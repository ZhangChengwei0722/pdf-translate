---
name: pdf-translate
description: "Use this skill whenever the user asks to translate a paper PDF into Chinese (e.g. 帮我翻译这篇论文, with a paper PDF attached). Translates the paper with PDFMathTranslate (pdf2zh-next) preserving layout, formulas, tables and vector figures, and additionally translates text inside safe raster figures using local OCR. Before translating, exactly two user choices must be confirmed: output mode (mono/dual/mono+dual) and figure review mode (multimodal/human/none). The translation provider follows the user's PDFMathTranslate configuration; this skill never forces a provider."
---

# PDF 论文翻译（PDFMathTranslate + raster figure 图片文字翻译）

## 概述

把英文论文 PDF 翻译成中文，保留原始排版。两个组成部分：

- **正文与 PDF 输出**：PDFMathTranslate（pdf2zh-next + BabelDOC）负责正文、caption、table、formula、vector figure、mono/dual 生成和 PDF 写入，provider 沿用其自身配置。
- **raster figure 图片文字**：本 Skill 只安全修改 raster figure 中的文字——本地 RapidOCR 识别、用同一 PDFMathTranslate translator 翻译、Pillow 在 OCR mask 邻域内局部重绘。不安全或失败时保留原图并继续，绝不生成式重绘。

原始 PDF 永不修改、覆盖或删除。只交付用户选择的翻译 PDF。

**依赖与兼容**：Python 3.10+、pdf2zh-next==2.9.0、BabelDOC==0.6.2、PyMuPDF、rapidocr-onnxruntime、Pillow，以及一个 CJK 字体（msyh/simhei/simsun 至少其一）。翻译 provider 和凭据来自用户现有的 PDFMathTranslate 配置，本 Skill 从不读写或强制任何 provider 凭据，也不执行 pip 安装。

## 运行前：两项选择（硬规则）

每次运行前必须确认两项选择。用户已明确给出的不得重复询问；缺少一项只问一项；两项都缺时在同一条消息中一次问完。两项未确定前不开始任何转换。

1. **输出**：
   - `mono` → 只交付纯中文 PDF（映射为 `--no-dual`）
   - `dual` → 只交付中英对照 PDF（映射为 `--no-mono`）
   - `mono+dual` → 同时交付两种
   - 自然语言映射："只要中文版"→mono；"只要双语版/中英对照版"→dual；"两个版本都要"→mono+dual。
2. **图片翻译检查**：
   - `multimodal`：多模态 Agent 在运行 PDFMathTranslate 前检查成功修改的 figure crop，发现明显问题时回退受影响 figure，不请求用户确认。
   - `human`：在聊天中展示临时预览，暂停并等待用户 accept/reject。
   - `none`：不生成预览、不视觉判断，直接继续。
   - 没有 raster figure 被成功修改时自动记为 `not_applicable`，不暂停、不生成预览。

provider 不是第三个运行前问题。它沿用用户请求中已明确的 PDFMathTranslate provider/config，或 PDFMathTranslate 现有 config 与环境设置，或其默认 provider。

## 调用方式

命令由 Agent 调用，用户不手工输入。

### start（首次运行）

```powershell
powershell -ExecutionPolicy Bypass -File "<skill目录>\scripts\pdf2zh-zh.ps1" `
  start --input "paper.pdf" --output-mode mono --review-mode human `
  -- <原有 PDFMathTranslate provider/config 参数>
```

`--` 后的参数按原顺序透传给 PDFMathTranslate（如 `--openai-compatible ...` 或该机器现有的 provider 参数）。没有 provider 参数时沿用 PDFMathTranslate 的 config、环境变量或默认行为。

### continue（human/multimodal 检查）

```powershell
powershell -ExecutionPolicy Bypass -File "<skill目录>\scripts\pdf2zh-zh.ps1" `
  continue --session "<session目录>" `
  --accept "p2-xref17,p5-xref42" --reject "p7-xref61" `
  -- <与 start 相同的 PDFMathTranslate provider/config 参数>
```

session 目录由 start 的 stdout JSON 给出。continue 必须重新传入与 start 相同的 `--` 后参数（session 不保存 provider 配置或凭据）。

## 运行流程

1. 确认两项选择（见上）。
2. 调用 start：脚本检查版本（pdf2zh-next==2.9.0、BabelDOC==0.6.2）、创建工作副本（保留原 stem）、发现并处理 raster figure、按 review mode 分流。
3. stdout 返回小型 JSON：`status`（completed / review_required / failed / choices_required）、`outputs`、`session_dir`、`previews`、`translated_figures`、`retained_figures`、`warnings`、`review_status`。
4. `review_required` 时：multimodal 由 Agent 查看 previews 并决策；human 把 previews 展示给用户并等待回复，然后按用户决定调用 continue。
5. `completed` 时：在聊天中汇报结果（见下）。

版本不匹配、RapidOCR 缺失或 DocLayout 内部 API 不可用时，脚本自动退回普通 `pdf2zh` 调用：正文翻译照常，raster figure 图片文字不处理，并在 warning 中说明原因。

## 输出约定

- 输出 PDF 命名沿用 PDFMathTranslate 规则（`<原名>.<lang>.mono.pdf` / `<原名>.<lang>.dual.pdf`），交付到原 PDF 所在目录。
- 同名文件已存在时生成唯一名称，绝不覆盖既有文件。
- 原始 PDF 不动、不删除、不覆盖。
- 翻译产物仅供阅读参考，不能作为引用来源（引用一律以原文为准）。

## 聊天结果契约

最终回复必须列出所有实际交付的 PDF，并汇报 raster figure 结果。不得暗示所有图片文字都已翻译。示例：

```text
翻译完成。

输出：
- paper.zh.mono.pdf
- paper.zh.dual.pdf

图片文字：成功翻译 5 张；保留原图 2 张。
Warning：第 6 页背景复杂；第 9 页译文无法安全放入原区域。
图片检查：多模态 Agent 已检查。
```

没有 warning 时省略 warning 行；没有修改 raster figure 时说明"未修改 raster figure 图片文字"。vector figure 不写入 raster 的 retained/skipped warning。

## 失败与边界

- 单张 raster figure 不安全/OCR 失败/翻译失败/review 拒绝：保留原图、记录 warning、继续整篇翻译。
- PDFMathTranslate 整体失败或所选输出缺失：整次失败，报告上游错误，不声称已有翻译产物。
- 不做扫描件预检、不做全文 OCR、不做 CJK 比例/文件大小/页数一致性验证、不做全页像素对比。
- 不产生 job.json、report、manifest、QA PDF、review HTML 或持久缓存；review session 只在 `%TEMP%\pdf-translator\` 下临时存在，continue/取消/失败后自动删除。
- 不安装任何依赖；依赖缺失时按上文 fallback 规则处理。
