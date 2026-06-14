# PDF Diff Guardrails

This file records decisions that must be preserved in future fixes. Read it before changing PDF parsing, OCR, visual diff grouping, or OCI deployment settings.

## 2026-05-20 Image PDF Footer/OCR Fix

Commit: `f23c2ba fix: protect image PDF footer diffs`

### Case That Must Keep Passing

Files:

- `台灣人壽新保安心住院醫療終身健康保險_商品DM(公版)-FINAL(製作人-陳柏婷)-1120209.pdf`
- `台灣人壽新保安心住院醫療終身健康保險_商品DM_20240701適用.pdf`

Observed structure:

- Both PDFs are image-only.
- PyMuPDF native text extraction returns 0 words/chars.
- The correct solution cannot rely on native PDF text.

Required result:

- Page 2 footer-right `Control No.` / version change must be detected.
- Expected extracted values:
  - Old: `Version: 2023.02; Control No: 2301-2501-OP2-0043`
  - New: `Version: 2024.07; Control No: OP-2407-2607-0503`
- OCR garbage such as `[PAYV` / private-use mojibake must not appear as ordinary `TEXT_MODIFIED` UI text.

Measured facts from the failing case:

- Page 2 footer-right has `2162` changed pixels.
- The `Control No.` area largest connected component has `1086 px`.
- This is a real visual change, not an absence of difference.

### Implementation Rules

Keep these behaviors unless there is a stronger regression test proving a replacement is better:

- Use a broad visual scan first, then refine candidates.
- Keep the broad connected-component dilation behavior in `diff_pixels()` at `iterations=4`. Reducing it to `1` caused the footer/control-number miss.
- Keep a protected header/footer OCR pass for high-value fields before general local filtering can suppress them.
- Extract priority OCR patterns such as:
  - `Control No`
  - version dates like `2024.07`
  - document/control-number strings
- Do not expose local OCR output as normal text unless it is reliable or matches a priority pattern.
- Do not OCR large complex page/table regions just to fill `old_value` / `new_value`; show them as visual/image diffs unless reliable text exists.
- When merging nearby diffs, priority footer/header values must win over noisy local OCR values.
- Reduced nearby text merge radius can be useful, but it must not suppress protected footer/header changes.

### Validation Expectations

Before pushing/deploying changes in this area, run:

```powershell
python -B -m py_compile backend\config.py backend\services\parser_service.py backend\services\diff_service.py backend\tests\test_diff.py
python -B -m pytest backend\tests -p no:cacheprovider --basetemp .pytest-tmp-verify
git diff --check
```

Also run the real-PDF Docker regression when the two Taiwan Life PDFs are available locally. Expected summary from the 2026-05-20 fix:

```text
raw: 33 merged: 20
text_count: 1 image_count: 19
footer_count: 1
footer: number_modified ... 'Version: 2023.02; Control No: 2301-2501-OP2-0043' -> 'Version: 2024.07; Control No: OP-2407-2607-0503'
garbage_text_count: 0
```

## 2026-05-21 Native Text + OCR Reliability Update

This update fixed two regressions that looked opposite but share one rule: decide from the PDF structure first, then use text and location together.

### Cases That Must Keep Passing

1. Image-only Taiwan Life EDMs:
   - `baoxinanxin`: must not expose OCR fragments such as `[PAYV` as text.
   - `fengshouai`: page 6 footer-right must detect:
     - Old: `Version: 2026.02; Control No: OP-2602-0081`
     - New: `Version: 2026.05; Control No: 2605-OP-0029`
2. Native-text PDF:
   - `callcard_back`: must be treated as `text_pdf`, not image-only.
   - Text diffs such as removed `海外` and changed benefit wording must remain visible.
3. Product DM image-only PDFs:
   - Footer `Control No.` / version changes must survive deduplication.
   - Table/currency OCR like `975.18` must not be mistaken for `Version`.

### Implementation Rules

- PyMuPDF `rawdict` spans can omit `span["text"]` while still containing `span["chars"][].c`; parser code must join chars as a fallback before declaring a PDF image-only.
- `Control No.` extraction must support short formats such as `OP-2602-0081` and mixed formats such as `2605-OP-0029`.
- Bracketed version dates are high priority; loose date-like values should only be accepted with a detected control number.
- Local OCR for normal image-only diff regions is allowed only when the pair has a strong signal:
  - priority footer/header field, or
  - a long CJK run, or
  - dense numeric table text.
- Reject fragmented short-line OCR and obvious uppercase bracket noise before it reaches `old_value` / `new_value`.
- Large layout/table movements remain visual diffs unless a protected priority field or reliable local text is present.
- For native text PDFs, same text with the same bbox is rendering noise; same text with a clearly moved bbox is a position/content-layout change and must not be suppressed.
- `control/version` priority items should not be proximity-merged with nearby ordinary text because that can hide the neighboring text difference.
- Header/footer priority OCR should run whenever the protected band has any visual change. Do not block it with high pixel/component thresholds; OCR extraction itself decides whether a priority value exists.

### Diagnostic Workflow

Do not diagnose these cases with bare host Python. Host Python may lack `fitz`, `tesseract`, `pdftotext`, or `pdftoppm`, while OCI runs inside the backend image.

Use the container-backed diagnostic script so local checks match OCI dependencies:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\diagnose-pdf-samples.ps1
```

Expected 2026-05-21 sample summaries:

```text
baoxinanxin: image_pdf; only footer text should remain; no [PAYV] ordinary text
fengshouai: image_pdf; includes page 6 text_modified plus footer number_modified
callcard_back: text_pdf; native text diffs visible
auto:美保發: image_pdf; footer number_modified visible
auto:臻美利: image_pdf; footer number_modified visible; no false Version: 975.18
```

Reviewer conclusions from this pass:

- PDF-content review: current split is correct; image-only EDMs should be handled by pixel/OCR guardrails, while native text PDFs should keep text-layer diffs.
- Algorithm review: keep tests for same-text movement, small footer priority OCR, and priority-vs-nearby-text merge behavior.
- Environment/model review: do not use bare host Python as the truth source; use the backend container. PaddleOCR may remain as a disabled metadata-only experiment, but it must not change final diff items until fixed samples prove better recall without garbage text.

### Model Guidance

MinerU and Docling are already the intended parallel parsers. Do not add another local model just to mask OCR noise. The optional PaddleOCR path is allowed only as an off-by-default A/B metadata experiment. Promote a new local OCR/layout model to final diff generation only after a fixed sample suite proves it improves text recall without reintroducing garbage text or hiding protected footer/header changes.

## MinerU + Docling Parsing Rule

The original MinerU version used parallel table parsing. Keep that behavior.

- `ENABLE_DOCLING_PARALLEL=true`
- `MINERU_PREFERRED_WAIT_SECONDS=0`
- `backend/config.py` defaults should match this.
- `docker-compose.yml` should explicitly set these env vars for `backend-minerU`.

## 2026-06-14 Compact Image Number Diff Rule

### Case That Must Keep Passing

Files:

- `台灣人壽鳳守愛防癌定期健康保險_商品DM_20260213適用.pdf`
- `台灣人壽鳳守愛防癌定期健康保險_商品DM_20260506適用.pdf`

Required result:

- Page 2 image/graphic number change must be surfaced as a formal `NUMBER_MODIFIED` item:
  - Old: `24`
  - New: `28`
  - Context: `Page 2 圖片數字變更`
- Page 6 footer-right priority field must still be detected:
  - Old: `Version: 2026.02; Control No: OP-2602-0081`
  - New: `Version: 2026.05; Control No: 2605-OP-0029`
- Pure visual/color/image diffs without reliable text or numbers should remain suppressed from the formal review list.
- Regression samples should include `慈愛微型`, `新扶愛`, `美保發`, `美利保`, and `臻美利` under `商品DM/` when available locally.
- `新扶愛` must not surface phone/spacing/punctuation-only OCR drift as `NUMBER_MODIFIED` just because unchanged numbers such as `0800`, `40`, `310`, or `15` appear in the cropped text.
- `慈愛微型` must not surface one-digit list/sequence noise such as `2 -> 3`, `3 -> 5`, or `9 -> 1` as formal differences.
- `美利保` amount OCR should prefer high-zoom rereads when numeric text contains likely letter substitutions, e.g. avoid presenting `447,6i12` when `447,612` can be read from the same crop.

### Implementation Rules

- Do not restore full-page OCR as the main image-only strategy. It is slower and reintroduces noisy text false positives.
- Keep the pixel-first strategy: locate changed regions first, then OCR only relevant local regions.
- Tiny graphic numerals may OCR with unit artifacts, e.g. `24年` as `244` or `28年` as `281` / `28%`. Normalize these compact numeric OCR pairs before presenting them.
- Compact numeric fallback should reject isolated one-digit pairs unless a stronger priority pattern exists; single digits are too often list markers or OCR drift.
- For image-only PDFs, OCR reliability gating applies to both `TEXT_MODIFIED` and `NUMBER_MODIFIED`; unchanged numbers inside noisy text must not bypass the gate.
- Only label a diff as `圖片數字變更` when the surfaced values are compact numeric OCR values. Longer text blocks with changed numbers should use normal content context.
- If numeric OCR contains likely substitutions such as `i/I/O` inside numeric runs, one extra high-zoom local reread is allowed for the same crop. Do not expand that into full-page OCR.
- Skip the compact-number fallback in header/footer bands because protected `control/version` OCR owns those regions.
- Keep `PaddleOCR` off by default and metadata-only until fixed samples prove better recall without extra noise.

### Performance Notes

- The compact-number fallback adds one extra high-zoom Tesseract pass only for small changed image regions.
- Numeric OCR cleanup adds one extra high-zoom pass only when the first local OCR result has obvious numeric letter substitutions.
- Runtime impact should scale with changed-region count, not page count.
- Expected behavior for the `fengshouai` sample is still a small diff set: image PDF summary with `pixel=6`, two formal `number_modified` items, and pure visual candidates suppressed.

Historical source:

- `db3334a feat: 效能優化 (並行解析...)` had MinerU and Docling submitted together.
- `fc21cab` changed this to opt-in fallback. That was later corrected because the user remembered the original parallel behavior and wanted it preserved.

Do not describe Docling as only a fallback in current docs. Current intent:

- MinerU provides strong Chinese/table content extraction.
- Docling provides useful cell-level bbox data.
- The two are complementary and should run in parallel for table parsing.

## OCI Deployment Guardrails

Target only:

- Repo: `/home/ubuntu/pdf-check-minerU`
- Compose service: `backend-minerU`
- Container: `pdf-check-minerU`

Do not deploy to or restart unrelated services such as `pdf-check-backend`.

OCI keeps local-only `docker-compose.yml` differences:

- `ports: '8000'` instead of fixed `8001:8000`
- `networks.internal.external: true` instead of local `driver: bridge`

Preserve those remote compose differences during deployment. Do not overwrite them with the local compose file. Safe deployment pattern:

1. Check remote status and diff.
2. Stash only the OCI compose override if needed.
3. Fetch and fast-forward to `origin/main`.
4. Reapply the OCI compose override.
5. Rebuild/recreate only `backend-minerU`.
6. Confirm `/health` and env vars.

2026-05-20 deployment checks:

- `pdf-check-minerU` recreated from new `pdf-check-backend:latest`.
- `/health` returned `{"status":"ok"}`.
- Container env:
  - `ENABLE_DOCLING_PARALLEL=true`
  - `MINERU_PREFERRED_WAIT_SECONDS=0`
