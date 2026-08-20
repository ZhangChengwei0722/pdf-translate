"""figure_pipeline.py: safe raster figure text translation.

Only single-placement raster images clearly inside semantic figure regions
are modified. Pipeline stages:

  1. discover raster image XObject placements (PyMuPDF)
  2. predict semantic figure regions with the already-loaded BabelDOC
     DocLayout model (same instance PDFMathTranslate uses)
  3. keep only single-placement raster images that clearly intersect a
     figure region; exclude soft-mask, small icons and full-page backgrounds
  4. local RapidOCR on the original-resolution image
  5. deterministic scientific-token protection, then the shared
     config.translator.translate call (provider-neutral, text only)
  6. bounded Pillow redraw inside OCR masks only (background sampling,
     line fitting, finite font-size shrinking)
  7. unique-xref replacement; in-memory results only

Any unsafe condition retains the original figure and records a reason.
Vector figures are never touched here; PDFMathTranslate owns them.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Callable

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

CHINESE_FONT = Path(r"C:\Windows\Fonts\msyh.ttc")
OCR_CONFIDENCE = 0.55
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 62
BACKGROUND_PAD = 8
BACKGROUND_STD_LIMIT = 35.0
FIGURE_INTERSECTION_RATIO = 0.5
MIN_FIGURE_DIM = 40.0
SMALL_ICON_AREA_RATIO = 0.005
FULL_PAGE_RATIO = 0.95

# Deterministic scientific tokens (conservative, no NER, no dictionaries).
TOKEN_PATTERNS = [
    # number + unit combos
    r"\b\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?\s*(?:pM|nM|uM|mM|mg|ug|ng|pg|mL|uL|kb|kDa|%|°C|℃)\b",
    # bare numbers
    r"\b\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?\b",
    # hyphenated compound tokens (gene/protein/drug style, e.g. KRAS-G12D)
    r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+){1,}\b",
    # gene-style tokens with digits (e.g. p53, EGFRvIII, CDK4)
    r"\b[A-Za-z]{2,6}\d+(?:[A-Za-z]*)\b",
    # formula-style tokens containing math symbols
    r"\S*[\\^_{}]\S*",
    # panel identifiers like (A) (B) — conservative, avoids sentence words
    r"(?<![A-Za-z])[A-D](?=\))",
]


class FigureRetainError(Exception):
    """Raised when a figure must be kept as-is; reason is one of the
    FigureResult reason values."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def discover_placements(pdf_path: Path) -> dict[int, list[dict[str, Any]]]:
    """Map xref -> list of placements {page_index, rect, smask}."""
    document = fitz.open(pdf_path)
    placements: dict[int, list[dict[str, Any]]] = {}
    smask_cache: dict[int, bool] = {}
    try:
        for page_index, page in enumerate(document):
            xrefs = {image[0] for image in page.get_images(full=True)}
            for xref in xrefs:
                if xref not in smask_cache:
                    extracted = document.extract_image(xref)
                    smask_cache[xref] = bool(extracted.get("smask"))
                for rect in page.get_image_rects(xref):
                    placements.setdefault(xref, []).append(
                        {
                            "page_index": page_index,
                            "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                            "smask": smask_cache[xref],
                        }
                    )
    finally:
        document.close()
    return placements


def detect_figure_rects(doc_layout_model: Any, pdf_path: Path) -> dict[int, list[fitz.Rect]]:
    """DocLayout 'figure' class boxes per page, in PDF points (72 dpi = 1:1)."""
    from babeldoc.format.pdf.document_il.utils.mupdf_helper import get_no_rotation_img

    document = fitz.open(pdf_path)
    figure_rects: dict[int, list[fitz.Rect]] = {}
    try:
        for page_index, page in enumerate(document):
            pix = get_no_rotation_img(page, dpi=72)
            image = np.frombuffer(pix.samples, np.uint8).reshape(
                pix.height, pix.width, 3
            )[:, :, ::-1]
            predictions = doc_layout_model.predict(image)
            boxes = []
            for box in predictions[0].boxes:
                if predictions[0].names.get(box.cls) != "figure":
                    continue
                x0, y0, x1, y1 = [float(value) for value in box.xyxy]
                boxes.append(fitz.Rect(x0, y0, x1, y1))
            figure_rects[page_index] = boxes
    finally:
        document.close()
    return figure_rects


def _intersects_figure(rect: list[float], figure_rects: list[fitz.Rect]) -> bool:
    if not figure_rects:
        return False
    image_rect = fitz.Rect(rect)
    image_area = image_rect.width * image_rect.height
    if image_area <= 0:
        return False
    for figure_rect in figure_rects:
        intersection = image_rect & figure_rect
        if intersection.is_empty:
            continue
        if (intersection.width * intersection.height) / image_area >= FIGURE_INTERSECTION_RATIO:
            return True
    return False


# ---------------------------------------------------------------------------
# token protection
# ---------------------------------------------------------------------------

def protect_tokens(text: str) -> tuple[str, dict[str, str]]:
    """Replace every scientific token in ONE scan. Sequential per-pattern
    substitution would re-match the numeric placeholder digits (e.g. the
    bare-number rule matching the 0 inside [[0]]), producing nested
    placeholders and a false token_mismatch."""
    mapping: dict[str, str] = {}
    combined = re.compile("|".join(f"(?:{pattern})" for pattern in TOKEN_PATTERNS))

    def replace(match: re.Match) -> str:
        placeholder = f"[[{len(mapping)}]]"
        mapping[placeholder] = match.group(0)
        return placeholder

    return combined.sub(replace, text), mapping


def restore_tokens(text: str, mapping: dict[str, str]) -> str | None:
    """Restore protected tokens; None means a token went missing."""
    result = text
    for placeholder, token in mapping.items():
        if placeholder not in result:
            return None
        result = result.replace(placeholder, token)
    return result


# ---------------------------------------------------------------------------
# redraw
# ---------------------------------------------------------------------------

def fit_font(draw: ImageDraw.ImageDraw, text: str, width: int, height: int):
    """Returns (font, fits). Shrinks from height-based size down to
    MIN_FONT_SIZE; not fitting at MIN_FONT_SIZE is an overflow."""
    size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(height * 0.9)))
    while size > MIN_FONT_SIZE:
        font = ImageFont.truetype(str(CHINESE_FONT), size)
        bounds = draw.textbbox((0, 0), text, font=font)
        if bounds[2] - bounds[0] <= width and bounds[3] - bounds[1] <= height:
            return font, True
        size -= 2
    font = ImageFont.truetype(str(CHINESE_FONT), MIN_FONT_SIZE)
    bounds = draw.textbbox((0, 0), text, font=font)
    fits = bounds[2] - bounds[0] <= width and bounds[3] - bounds[1] <= height
    return font, fits


def background_color(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    x0, y0, x1, y1 = box
    pad = BACKGROUND_PAD
    crop = np.asarray(
        image.crop(
            (
                max(0, x0 - pad),
                max(0, y0 - pad),
                min(image.width, x1 + pad),
                min(image.height, y1 + pad),
            )
        ).convert("RGB")
    )
    median = np.median(crop.reshape(-1, 3), axis=0).astype(np.uint8)
    return tuple(int(value) for value in median)


def background_is_safe(image: Image.Image, box: tuple[int, int, int, int]) -> bool:
    """A ring around the OCR box must have low colour variance; gradients,
    heavy textures and transparency-like noise are unsafe to redraw over."""
    x0, y0, x1, y1 = box
    pad = BACKGROUND_PAD
    outer = (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(image.width, x1 + pad),
        min(image.height, y1 + pad),
    )
    inner = (x0, y0, x1, y1)
    if outer[2] <= outer[0] or outer[3] <= outer[1]:
        return False
    outer_crop = np.asarray(image.crop(outer).convert("RGB"))
    ring = np.ones(outer_crop.shape[:2], dtype=bool)
    ix0, iy0 = inner[0] - outer[0], inner[1] - outer[1]
    ring[iy0 : iy0 + (y1 - y0), ix0 : ix0 + (x1 - x0)] = False
    ring_pixels = outer_crop[ring]
    if ring_pixels.size == 0:
        return False
    std = ring_pixels.reshape(-1, 3).std(axis=0).mean()
    return float(std) <= BACKGROUND_STD_LIMIT


def redraw_ocr_labels(
    image_bytes: bytes,
    translator: Callable[..., str],
    ocr_engine: Any,
) -> tuple[bytes, list[dict[str, Any]], int]:
    """OCR -> protect -> translate -> restore -> bounded redraw.

    Raises FigureRetainError for any unsafe condition. Returns
    (png_bytes, records, outside_change_count)."""
    with Image.open(io.BytesIO(image_bytes)) as source:
        original = source.convert("RGB")
    try:
        result, _ = ocr_engine(np.asarray(original))
    except Exception:
        raise FigureRetainError("ocr_failed") from None
    if not result:
        raise FigureRetainError("ocr_failed")

    # 1. collect translatable labels (confidence + letters + real change)
    labels: list[dict[str, Any]] = []
    for item in result:
        polygon, source_text, confidence = item
        if float(confidence) < OCR_CONFIDENCE or not re.search(r"[A-Za-z]", source_text):
            continue
        protected, mapping = protect_tokens(source_text)
        try:
            try:
                translated_protected = translator(protected, ignore_cache=True)
            except TypeError:
                translated_protected = translator(protected)
        except Exception:
            # any provider-side failure (network, rate limit, upstream error)
            # keeps this single figure as-is and lets the paper continue
            raise FigureRetainError("translation_failed") from None
        translated = restore_tokens(translated_protected, mapping)
        if translated is None:
            raise FigureRetainError("token_mismatch")
        if not translated or translated == source_text:
            continue

        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        x0 = max(0, int(np.floor(min(xs))) - 4)
        y0 = max(0, int(np.floor(min(ys))) - 4)
        x1 = min(original.width, int(np.ceil(max(xs))) + 4)
        y1 = min(original.height, int(np.ceil(max(ys))) + 4)
        if x1 <= x0 or y1 <= y0:
            continue
        labels.append(
            {
                "source_text": source_text,
                "translated_text": translated,
                "protected_text": protected,
                "confidence": float(confidence),
                "box": (x0, y0, x1, y1),
                "polygon": polygon,
            }
        )

    if not labels:
        # OCR found text but nothing was safely translatable: no modification.
        raise FigureRetainError("no_safe_label")

    # 2. per-figure safety: any unsafe background -> keep the whole figure
    for label in labels:
        if not background_is_safe(original, label["box"]):
            raise FigureRetainError("unsafe_background")

    # 3. redraw
    redrawn = original.copy()
    draw = ImageDraw.Draw(redrawn)
    masks: list[tuple[int, int, int, int]] = []
    records: list[dict[str, Any]] = []
    for label in labels:
        x0, y0, x1, y1 = label["box"]
        fill = background_color(original, (x0, y0, x1, y1))
        draw.rectangle((x0, y0, x1, y1), fill=fill)
        font, fits = fit_font(draw, label["translated_text"], x1 - x0, y1 - y0)
        if not fits:
            raise FigureRetainError("text_overflow")
        bounds = draw.textbbox((0, 0), label["translated_text"], font=font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        text_x = x0 + max(0, (x1 - x0 - text_width) // 2)
        text_y = y0 + max(0, (y1 - y0 - text_height) // 2) - bounds[1]
        draw.text((text_x, text_y), label["translated_text"], fill="black", font=font)
        masks.append((x0, y0, x1, y1))
        records.append(
            {
                "source_text": label["source_text"],
                "translated_text": label["translated_text"],
                "confidence": round(label["confidence"], 4),
                "image_box": [x0, y0, x1, y1],
            }
        )

    # 4. defensive: nothing changed outside OCR masks inside this image
    original_pixels = np.asarray(original)
    redrawn_pixels = np.asarray(redrawn)
    allowed = np.zeros((original.height, original.width), dtype=bool)
    for x0, y0, x1, y1 in masks:
        allowed[y0:y1, x0:x1] = True
    changed = np.any(original_pixels != redrawn_pixels, axis=2)
    outside_change_count = int(np.count_nonzero(changed & ~allowed))
    if outside_change_count > 0:
        raise FigureRetainError("render_failed")

    output = io.BytesIO()
    redrawn.save(output, format="PNG")
    return output.getvalue(), records, outside_change_count


# ---------------------------------------------------------------------------
# candidate assembly + edits
# ---------------------------------------------------------------------------

def build_safe_edits(
    pdf_path: Path,
    placements: dict[int, list[dict[str, Any]]],
    figure_rects: dict[int, list[fitz.Rect]],
    translator: Callable[..., str],
    ocr_engine: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Returns (edits, ocr_summary, results). Retained figures carry
    {id, page, status: retained, reason}."""
    if ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        ocr_engine = RapidOCR()
    document = fitz.open(pdf_path)
    edits: list[dict[str, Any]] = []
    ocr_summary: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    try:
        for xref, xref_placements in placements.items():
            figure_id = f"p{xref_placements[0]['page_index'] + 1}-xref{xref}"
            if len(xref_placements) != 1:
                # reused image object: kept as-is, but this is a raster figure
                # so the chat report must say it was retained and why
                results.append(
                    {
                        "id": figure_id,
                        "page": xref_placements[0]["page_index"] + 1,
                        "status": "retained",
                        "reason": "reused_image",
                    }
                )
                continue
            placement = xref_placements[0]
            page_index = placement["page_index"]

            if placement.get("smask"):
                # soft-mask (transparency) image: kept as-is with a record
                results.append(
                    {
                        "id": figure_id,
                        "page": page_index + 1,
                        "status": "retained",
                        "reason": "soft_mask",
                    }
                )
                continue
            if not _intersects_figure(placement["rect"], figure_rects.get(page_index, [])):
                continue  # not a semantic figure -> excluded silently
            rect = fitz.Rect(placement["rect"])
            page = document[page_index]
            if rect.width < MIN_FIGURE_DIM or rect.height < MIN_FIGURE_DIM:
                continue  # small icon -> excluded silently
            page_area = page.rect.width * page.rect.height
            image_area = rect.width * rect.height
            if image_area >= page_area * FULL_PAGE_RATIO:
                continue  # full-page background -> excluded silently
            if image_area < page_area * SMALL_ICON_AREA_RATIO:
                continue  # tiny area -> excluded silently

            extracted = document.extract_image(xref)
            image_bytes = extracted["image"]
            try:
                translated_bytes, records, outside_change_count = redraw_ocr_labels(
                    image_bytes, translator, ocr_engine
                )
            except FigureRetainError as error:
                results.append(
                    {
                        "id": figure_id,
                        "page": page_index + 1,
                        "status": "retained",
                        "reason": error.reason,
                    }
                )
                continue
            except Exception:
                # defensive: any unexpected per-figure failure keeps the
                # original figure and never aborts the paper translation
                results.append(
                    {
                        "id": figure_id,
                        "page": page_index + 1,
                        "status": "retained",
                        "reason": "translation_failed",
                    }
                )
                continue

            with Image.open(io.BytesIO(image_bytes)) as image:
                image_size = image.size
            for record in records:
                record["page_box"] = map_image_box_to_page(
                    record["image_box"], image_size, placement["rect"]
                )
            edits.append(
                {
                    "id": figure_id,
                    "xref": xref,
                    "page_index": page_index,
                    "placement_rect": placement["rect"],
                    "translated_image": translated_bytes,
                }
            )
            ocr_summary[figure_id] = {
                "image_size": list(image_size),
                "labels": records,
                "outside_mask_change_count": outside_change_count,
            }
            results.append(
                {
                    "id": figure_id,
                    "page": page_index + 1,
                    "status": "translated",
                    "reason": "none",
                }
            )
    finally:
        document.close()
    return edits, ocr_summary, results


def map_image_box_to_page(
    image_box: list[int],
    image_size: tuple[int, int],
    placement_rect: list[float],
) -> list[float]:
    x0, y0, x1, y1 = image_box
    width, height = image_size
    rect = fitz.Rect(placement_rect)
    return [
        rect.x0 + (x0 / width) * rect.width,
        rect.y0 + (y0 / height) * rect.height,
        rect.x0 + (x1 / width) * rect.width,
        rect.y0 + (y1 / height) * rect.height,
    ]


def apply_edits(source_pdf: Path, edits: list[dict[str, Any]], output_pdf: Path) -> None:
    document = fitz.open(source_pdf)
    try:
        for edit in edits:
            page = document[edit["page_index"]]
            page.replace_image(edit["xref"], stream=edit["translated_image"])
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_pdf, garbage=0, deflate=True)
    finally:
        document.close()


# ---------------------------------------------------------------------------
# entry point used by run_pipeline.py
# ---------------------------------------------------------------------------

def process(
    babeldoc_config: Any,
    work_pdf: Path,
    temp_dir: Path,
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (prepared_pdf, edits, results, warnings)."""

    def translator(text: str, ignore_cache: bool = False) -> str:
        return babeldoc_config.translator.translate(text, ignore_cache=ignore_cache)

    from rapidocr_onnxruntime import RapidOCR

    ocr_engine = RapidOCR()
    placements = discover_placements(work_pdf)
    figure_rects = detect_figure_rects(babeldoc_config.doc_layout_model, work_pdf)
    edits, _ocr_summary, results = build_safe_edits(
        work_pdf, placements, figure_rects, translator, ocr_engine
    )
    if not edits:
        return work_pdf, [], results, _warnings_from_results(results)

    # keep the original stem so upstream output names stay recognisable
    prepared_dir = temp_dir / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    prepared_pdf = prepared_dir / work_pdf.name
    apply_edits(work_pdf, edits, prepared_pdf)
    return prepared_pdf, edits, results, _warnings_from_results(results)


def _warnings_from_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"page": result["page"], "figure_id": result["id"], "reason": result["reason"]}
        for result in results
        if result.get("status") == "retained"
    ]
