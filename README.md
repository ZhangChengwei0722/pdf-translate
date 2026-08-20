# PDF Translator Skill / PDF 翻译 Skill

`pdf-translate` is a portable skill for translating scientific paper PDFs into Chinese while preserving the source document and the upstream PDFMathTranslate workflow.

`pdf-translate` 是一个可移植的 Skill，用于将科研论文 PDF 翻译成中文，同时保留原始文档和上游 PDFMathTranslate 工作流。

The skill adds a conservative raster-figure pipeline around PDFMathTranslate (pdf2zh-next + BabelDOC): it detects semantic raster figures, runs local OCR, translates recognized labels with the same upstream translator, and redraws only bounded OCR regions. Unsafe or failed figure edits retain the original image and produce a warning.

本 Skill 在 PDFMathTranslate（pdf2zh-next + BabelDOC）外增加了保守的 raster figure 处理流程：识别语义上的 raster figure，运行本地 OCR，使用同一个上游 translator 翻译识别出的标签，并且只在受限的 OCR 区域内重绘。不安全或失败的图片编辑会保留原图并产生 warning。

## What it does / 功能

- Keeps the original PDF untouched and never deletes or overwrites an existing output. / 原始 PDF 永不修改、删除或覆盖既有输出。
- Delegates body text, captions, tables, formulas, vector figures, and PDF writing to PDFMathTranslate. / 正文、caption、table、formula、vector figure 和 PDF 写入交给 PDFMathTranslate。
- Translates text inside safe raster figures with RapidOCR and Pillow. / 使用 RapidOCR 和 Pillow 翻译安全 raster figure 内的文字。
- Preserves scientific tokens such as units, gene-style names, panel identifiers, and formula-like text during translation. / 翻译时保护单位、基因样式名称、panel identifier 和公式样式文本等 scientific token。
- Isolates figure failures: one failed or unsafe figure does not fail the whole paper. / 隔离单图失败：一张图失败或不安全不会导致整篇论文失败。
- Supports exactly three output modes: `mono`, `dual`, and `mono+dual`. / 严格支持三种输出模式：`mono`、`dual`、`mono+dual`。
- Supports exactly three raster-figure review modes: `multimodal`, `human`, and `none`. / 严格支持三种 raster figure 检查模式：`multimodal`、`human`、`none`。
- Returns a small JSON result on stdout and cleans temporary review sessions after completion, cancellation, or failure. / 在 stdout 返回小型 JSON，并在完成、取消或失败后清理临时 review session。

The provider is deliberately not hard-coded. Arguments after `--` are forwarded to PDFMathTranslate in their original order, so the provider and credentials remain under the user's existing PDFMathTranslate configuration.

provider 不被硬编码。`--` 后的参数按原顺序透传给 PDFMathTranslate，因此 provider 和凭据继续由用户现有的 PDFMathTranslate 配置管理。

## Scope and limitations / 范围与限制

This skill is designed for born-digital, text-based scientific PDFs. It does not add scanned-document preprocessing or full-document OCR. Vector content remains owned by PDFMathTranslate/BabelDOC; this skill only considers raster image objects that pass its semantic and safety filters.

本 Skill 面向 born-digital、可提取文本的科研 PDF。不增加扫描件预处理或全文 OCR。Vector 内容仍由 PDFMathTranslate/BabelDOC 负责；本 Skill 只处理通过语义和安全过滤的 raster image object。

The skill does not perform CJK-ratio gates, file-size gates, page-count gates, full-page pixel diffs, or other heuristic checks that can report false failures. It does not create persistent jobs, caches, manifests, QA PDFs, reports, databases, or review HTML. Temporary review material is kept under the operating system temporary directory and is removed when the workflow ends.

本 Skill 不执行 CJK 比例、文件大小、页数、全页 pixel diff 或其他容易造成假报错的 heuristic gate。不创建持久 job、cache、manifest、QA PDF、report、database 或 review HTML。临时 review 素材只存放在操作系统临时目录，并在工作流结束时删除。

Translated PDFs are reading aids. Cite the original publication, not a translated artifact.

翻译 PDF 仅供阅读参考；引用时必须引用原始出版物，不要引用翻译产物。

## Requirements / 依赖要求

The validated baseline is:

已验证的基线版本如下：

| Component / 组件 | Version / 版本 |
| --- | --- |
| Python | 3.10 or newer / 3.10 或更高 |
| pdf2zh-next | 2.9.0 |
| BabelDOC | 0.6.2 |
| PyMuPDF | 1.25.2 |
| rapidocr-onnxruntime | 1.4.4 |
| Pillow | 11.3.0 |

The host also needs a CJK font. The current Windows implementation uses Microsoft YaHei (`msyh.ttc`) from the standard Windows fonts directory; environments without that font should adapt the font constant before use. The skill does not install dependencies or fonts.

宿主环境还需要 CJK 字体。当前 Windows 实现使用标准 Windows 字体目录中的 Microsoft YaHei（`msyh.ttc`）；没有该字体的环境应在使用前调整 font constant。本 Skill 不安装依赖或字体。

Install the validated Python dependencies in the environment that will run the skill:

在运行本 Skill 的 Python 环境中安装已验证的依赖：

```powershell
python -m pip install `
  "pdf2zh-next==2.9.0" `
  "BabelDOC==0.6.2" `
  "PyMuPDF==1.25.2" `
  "rapidocr-onnxruntime==1.4.4" `
  "Pillow==11.3.0"
```

The PowerShell launcher expects `python` and the PDFMathTranslate `pdf2zh` executable to be available on `PATH`.

PowerShell launcher 要求 `python` 和 PDFMathTranslate 的 `pdf2zh` executable 位于 `PATH` 中。

## Install the skill / 安装 Skill

Copy this repository directory into the skill directory used by your compatible Agent host, keeping `SKILL.md` beside `scripts/`. For a Codex-compatible installation the resulting layout is:

将本仓库目录复制到兼容 Agent 宿主使用的 Skill 目录，并保持 `SKILL.md` 与 `scripts/` 同级。Codex-compatible 安装后的布局如下：

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

不要把用户 PDF、provider key、临时 review session 或私有测试 fixture 复制到仓库中。

## Usage / 使用方式

Before every run, the Agent must confirm two user choices. If one choice is already known, ask only for the other; if both are missing, ask both in one message. No conversion starts until the two choices are known.

每次运行前，Agent 必须确认两个用户选项。如果已有一个选项，只询问另一个；如果两个都缺失，在一条消息中一次询问。两个选项确定前不开始转换。

### 1. Output mode / 输出模式

| Mode / 模式 | Delivered output / 交付输出 |
| --- | --- |
| `mono` | Chinese-only PDF / 纯中文 PDF |
| `dual` | Chinese-English comparison PDF / 中英对照 PDF |
| `mono+dual` | Both PDFs / 两种 PDF |

Only the selected output(s) are handed to the user. Existing files are never overwritten; a unique suffix is used when a destination name already exists.

只向用户交付其选择的输出。既有文件永不覆盖；目标名称已存在时使用唯一后缀。

### 2. Raster-figure review mode / Raster figure 检查模式

| Mode / 模式 | Behavior / 行为 |
| --- | --- |
| `multimodal` | The Agent inspects generated figure previews and accepts or rejects affected figures. / Agent 检查生成的 figure preview，并接受或拒绝受影响的图片。 |
| `human` | The workflow pauses with previews and waits for the user's accept/reject decision. / 工作流展示 preview 后暂停，等待用户 accept/reject。 |
| `none` | No figure preview review is performed. / 不生成或检查 figure preview。 |

If no raster figure is safely modified, review is automatically `not_applicable` and no session is created.

如果没有 raster figure 被安全修改，review 自动记为 `not_applicable`，不会暂停，也不会创建 session。

### Start a translation / 开始翻译

The launcher forwards provider options after `--`; replace the placeholder with arguments already supported by your PDFMathTranslate installation. Do not add a provider-specific branch to this skill.

launcher 会透传 `--` 后的 provider 选项；请替换为当前 PDFMathTranslate 安装已支持的参数。不要为某个 provider 增加专用分支。

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\pdf2zh-zh.ps1" `
  start --input "<input.pdf>" --output-mode mono --review-mode human `
  -- <the same provider/configuration arguments accepted by PDFMathTranslate>
```

The command prints one JSON object. Typical fields include `status`, `outputs`, `session_dir`, `previews`, `translated_figures`, `retained_figures`, `warnings`, and `review_status`.

命令打印一个 JSON 对象。常见字段包括 `status`、`outputs`、`session_dir`、`previews`、`translated_figures`、`retained_figures`、`warnings` 和 `review_status`。

### Continue a reviewed translation / 继续已检查的翻译

For `human` or `multimodal`, the start response contains the temporary session directory and figure IDs. Continue only after every preview has a decision:

对于 `human` 或 `multimodal`，start 响应会返回临时 session 目录和 figure ID。所有 preview 都完成决策后再 continue：

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\pdf2zh-zh.ps1" `
  continue --session "<session-dir>" `
  --accept "p2-xref17,p5-xref42" `
  --reject "p7-xref61" `
  -- <the same provider/configuration arguments accepted by PDFMathTranslate>
```

The `continue` command must receive the same provider/configuration arguments as `start`; temporary sessions never store credentials or provider settings.

`continue` 必须接收与 `start` 相同的 provider/configuration 参数；临时 session 不保存凭据或 provider 设置。

## Failure handling / 失败处理

- A missing or invalid input fails before conversion and leaves the source untouched. / 输入缺失或无效时在转换前失败，原文件保持不变。
- A provider error, OCR failure, token mismatch, unsafe background, soft mask, reused image, overflow, or review rejection retains the affected raster figure and reports a warning. / provider 错误、OCR 失败、token mismatch、不安全背景、soft mask、复用图片、文字溢出或 review 拒绝都会保留受影响 raster figure，并报告 warning。
- A failure in one raster figure is isolated from other figures and from the rest of the paper. / 单张 raster figure 失败与其他图片及论文其余部分隔离。
- If the validated pdf2zh-next/BabelDOC versions are unavailable, or RapidOCR/DocLayout cannot be loaded, the pipeline falls back to ordinary `pdf2zh` translation and warns that raster figures were not processed. / 如果 pdf2zh-next/BabelDOC 版本不匹配，或 RapidOCR/DocLayout 无法加载，流程回退到普通 `pdf2zh` 翻译，并 warning raster figure 未处理。
- If PDFMathTranslate itself fails or a selected output is missing, the whole run is reported as failed; no incomplete output is claimed as delivered. / 如果 PDFMathTranslate 整体失败或所选输出缺失，整次运行报告为 failed，不声称交付不完整输出。

## Development checks / 开发检查

The public repository intentionally does not contain private PDFs or the internal P0 fixture set. Run the lightweight checks from the repository root:

公开仓库有意不包含私有 PDF 或内部 P0 fixture。请在仓库根目录运行轻量检查：

```powershell
python -m py_compile scripts/run_pipeline.py scripts/figure_pipeline.py
python scripts/run_pipeline.py --help
```

The GitHub Actions workflow performs the same syntax/help checks and verifies the public file layout without contacting a translation provider or downloading model assets.

GitHub Actions workflow 执行相同的语法/help 检查，并验证公开文件布局，不连接 translation provider，也不下载模型资产。

## Repository layout / 仓库布局

```text
SKILL.md                         Skill contract and Agent-facing workflow / Skill 契约与 Agent 工作流
scripts/                         PowerShell launcher and Python pipeline / PowerShell launcher 与 Python pipeline
README.md                        Bilingual user and contributor documentation / 中英双语用户与贡献者文档
LICENSE                          GNU AGPL v3 or later / GNU AGPL v3 或更高版本
NOTICE                           Project copyright and dependency boundary / 项目版权与依赖边界
THIRD_PARTY_NOTICES.md           Dependency and attribution notes / 依赖与致谢说明
CONTRIBUTING.md                  Contribution and testing rules / 贡献与测试规则
SECURITY.md                      Security reporting policy / 安全报告政策
CODE_OF_CONDUCT.md               Community expectations / 社区行为准则
.github/                         CI and issue/PR templates / CI 与 issue/PR 模板
```

## Acknowledgments / 致谢

This skill stands on the work of the following open-source projects:

本 Skill 基于以下开源项目的工作：

- [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) (AGPL-3.0): upstream scientific PDF translation interface, provider configuration, mono/dual output, and high-level orchestration. / 上游科研 PDF 翻译接口、provider 配置、mono/dual 输出和高级编排。
- [BabelDOC](https://github.com/funstory-ai/BabelDOC) (AGPL-3.0): document translation and layout-preserving PDF generation used by PDFMathTranslate. / PDFMathTranslate 使用的文档翻译与保留布局的 PDF 生成后端。
- [RapidOCR](https://github.com/RapidAI/RapidOCR) (Apache-2.0): local OCR used to recognize text in raster figures. / 用于识别 raster figure 文字的本地 OCR。
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0): PDF inspection, image-object discovery, placement mapping, and bounded raster replacement. / 用于 PDF 检查、图片对象发现、位置映射和受限 raster 替换。
- [Pillow](https://github.com/python-pillow/Pillow) (MIT-CMU): local image decoding, masking, font fitting, and redraw operations. / 用于本地图片解码、mask、字体适配和重绘。

The repository calls these projects through their public or verified APIs and does not copy large portions of their source code. Their licenses and notices remain their respective authors' responsibility; see `THIRD_PARTY_NOTICES.md` for the dependency boundary.

本仓库通过这些项目的公开或已验证 API 调用它们，不复制上游大段源码。各项目的许可证和 notices 仍由其各自作者负责；依赖边界见 `THIRD_PARTY_NOTICES.md`。

## License / 许可证

The skill code and documentation in this repository are released under the [GNU Affero General Public License v3.0 or later](LICENSE). Runtime dependencies are separate works and remain under their own licenses.

本仓库中的 Skill 代码和文档以 [GNU Affero General Public License v3.0 or later](LICENSE) 发布。运行时依赖属于独立作品，继续适用各自许可证。
