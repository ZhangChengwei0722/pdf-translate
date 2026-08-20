"""PDF Translator orchestrator for the PDF-translate skill.

Usage:
  run_pipeline.py start --input <pdf> --output-mode <mono|dual|mono+dual>
                       --review-mode <multimodal|human|none> [-- <pdf2zh args...>]
  run_pipeline.py continue --session <dir> --accept <ids> --reject <ids>
                           [-- <pdf2zh args...>]

Pipeline (start):
  choices -> versions allowlist -> resolve pdf2zh settings once ->
  working copy (original stem) -> raster figure edits (figure_pipeline.py,
  optional) -> review split (session only for human/multimodal with edits) ->
  BabelDOC translation -> minimal output check -> unique-name handoff ->
  stdout JSON -> cleanup owned temp files.

The original PDF is never modified, overwritten or deleted. Only the
user-selected output PDFs are delivered. No persistent jobs, cache, reports,
manifests or QA files are created.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

ALLOWED_VERSIONS = {"pdf2zh-next": "2.9.0", "BabelDOC": "0.6.2"}
TEMP_ROOT = Path(tempfile.gettempdir()) / "pdf-translator"
SESSION_SCHEMA_VERSION = 1
OUTPUT_MODES = ("mono", "dual", "mono+dual")
REVIEW_MODES = ("multimodal", "human", "none")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def emit(payload: dict[str, Any], exit_code: int) -> int:
    """Print one small stdout JSON object (never written to disk)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False))
    return exit_code


def ensure_within(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    resolved_parent = parent.resolve()
    if resolved != resolved_parent and resolved_parent not in resolved.parents:
        raise RuntimeError(f"Refusing operation outside {resolved_parent}: {resolved}")


def check_supported_versions() -> tuple[bool, dict[str, str]]:
    from importlib.metadata import PackageNotFoundError, version

    installed: dict[str, str] = {}
    for package in ALLOWED_VERSIONS:
        try:
            installed[package] = version(package)
        except PackageNotFoundError:
            installed[package] = "missing"
    ok = all(installed.get(p) == v for p, v in ALLOWED_VERSIONS.items())
    return ok, installed


def resolve_target_dir(input_pdf: Path, raw_args: list[str]) -> Path:
    """User --output value wins; otherwise the original PDF directory."""
    for index, token in enumerate(raw_args):
        if token == "--output" and index + 1 < len(raw_args):
            return Path(raw_args[index + 1])
        if token.startswith("--output="):
            return Path(token.split("=", 1)[1])
    return input_pdf.parent


def strip_output_arg(raw_args: list[str]) -> list[str]:
    """Remove --output (and its value) so the fallback can redirect output."""
    stripped: list[str] = []
    index = 0
    while index < len(raw_args):
        token = raw_args[index]
        if token == "--output":
            index += 2
            continue
        if token.startswith("--output="):
            index += 1
            continue
        stripped.append(token)
        index += 1
    return stripped


def mode_flags(output_mode: str) -> list[str]:
    if output_mode == "mono":
        return ["--no-dual"]
    if output_mode == "dual":
        return ["--no-mono"]
    return []


def resolve_settings(raw_args: list[str]) -> Any:
    """Resolve PDFMathTranslate settings exactly once, honouring its own
    config file, environment variables and defaults (no provider forcing)."""
    from pdf2zh_next.config import ConfigManager

    original_argv = sys.argv
    sys.argv = ["pdf2zh"] + list(raw_args)
    try:
        cli_settings = ConfigManager().initialize_cli_config()
        settings = cli_settings.to_settings_model()
    finally:
        sys.argv = original_argv
    return settings


def copy_work_pdf(input_pdf: Path, temp_root: Path) -> Path:
    """Working copy that keeps the original stem so upstream output names stay
    recognisable (e.g. <stem>.zh.mono.pdf)."""
    work_pdf = temp_root / f"{input_pdf.stem}.pdf"
    shutil.copy2(input_pdf, work_pdf)
    return work_pdf


def check_pdf_openable(path: Path) -> bool:
    try:
        import fitz
    except ImportError:
        return False
    try:
        document = fitz.open(path)
        try:
            return document.page_count >= 1
        finally:
            document.close()
    except Exception:
        return False


@contextlib.contextmanager
def silence_stdout_fd():
    """Redirect file descriptor 1 to devnull while upstream child processes
    run. PDFMathTranslate's subprocess inherits fd 1 and its RichHandler logs
    to stdout, which would pollute our single-JSON stdout contract."""
    saved_fd = os.dup(1)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        yield
    finally:
        os.dup2(saved_fd, 1)
        os.close(devnull_fd)
        os.close(saved_fd)


def unique_destination(target_dir: Path, name: str) -> Path:
    """Never overwrite an existing file; append a counter before the suffix."""
    candidate = target_dir / name
    if not candidate.exists():
        return candidate
    suffix = candidate.suffix
    stem = candidate.name[: -len(suffix)] if suffix else candidate.name
    for index in range(1, 10000):
        candidate = target_dir / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate
    return target_dir / f"{stem}.{uuid.uuid4().hex[:6]}{suffix}"


def render_preview(pdf_path: Path, page_index: int, rect: list[float], output: Path) -> None:
    import fitz

    document = fitz.open(pdf_path)
    try:
        page = document[page_index]
        clip = fitz.Rect(rect)
        expanded = fitz.Rect(clip.x0 - 8, clip.y0 - 8, clip.x1 + 8, clip.y1 + 8) & page.rect
        page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=expanded, alpha=False).save(output)
    finally:
        document.close()


# ---------------------------------------------------------------------------
# figure stage (figure_pipeline.py is optional; Stage A runs without edits)
# ---------------------------------------------------------------------------

def process_figures(babeldoc_config: Any, work_pdf: Path, temp_root: Path):
    """Returns (prepared_pdf, edits, results, warnings)."""
    try:
        import figure_pipeline
    except ImportError:
        return (
            work_pdf,
            [],
            [],
            [{"page": None, "figure_id": None, "reason": "figure_pipeline not available; raster figures not processed"}],
        )
    return figure_pipeline.process(babeldoc_config, work_pdf, temp_root)


# ---------------------------------------------------------------------------
# review session (shared by human and multimodal; schema identical)
# ---------------------------------------------------------------------------

def create_review_session(
    source_pdf: Path,
    prepared_pdf: Path,
    edits: list[dict[str, Any]],
    review_mode: str,
    output_mode: str,
    session_dir: Path,
) -> dict[str, Any]:
    preview_dir = session_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_prepared = session_dir / "prepared.pdf"
    if prepared_pdf.resolve() != target_prepared.resolve():
        shutil.copy2(prepared_pdf, target_prepared)

    figures = []
    for edit in edits:
        preview = preview_dir / f"{edit['id']}.png"
        render_preview(target_prepared, edit["page_index"], edit["placement_rect"], preview)
        figures.append(
            {
                "id": edit["id"],
                "page_index": edit["page_index"],
                "xref": edit["xref"],
                "preview": str(preview),
            }
        )

    metadata = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_dir.name,
        "review_mode": review_mode,
        "output_mode": output_mode,
        "source_pdf": str(source_pdf.resolve()),
        "prepared_pdf": str(target_prepared.resolve()),
        "figures": figures,
    }
    (session_dir / "review-session.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def apply_review_decisions(session_dir: Path, accepted: set[str], rejected: set[str]) -> Path:
    """Revert rejected figures from the read-only source PDF and write the
    final prepared PDF. session_dir must be inside TEMP_ROOT."""
    ensure_within(session_dir, TEMP_ROOT)
    metadata_path = session_dir / "review-session.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    figure_ids = {figure["id"] for figure in metadata["figures"]}
    if accepted & rejected:
        raise ValueError("A figure cannot be both accepted and rejected")
    if accepted | rejected != figure_ids:
        raise ValueError("Review decision must cover every figure")

    import fitz

    source = fitz.open(metadata["source_pdf"])
    prepared = fitz.open(metadata["prepared_pdf"])
    try:
        for figure in metadata["figures"]:
            if figure["id"] not in rejected:
                continue
            original_image = source.extract_image(figure["xref"])["image"]
            prepared[figure["page_index"]].replace_image(figure["xref"], stream=original_image)
        # keep the original stem so upstream output names stay recognisable
        final_prepared = session_dir / f"{Path(metadata['source_pdf']).stem}.pdf"
        prepared.save(final_prepared, garbage=0, deflate=True)
    finally:
        prepared.close()
        source.close()
    return final_prepared


# ---------------------------------------------------------------------------
# BabelDOC invocation
# ---------------------------------------------------------------------------

async def _translate_async(settings: Any, pdf_path: Path) -> Any:
    from pdf2zh_next.high_level import do_translate_async_stream

    async for event in do_translate_async_stream(settings, pdf_path):
        event_type = event.get("type")
        if event_type == "finish":
            return event["translate_result"]
        if event_type == "error":
            raise RuntimeError(
                f"PDFMathTranslate error: {event.get('error')} ({event.get('error_type', '')})"
            )
    raise RuntimeError("PDFMathTranslate finished without a finish event")


def run_babeldoc(settings: Any, pdf_path: Path) -> Any:
    with silence_stdout_fd():
        return asyncio.run(_translate_async(settings, pdf_path))


def selected_result_paths(result: Any, output_mode: str) -> list[Path]:
    paths = []
    if output_mode in ("mono", "mono+dual"):
        paths.append(result.mono_pdf_path)
    if output_mode in ("dual", "mono+dual"):
        paths.append(result.dual_pdf_path)
    return [Path(path) for path in paths if path]


def handoff_outputs(result: Any, output_mode: str, target_dir: Path) -> list[Path]:
    delivered: list[Path] = []
    for source in selected_result_paths(result, output_mode):
        if not source.is_file():
            raise RuntimeError(f"Selected output missing: {source}")
        if not check_pdf_openable(source):
            raise RuntimeError(f"Selected output cannot be opened or is empty: {source}")
        destination = unique_destination(target_dir, source.name)
        shutil.copy2(source, destination)
        delivered.append(destination)
    return delivered


# ---------------------------------------------------------------------------
# fallback: unsupported versions / missing RapidOCR / DocLayout unavailable
# ---------------------------------------------------------------------------

def run_fallback(
    input_pdf: Path,
    raw_args: list[str],
    output_mode: str,
    target_dir: Path,
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    pdf2zh = shutil.which("pdf2zh")
    if not pdf2zh:
        return {
            "status": "failed",
            "error": "pdf2zh executable not found; cannot fall back to plain PDFMathTranslate",
            "outputs": [],
            "session_dir": None,
            "previews": [],
            "translated_figures": 0,
            "retained_figures": 0,
            "warnings": warnings,
            "review_status": "not_applicable",
        }

    temp_root = TEMP_ROOT / f"pdf-translate-{uuid.uuid4().hex[:12]}"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        temp_out = temp_root / "out"
        temp_out.mkdir(parents=True, exist_ok=True)
        command = (
            [pdf2zh, str(input_pdf), "--output", str(temp_out)]
            + mode_flags(output_mode)
            + strip_output_arg(raw_args)
        )
        completed = subprocess.run(
            command, cwd=temp_out, stdout=subprocess.DEVNULL, stderr=None
        )
        if completed.returncode != 0:
            return {
                "status": "failed",
                "error": f"pdf2zh failed with exit code {completed.returncode}",
                "outputs": [],
                "session_dir": None,
                "previews": [],
                "translated_figures": 0,
                "retained_figures": 0,
                "warnings": warnings,
                "review_status": "not_applicable",
            }

        mono_files = sorted(temp_out.glob("*.mono.pdf"))
        dual_files = sorted(temp_out.glob("*.dual.pdf"))
        expected = []
        if output_mode in ("mono", "mono+dual"):
            expected.append(mono_files)
        if output_mode in ("dual", "mono+dual"):
            expected.append(dual_files)
        if any(not group for group in expected):
            return {
                "status": "failed",
                "error": f"Selected output missing after pdf2zh: {output_mode}",
                "outputs": [],
                "session_dir": None,
                "previews": [],
                "translated_figures": 0,
                "retained_figures": 0,
                "warnings": warnings,
                "review_status": "not_applicable",
            }

        delivered: list[Path] = []
        for group in expected:
            for source in group:
                if not check_pdf_openable(source):
                    continue
                delivered.append(
                    unique_destination(target_dir, source.name)
                )
                shutil.copy2(source, delivered[-1])
        if not delivered:
            return {
                "status": "failed",
                "error": "Selected outputs cannot be opened after pdf2zh",
                "outputs": [],
                "session_dir": None,
                "previews": [],
                "translated_figures": 0,
                "retained_figures": 0,
                "warnings": warnings,
                "review_status": "not_applicable",
            }
        return {
            "status": "completed",
            "outputs": [str(path) for path in delivered],
            "session_dir": None,
            "previews": [],
            "translated_figures": 0,
            "retained_figures": 0,
            "warnings": warnings,
            "review_status": "not_applicable",
        }
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def classify_review(edits: list[dict[str, Any]], review_mode: str) -> str:
    """Single source of truth for the review split:
    no successful figure edits -> not_applicable (no pause, no preview);
    none -> not_reviewed (continue directly); human/multimodal with edits ->
    pending (minimal temp session)."""
    if not edits:
        return "not_applicable"
    if review_mode == "none":
        return "not_reviewed"
    return "pending"


def cmd_start(opts: argparse.Namespace, raw_args: list[str]) -> int:
    missing = []
    if not opts.output_mode:
        missing.append("output_mode")
    if not opts.review_mode:
        missing.append("review_mode")
    if missing:
        return emit(
            {
                "status": "choices_required",
                "missing": missing,
                "outputs": [],
                "session_dir": None,
                "previews": [],
                "translated_figures": 0,
                "retained_figures": 0,
                "warnings": [],
                "review_status": None,
            },
            0,
        )

    input_pdf = Path(opts.input).expanduser() if opts.input else None
    if input_pdf is None or not input_pdf.is_file():
        return emit({"status": "failed", "error": f"Input PDF not found: {opts.input}", "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)
    if input_pdf.suffix.lower() != ".pdf":
        return emit({"status": "failed", "error": f"Input is not a PDF: {opts.input}", "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)

    target_dir = resolve_target_dir(input_pdf, raw_args)
    target_dir.mkdir(parents=True, exist_ok=True)

    versions_ok, installed = check_supported_versions()
    if not versions_ok:
        warnings = [
            {
                "page": None,
                "figure_id": None,
                "reason": f"unsupported versions {installed}; expected {ALLOWED_VERSIONS}; raster figures not processed",
            }
        ]
        payload = run_fallback(input_pdf, raw_args, opts.output_mode, target_dir, warnings)
        return emit(payload, 1 if payload["status"] == "failed" else 0)

    if importlib.util.find_spec("rapidocr_onnxruntime") is None:
        warnings = [{"page": None, "figure_id": None, "reason": "rapidocr-onnxruntime not installed; raster figures not processed"}]
        return emit(run_fallback(input_pdf, raw_args, opts.output_mode, target_dir, warnings), 0)

    temp_root = TEMP_ROOT / f"pdf-translate-{uuid.uuid4().hex[:12]}"
    temp_root.mkdir(parents=True, exist_ok=True)
    keep_session = False
    try:
        work_pdf = copy_work_pdf(input_pdf, temp_root)

        settings = resolve_settings(raw_args)
        settings.basic.input_files = {str(input_pdf)}
        settings.pdf.no_mono = opts.output_mode == "dual"
        settings.pdf.no_dual = opts.output_mode == "mono"
        settings.translation.output = str(temp_root / "out")

        try:
            from pdf2zh_next.high_level import create_babeldoc_config

            config = create_babeldoc_config(settings, work_pdf)
        except Exception as exc:
            warnings = [{"page": None, "figure_id": None, "reason": f"DocLayout/config unavailable ({exc}); raster figures not processed"}]
            return emit(run_fallback(input_pdf, raw_args, opts.output_mode, target_dir, warnings), 0)

        prepared_pdf, edits, results, warnings = process_figures(config, work_pdf, temp_root)

        translated = sum(1 for item in results if item.get("status") == "translated")
        retained = sum(1 for item in results if item.get("status") == "retained")

        review_status = classify_review(edits, opts.review_mode)
        if review_status == "pending":
            metadata = create_review_session(input_pdf, prepared_pdf, edits, opts.review_mode, opts.output_mode, temp_root)
            keep_session = True
            return emit(
                {
                    "status": "review_required",
                    "session_dir": str(temp_root),
                    "previews": metadata["figures"],
                    "translated_figures": translated,
                    "retained_figures": retained,
                    "warnings": warnings,
                    "review_status": review_status,
                },
                0,
            )

        result = run_babeldoc(settings, prepared_pdf)
        delivered = handoff_outputs(result, opts.output_mode, target_dir)
        return emit(
            {
                "status": "completed",
                "outputs": [str(path) for path in delivered],
                "session_dir": None,
                "previews": [],
                "translated_figures": translated,
                "retained_figures": retained,
                "warnings": warnings,
                "review_status": review_status,
            },
            0,
        )
    except Exception as exc:
        return emit({"status": "failed", "error": str(exc), "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)
    finally:
        if not keep_session:
            shutil.rmtree(temp_root, ignore_errors=True)


def cmd_continue(opts: argparse.Namespace, raw_args: list[str]) -> int:
    if not opts.session:
        return emit({"status": "failed", "error": "continue requires --session", "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)
    session_dir = Path(opts.session)
    try:
        ensure_within(session_dir, TEMP_ROOT)
    except RuntimeError as exc:
        return emit({"status": "failed", "error": str(exc), "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)

    metadata_path = session_dir / "review-session.json"
    if not metadata_path.is_file():
        return emit({"status": "failed", "error": f"review-session.json not found: {session_dir}", "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    accepted = {item.strip() for item in (opts.accept or "").split(",") if item.strip()}
    rejected = {item.strip() for item in (opts.reject or "").split(",") if item.strip()}
    figure_ids = {figure["id"] for figure in metadata["figures"]}
    if accepted & rejected:
        return emit({"status": "failed", "error": "A figure cannot be both accepted and rejected", "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)
    if accepted | rejected != figure_ids:
        return emit({"status": "failed", "error": f"Review decision must cover every figure: {sorted(figure_ids)}", "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)

    output_mode = metadata.get("output_mode", "mono+dual")
    source_pdf = Path(metadata["source_pdf"])
    target_dir = resolve_target_dir(source_pdf, raw_args)
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_root = session_dir
    try:
        settings = resolve_settings(raw_args)
        settings.basic.input_files = {str(source_pdf)}
        settings.pdf.no_mono = output_mode == "dual"
        settings.pdf.no_dual = output_mode == "mono"
        settings.translation.output = str(temp_root / "out")

        final_prepared = apply_review_decisions(session_dir, accepted, rejected)
        result = run_babeldoc(settings, final_prepared)
        delivered = handoff_outputs(result, output_mode, target_dir)
        rejected_ids = sorted(rejected)
        return emit(
            {
                "status": "completed",
                "outputs": [str(path) for path in delivered],
                "session_dir": None,
                "previews": [],
                "translated_figures": len(figure_ids) - len(rejected_ids),
                "retained_figures": len(rejected_ids),
                "warnings": [{"page": None, "figure_id": figure_id, "reason": "rejected in review"} for figure_id in rejected_ids],
                "review_status": "checked",
            },
            0,
        )
    except Exception as exc:
        return emit({"status": "failed", "error": str(exc), "outputs": [], "session_dir": None, "previews": [], "translated_figures": 0, "retained_figures": 0, "warnings": [], "review_status": None}, 1)
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description="PDF Translator orchestrator: two user choices, raster figure safety, PDFMathTranslate reuse.",
    )
    parser.add_argument("command", choices=("start", "continue"))
    parser.add_argument("--input", help="Input PDF path (start)")
    parser.add_argument("--output-mode", choices=OUTPUT_MODES, help="mono | dual | mono+dual")
    parser.add_argument("--review-mode", choices=REVIEW_MODES, help="multimodal | human | none")
    parser.add_argument("--session", help="Review session directory (continue)")
    parser.add_argument("--accept", help="Comma-separated figure ids to accept (continue)")
    parser.add_argument("--reject", help="Comma-separated figure ids to reject (continue)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    # argparse's parse_known_args keeps the "--" separator itself in extras;
    # split it manually so everything after "--" is passed through verbatim
    # as PDFMathTranslate arguments.
    if "--" in argv:
        split = argv.index("--")
        opts, pre_extras = parser.parse_known_args(argv[:split])
        extras = pre_extras + argv[split + 1 :]
    else:
        opts, extras = parser.parse_known_args(argv)
    if opts.command == "start":
        return cmd_start(opts, extras)
    return cmd_continue(opts, extras)


if __name__ == "__main__":
    raise SystemExit(main())
