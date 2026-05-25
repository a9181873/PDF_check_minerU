# VS Code Handoff - 2026-05-25

明天從 VS Code 繼續時，請先看這份。

## Branch

- Repo: `a9181873/PDF_check_minerU`
- Branch: `codex/pdf-diff-regression-audit`
- Latest commit at handoff: `8651247 docs: record 商品DM fallback probe`
- PR entry: <https://github.com/a9181873/PDF_check_minerU/pull/new/codex/pdf-diff-regression-audit>

## What Was Found

核心退化不是單一 OCR 壞掉，而是 2026-05-21 `c60ae99` 之後：

1. `merge_diff_results()` 開始丟棄所有 `DiffType.IMAGE_DIFF`。
2. `_drop_non_numeric_modifications()` 又做最終非數字過濾。
3. image-only PDF 在 `ENABLE_IMAGE_TEXT_RECALL=false` 時，pixel path 抓到的真差異常常只剩 `IMAGE_DIFF`。
4. 結果是系統其實有看到差異，但最後自己刪掉，造成使用者看到 0 筆或原本能辨識的地方消失。

## What Was Changed

已推送三個後續 commit：

- `9ec5544 fix: retain image PDF visual fallback`
  - image-only / mixed image PDF 保留 `IMAGE_DIFF` fallback。
  - 一般 text PDF 仍維持原本降噪。

- `9f6ca22 feat: add alignment recall strategy`
  - 新增 `IMAGE_TEXT_RECALL_STRATEGY=alignment|heuristic`。
  - recall ON 時可走 `align_service.align_paragraphs()` 的文字序列對齊，不必繼續只調 bbox-IoU heuristic。
  - recall 本身仍預設 OFF。

- `8651247 docs: record 商品DM fallback probe`
  - 記錄 `/商品DM` 5 組 PDF 在 recall OFF 下的 fallback 快速驗證結果。

## Important Files

- `docs/pdf_diff_regression_audit_2026-05-25.md`
  - 主分析、時間線、修法、商品 DM 快速驗證。
- `docs/recall-regression-runbook.md`
  - 真實 MinerU 容器 OCR A/B 驗證方式。
- `backend/services/diff_service.py`
  - P0 fallback 修正與 recall strategy 接線。
- `backend/services/align_service.py`
  - alignment recall 原型。
- `backend/tests/test_diff.py`
- `backend/tests/test_image_text_recall.py`
- `backend/tests/test_align_service.py`

## Verification Already Run

```bash
backend/.venv/bin/python -m pytest backend/tests
```

Result: `62 passed`.

Quick probe on local `/Users/jy/pdfcheck_minerU/商品DM`, recall OFF:

| Sample | Result |
|---|---|
| 慈愛微型 | total 4, `image_diff=3`, `number_modified=1` |
| 新扶愛 | total 48, `image_diff=47`, `number_modified=1` |
| 美保發 | total 3, `image_diff=2`, `number_modified=1` |
| 美利保 | total 4, `image_diff=3`, `number_modified=1` |
| 臻美利 | total 7, `image_diff=6`, `number_modified=1` |

Meaning: recall OFF no longer deletes the image-only PDF visual evidence.

## Local Data Caveat

`商品DM/` PDF samples were not committed. They remain local-only. If continuing on another computer, copy the same `商品DM/` folder into the repo root before rerunning sample probes.

## Suggested Next Step

Do not add more recall heuristics first.

Next useful step is a real MinerU OCR A/B:

1. `ENABLE_IMAGE_TEXT_RECALL=true`
2. Run once with `IMAGE_TEXT_RECALL_STRATEGY=alignment`
3. Run once with `IMAGE_TEXT_RECALL_STRATEGY=heuristic`
4. Compare:
   - total diffs
   - diff types
   - missing required changes
   - false positives from OCR re-segmentation
   - OCR garbage such as `[PAYV`

Use `docs/recall-regression-runbook.md` as the procedure.

## Prompt For Tomorrow

If opening a fresh Codex chat in VS Code, paste:

```text
請從 docs/vscode_handoff_2026-05-25.md 繼續 PDF_check_minerU 的回歸分析。重點：不要再往舊 recall heuristic 加規則，先用 商品DM 做 MinerU OCR A/B，比較 IMAGE_TEXT_RECALL_STRATEGY=alignment 與 heuristic，並把發現記錄後推到 GitHub branch codex/pdf-diff-regression-audit。
```
