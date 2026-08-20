# PDF Translator Skill

`pdf-translate` is a portable skill for translating scientific paper PDFs into Chinese while preserving the source document and the upstream PDFMathTranslate workflow.

The skill adds a conservative raster-figure pipeline around PDFMathTranslate (pdf2zh-next + BabelDOC): it detects semantic raster figures, runs local OCR, translates recognized labels with the same upstream translator, and redraws only bounded OCR regions. Unsafe or failed figure edits retain the original image and produce a warning.

## What it does

- Keeps the original PDF untouched and never deletes or overwrites an existing output.
- Delegates body text, captions, tables, formulas, vector figures, and PDF writing to PDFMathTranslate.
- Translates text inside safe raster figures with RapidOCR and Pillow.
- Preserves scientific tokens such as units, gene-style names, panel identifiers, and formula-like text during translation.
- Isolates figure failures: one failed or unsafe figure does not fail the whole paper.
- Supports exactly three output modes: `mono`, `dual`, and `mono+dual`.
- Supports exactly three raster-figure review modes: `multimodal`, `human`, and `none`.
- Returns a small JSON result on stdout and cleans temporary review sessions after completion, cancellation, or failure.

The provider is deliberately not hard-coded. Arguments after `--` are forwarded to PDFMathTranslate in their original order, so the provider and credentials remain under the user's existing PDFMathTranslate configuration.

## Scope and limitations

This skill is designed for born-digital, text-based scientific PDFs. It does not add scanned-document preprocessing or full-document OCR. Vector content remains owned by PDFMathTranslate/BabelDOC; this skill only considers raster image objects that pass its semantic and safety filters.

The skill does not perform CJK-ratio gates, file-size gates, page-count gates, full-page pixel diffs, or other heuristic checks that can report false failures. It does not create persistent jobs, caches, manifests, QA PDFs, reports, databases, or review HTML. Temporary review material is kept under the operating system temporary directory and is removed when the workflow ends.

Translated PDFs are reading aids. Cite the original publication, not a translated artifact.

## Requirements

The validated baseline is:

| Component | Version |
| --- | --- |
| Python | 3.10 or newer |
| pdf2zh-next | 2.9.0 |
| BabelDOC | 0.6.2 |
| PyMuPDF | 1.25.2 |
| rapidocr-onnxruntime | 1.4.4 |
| Pillow | 11.3.0 |

The host also needs a CJK font. The current Windows implementation uses Microsoft YaHei (`msyh.ttc`) from the standard Windows fonts directory; environments without that font should adapt the font constant before use. The skill does not install dependencies or fonts.

Install the validated Python dependencies in the environment that will run the skill:

```powershell
python -m pip install `
  "pdf2zh-next==2.9.0" `
  "BabelDOC==0.6.2" `
  "PyMuPDF==1.25.2" `
  "rapidocr-onnxruntime==1.4.4" `
  "Pillow==11.3.0"
```

The PowerShell launcher expects `python` and the PDFMathTranslate `pdf2zh` executable to be available on `PATH`.

## Install the skill

Copy this repository directory into the skill directory used by your compatible Agent host, keeping `SKILL.md` beside `scripts/`. For a Codex-compatible installation the resulting layout is:

```text
skills/
└── PDF-translate/
    ├── SKILL.md
    └── scripts/
        ├── figure_pipeline.py
        ├── pdf2zh-zh.ps1
        └── run_pipeline.py
```

Do not copy user PDFs, provider keys, temporary review sessions, or private test fixtures into the repository.

## Usage

Before every run, the Agent must confirm two user choices. If one choice is already known, ask only for the other; if both are missing, ask both in one message. No conversion starts until the two choices are known.

### 1. Output mode

| Mode | Delivered output |
| --- | --- |
| `mono` | Chinese-only PDF |
| `dual` | Chinese-English comparison PDF |
| `mono+dual` | Both PDFs |

Only the selected output(s) are handed to the user. Existing files are never overwritten; a unique suffix is used when a destination name already exists.

### 2. Raster-figure review mode

| Mode | Behavior |
| --- | --- |
| `multimodal` | The Agent inspects generated figure previews and accepts or rejects affected figures. |
| `human` | The workflow pauses with previews and waits for the user's accept/reject decision. |
| `none` | No figure preview review is performed. |

If no raster figure is safely modified, review is automatically `not_applicable` and no session is created.

### Start a translation

The launcher forwards provider options after `--`; replace the placeholder with arguments already supported by your PDFMathTranslate installation. Do not add a provider-specific branch to this skill.

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\pdf2zh-zh.ps1" `
  start --input "<input.pdf>" --output-mode mono --review-mode human `
  -- <the same provider/configuration arguments accepted by PDFMathTranslate>
```

The command prints one JSON object. Typical fields include `status`, `outputs`, `session_dir`, `previews`, `translated_figures`, `retained_figures`, `warnings`, and `review_status`.

### Continue a reviewed translation

For `human` or `multimodal`, the start response contains the temporary session directory and figure IDs. Continue only after every preview has a decision:

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\pdf2zh-zh.ps1" `
  continue --session "<session-dir>" `
  --accept "p2-xref17,p5-xref42" `
  --reject "p7-xref61" `
  -- <the same provider/configuration arguments accepted by PDFMathTranslate>
```

The `continue` command must receive the same provider/configuration arguments as `start`; temporary sessions never store credentials or provider settings.

## Failure handling

- A missing or invalid input fails before conversion and leaves the source untouched.
- A provider error, OCR failure, token mismatch, unsafe background, soft mask, reused image, overflow, or review rejection retains the affected raster figure and reports a warning.
- A failure in one raster figure is isolated from other figures and from the rest of the paper.
- If the validated pdf2zh-next/BabelDOC versions are unavailable, or RapidOCR/DocLayout cannot be loaded, the pipeline falls back to ordinary `pdf2zh` translation and warns that raster figures were not processed.
- If PDFMathTranslate itself fails or a selected output is missing, the whole run is reported as failed; no incomplete output is claimed as delivered.

## Development checks

The public repository intentionally does not contain private PDFs or the internal P0 fixture set. Run the lightweight checks from the repository root:

```powershell
python -m py_compile scripts/run_pipeline.py scripts/figure_pipeline.py
python scripts/run_pipeline.py --help
```

The GitHub Actions workflow performs the same syntax/help checks and verifies the public file layout without contacting a translation provider or downloading model assets.

## Repository layout

```text
SKILL.md                         Skill contract and Agent-facing workflow
scripts/                         PowerShell launcher and Python pipeline
README.md                        User and contributor documentation
LICENSE                          GNU AGPL v3 or later
NOTICE                           Project copyright and dependency boundary
THIRD_PARTY_NOTICES.md           Dependency and attribution notes
CONTRIBUTING.md                  Contribution and testing rules
SECURITY.md                      Security reporting policy
CODE_OF_CONDUCT.md               Community expectations
.github/                         CI and issue/PR templates
```

## Acknowledgments

This skill stands on the work of the following open-source projects:

- [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) (AGPL-3.0): upstream scientific PDF translation interface, provider configuration, mono/dual output, and high-level orchestration.
- [BabelDOC](https://github.com/funstory-ai/BabelDOC) (AGPL-3.0): document translation and layout-preserving PDF generation used by PDFMathTranslate.
- [RapidOCR](https://github.com/RapidAI/RapidOCR) (Apache-2.0): local OCR used to recognize text in raster figures.
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0): PDF inspection, image-object discovery, placement mapping, and bounded raster replacement.
- [Pillow](https://github.com/python-pillow/Pillow) (MIT-CMU): local image decoding, masking, font fitting, and redraw operations.

The repository calls these projects through their public or verified APIs and does not copy large portions of their source code. Their licenses and notices remain their respective authors' responsibility; see `THIRD_PARTY_NOTICES.md` for the dependency boundary.

## License

The skill code and documentation in this repository are released under the [GNU Affero General Public License v3.0 or later](LICENSE). Runtime dependencies are separate works and remain under their own licenses.
