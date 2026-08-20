# PDF 翻译 Skill

[English version / 英文版](README.md)

`pdf-translate` 是一个可移植的 Skill，用于将科研论文 PDF 翻译成中文，同时保留原始文档和上游 PDFMathTranslate 工作流。

本 Skill 在 PDFMathTranslate（pdf2zh-next + BabelDOC）外增加了保守的 raster figure 处理流程：识别语义上的 raster figure，运行本地 OCR，使用同一个上游 translator 翻译识别出的标签，并且只在受限的 OCR 区域内重绘。不安全或失败的图片编辑会保留原图并产生 warning。

## 功能

- 原始 PDF 永不修改、删除或覆盖既有输出。
- 正文、caption、table、formula、vector figure 和 PDF 写入交给 PDFMathTranslate。
- 使用 RapidOCR 和 Pillow 翻译安全 raster figure 内的文字。
- 翻译时保护单位、基因样式名称、panel identifier 和公式样式文本等 scientific token。
- 隔离单图失败：一张图失败或不安全不会导致整篇论文失败。
- 严格支持三种输出模式：`mono`、`dual`、`mono+dual`。
- 严格支持三种 raster figure 检查模式：`multimodal`、`human`、`none`。
- 在 stdout 返回小型 JSON，并在完成、取消或失败后清理临时 review session。

provider 不被硬编码。`--` 后的参数按原顺序透传给 PDFMathTranslate，因此 provider 和凭据继续由用户现有的 PDFMathTranslate 配置管理。

## 范围与限制

本 Skill 面向 born-digital、可提取文本的科研 PDF。不增加扫描件预处理或全文 OCR。Vector 内容仍由 PDFMathTranslate/BabelDOC 负责；本 Skill 只处理通过语义和安全过滤的 raster image object。

本 Skill 不执行 CJK 比例、文件大小、页数、全页 pixel diff 或其他容易造成假报错的 heuristic gate。不创建持久 job、cache、manifest、QA PDF、report、database 或 review HTML。临时 review 素材只存放在操作系统临时目录，并在工作流结束时删除。

翻译 PDF 仅供阅读参考；引用时必须引用原始出版物，不要引用翻译产物。

## 依赖要求

已验证的基线版本如下：

| 组件 | 版本 |
| --- | --- |
| Python | 3.10 或更高 |
| pdf2zh-next | 2.9.0 |
| BabelDOC | 0.6.2 |
| PyMuPDF | 1.25.2 |
| rapidocr-onnxruntime | 1.4.4 |
| Pillow | 11.3.0 |

宿主环境还需要 CJK 字体。当前 Windows 实现使用标准 Windows 字体目录中的 Microsoft YaHei（`msyh.ttc`）；没有该字体的环境应在使用前调整 font constant。本 Skill 不安装依赖或字体。

在运行本 Skill 的 Python 环境中安装已验证的依赖：

```powershell
python -m pip install `
  "pdf2zh-next==2.9.0" `
  "BabelDOC==0.6.2" `
  "PyMuPDF==1.25.2" `
  "rapidocr-onnxruntime==1.4.4" `
  "Pillow==11.3.0"
```

PowerShell launcher 要求 `python` 和 PDFMathTranslate 的 `pdf2zh` executable 位于 `PATH` 中。

## 安装 Skill

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

不要把用户 PDF、provider key、临时 review session 或私有测试 fixture 复制到仓库中。

## 使用方式

每次运行前，Agent 必须确认两个用户选项。如果已有一个选项，只询问另一个；如果两个都缺失，在一条消息中一次询问。两个选项确定前不开始转换。

### 1. 输出模式

| 模式 | 交付输出 |
| --- | --- |
| `mono` | 纯中文 PDF |
| `dual` | 中英对照 PDF |
| `mono+dual` | 两种 PDF |

只向用户交付其选择的输出。既有文件永不覆盖；目标名称已存在时使用唯一后缀。

### 2. Raster figure 检查模式

| 模式 | 行为 |
| --- | --- |
| `multimodal` | Agent 检查生成的 figure preview，并接受或拒绝受影响的图片。 |
| `human` | 工作流展示 preview 后暂停，等待用户 accept/reject。 |
| `none` | 不生成或检查 figure preview。 |

如果没有 raster figure 被安全修改，review 自动记为 `not_applicable`，不会暂停，也不会创建 session。

### 开始翻译

launcher 会透传 `--` 后的 provider 选项；请替换为当前 PDFMathTranslate 安装已支持的参数。不要为某个 provider 增加专用分支。

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\pdf2zh-zh.ps1" `
  start --input "<input.pdf>" --output-mode mono --review-mode human `
  -- <the same provider/configuration arguments accepted by PDFMathTranslate>
```

命令打印一个 JSON 对象。常见字段包括 `status`、`outputs`、`session_dir`、`previews`、`translated_figures`、`retained_figures`、`warnings` 和 `review_status`。

### 继续已检查的翻译

对于 `human` 或 `multimodal`，start 响应会返回临时 session 目录和 figure ID。所有 preview 都完成决策后再 continue：

```powershell
powershell -ExecutionPolicy Bypass -File "<skill-dir>\scripts\pdf2zh-zh.ps1" `
  continue --session "<session-dir>" `
  --accept "p2-xref17,p5-xref42" `
  --reject "p7-xref61" `
  -- <the same provider/configuration arguments accepted by PDFMathTranslate>
```

`continue` 必须接收与 `start` 相同的 provider/configuration 参数；临时 session 不保存凭据或 provider 设置。

## 失败处理

- 输入缺失或无效时在转换前失败，原文件保持不变。
- provider 错误、OCR 失败、token mismatch、不安全背景、soft mask、复用图片、文字溢出或 review 拒绝都会保留受影响 raster figure，并报告 warning。
- 单张 raster figure 失败与其他图片及论文其余部分隔离。
- 如果 pdf2zh-next/BabelDOC 版本不匹配，或 RapidOCR/DocLayout 无法加载，流程回退到普通 `pdf2zh` 翻译，并 warning raster figure 未处理。
- 如果 PDFMathTranslate 整体失败或所选输出缺失，整次运行报告为 failed，不声称交付不完整输出。

## 开发检查

公开仓库有意不包含私有 PDF 或内部 P0 fixture。请在仓库根目录运行轻量检查：

```powershell
python -m py_compile scripts/run_pipeline.py scripts/figure_pipeline.py
python scripts/run_pipeline.py --help
```

GitHub Actions workflow 执行相同的语法/help 检查，并验证公开文件布局，不连接 translation provider，也不下载模型资产。

## 仓库布局

```text
SKILL.md                         Skill 契约与 Agent 工作流
scripts/                         PowerShell launcher 与 Python pipeline
README.md                        英文版用户与贡献者文档
README.zh-CN.md                  中文版用户与贡献者文档
LICENSE                          GNU AGPL v3 或更高版本
NOTICE                           项目版权与依赖边界
THIRD_PARTY_NOTICES.md           依赖与致谢说明
CONTRIBUTING.md                  贡献与测试规则
SECURITY.md                      安全报告政策
CODE_OF_CONDUCT.md               社区行为准则
.github/                         CI 与 issue/PR 模板
```

## 致谢

本 Skill 基于以下开源项目的工作：

- [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next)（AGPL-3.0）：上游科研 PDF 翻译接口、provider 配置、mono/dual 输出和高级编排。
- [BabelDOC](https://github.com/funstory-ai/BabelDOC)（AGPL-3.0）：PDFMathTranslate 使用的文档翻译与保留布局的 PDF 生成后端。
- [RapidOCR](https://github.com/RapidAI/RapidOCR)（Apache-2.0）：用于识别 raster figure 文字的本地 OCR。
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF)（AGPL-3.0）：用于 PDF 检查、图片对象发现、位置映射和受限 raster 替换。
- [Pillow](https://github.com/python-pillow/Pillow)（MIT-CMU）：用于本地图片解码、mask、字体适配和重绘。

本仓库通过这些项目的公开或已验证 API 调用它们，不复制上游大段源码。各项目的许可证和 notices 仍由其各自作者负责；依赖边界见 `THIRD_PARTY_NOTICES.md`。

## 许可证

本仓库中的 Skill 代码和文档以 [GNU Affero General Public License v3.0 or later](LICENSE) 发布。运行时依赖属于独立作品，继续适用各自许可证。
