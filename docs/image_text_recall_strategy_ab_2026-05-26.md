# Image Text Recall Strategy A/B - EDM Regression

Date: 2026-05-26

## Context

This run continues from `docs/vscode_handoff_2026-05-25.md` on branch
`codex/pdf-diff-regression-audit`.

The goal was to avoid adding more rules to the older recall heuristic, then run
the real MinerU OCR A/B requested in the handoff:

- `IMAGE_TEXT_RECALL_STRATEGY=alignment`: `diff_aligned_paragraphs()` via
  `align_service.align_paragraphs()`
- `IMAGE_TEXT_RECALL_STRATEGY=heuristic`: older position / bbox-IoU path
  (`diff_positioned_paragraphs()`)

Recall remains default OFF; this is a regression audit of the recall-on path.

## Runtime

- EDM source: `C:\Users\JY\Downloads\DM`
- Container image: `pdf-check-backend:latest`
- MinerU endpoint: `http://mineru-api-minerU:18080`
- Docker network: `pdf_check_mineru_internal`
- Raw local output: `C:\tmp\edm_recall_ab_alignment.json`
- Script: `backend/scripts/compare_recall_strategies.py`

Command:

```powershell
docker run --rm --network pdf_check_mineru_internal `
  -e PYTHONDONTWRITEBYTECODE=1 `
  -e PYTHONIOENCODING=utf-8 `
  -e MINERU_API_URL=http://mineru-api-minerU:18080 `
  -v "C:\Users\JY\Desktop\PDF_check_minerU:/repo:ro" `
  -v "C:\Users\JY\Downloads\DM:/dm:ro" `
  -v "C:\tmp:/out" `
  -w /repo/backend `
  pdf-check-backend:latest `
  python scripts/compare_recall_strategies.py --dm-root /dm --output /out/edm_recall_ab_alignment.json
```

## Result Summary

| EDM pair | alignment | heuristic | Finding |
| --- | ---: | ---: | --- |
| 台灣人壽新保安心住院醫療終身健康保險 | 11 | 2 | Alignment finds the page-2 structural clause changes but over-fragments them into added/deleted pieces; heuristic is cleaner and reports the header update plus one added clause. |
| 台灣人壽鳳守愛防癌定期健康保險 | 0 | 0 | No strategy difference. |
| 平安Call卡DM_家庭版 | 0 | 0 | No strategy difference. |
| 慈愛微型 | 2 | 1 | Alignment adds one small `8注意事項` fragment; heuristic only reports the product-number/date OCR line. |
| 新扶愛 | 8 | 1 | Alignment recalls more title/phone/amount fragments but also emits duplicated add/delete fragments; heuristic emits one page-4 clause mispair. |
| 美保發 | 2 | 0 | Alignment reports one deleted disclosure line and one added customer-service line; heuristic reports nothing. Needs visual/human confirmation. |
| 美利保 | 0 | 0 | No strategy difference. |
| 美鑫傳家 | 7 | 7 | Both strategies catch the high-signal rate/value changes, but heuristic output is more readable; alignment splits several changes into short numeric fragments. |

## Interpretation

Alignment improves recall for non-IoU structural changes, but the current output
is not yet cleaner than heuristic. Its main failure mode is fragmentation:
headers, list moves, and long clause changes become multiple small added/deleted
or numeric snippets. That is visible in 新保安心, 新扶愛, and 美鑫傳家.

Heuristic remains more conservative and readable on this EDM set, but it still
has known blind spots: it misses 美保發's alignment-only candidates and produces
the 新扶愛 page-4 clause mispair. Adding more rules to the old heuristic is not
the right next move.

Recommended next step: improve alignment post-processing, not heuristic rules.
Specifically, group adjacent alignment opcodes back into reviewer-sized spans,
suppress tiny heading/footer fragments unless backed by strong visual evidence,
and keep using the image-diff fallback while recall remains default OFF.

## Validation

- `python -m py_compile backend\config.py backend\services\diff_service.py backend\scripts\compare_recall_strategies.py` - pass
- `python -m pytest backend\tests --basetemp backend\tmp_pytest_probe -p no:cacheprovider -q` - 62 passed
- MinerU OCR A/B over 8 EDM pairs - pass
