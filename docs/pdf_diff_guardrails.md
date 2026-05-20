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

## MinerU + Docling Parsing Rule

The original MinerU version used parallel table parsing. Keep that behavior.

- `ENABLE_DOCLING_PARALLEL=true`
- `MINERU_PREFERRED_WAIT_SECONDS=0`
- `backend/config.py` defaults should match this.
- `docker-compose.yml` should explicitly set these env vars for `backend-minerU`.

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
