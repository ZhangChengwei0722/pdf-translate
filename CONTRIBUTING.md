# Contributing

Thank you for helping improve PDF Translator Skill. Contributions should keep the workflow small, provider-neutral, and safe for original documents.

## Before opening an issue or pull request

- Check existing issues and the current `SKILL.md` contract.
- Describe the input shape, operating system, Python version, package versions, command, and the JSON result. Remove API keys, private paths, and user document content.
- For a behavior change, explain which of the two user choices, output guarantees, review states, or warning semantics are affected.

## Implementation rules

- Preserve the exactly-two-choice interaction: output mode and raster-figure review mode.
- Keep translation provider handling delegated to PDFMathTranslate. Do not add a forced provider or provider-specific secret handling.
- Keep the original PDF immutable and keep unselected outputs out of the delivery directory.
- Treat unsafe or failed raster-figure edits as retained originals with warnings; do not fail the entire paper for one figure.
- Do not add scanned-document OCR, persistent jobs, caches, manifests, reports, QA PDFs, databases, or services without a separately accepted design change.
- Vector content remains the responsibility of PDFMathTranslate/BabelDOC.
- The public repository must not contain user PDFs, private synthetic fixtures, API keys, generated review sessions, machine-specific paths, or generated local skill mirrors.

## Validation

Run these checks from the repository root before submitting a pull request:

```powershell
python -m py_compile scripts/run_pipeline.py scripts/figure_pipeline.py
python scripts/run_pipeline.py --help
```

Do not make a real provider request in CI. If a change requires an integration test, use a deterministic fake translator and synthetic in-memory or temporary input, and keep private acceptance fixtures outside the public repository.

## Pull requests

- Keep each pull request focused and explain the user-visible behavior.
- Include the commands used for validation and their relevant output.
- Update `README.md`, `SKILL.md`, or governance documents when the public contract changes.
- Do not commit generated `.codex` mirrors or unrelated workspace files.

By submitting a contribution, you agree that it may be distributed under this repository's AGPL-3.0-or-later license.
