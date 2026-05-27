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
- Raw local output, first A/B: `C:\tmp\edm_recall_ab_alignment.json`
- Raw local output, after alignment post-processing:
  `C:\tmp\edm_recall_ab_alignment_postprocess.json`
- PDF-first visual review sheets: `runtime\codex_pdf_visual_review\case*.jpg`
- PDF-first visual summary: `runtime\codex_pdf_visual_review\summary.json`
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

## PDF-First Review

Before judging OCR output, the samples were inspected as rendered PDFs:

| EDM pair | PDF type | Human review expectation |
| --- | --- | --- |
| 新保安心 | Image-only, 2 pages | Page 1 has a small header/date/control-number change. Page 2 has broad clause/section changes; reviewers need visible regions or readable clause spans, not only a few OCR fragments. |
| 鳳守愛 | Image-only, 6 pages | Mostly unchanged. Page 2 has a tiny mark-level change; page 6 has a small footer/control-area change. |
| 平安Call 家庭版 | Mixed text + image, 1 page | Text layer exists on both PDFs, plus image content. Do not treat this as image-only; text-layer diff remains primary, with visual fallback only for image-rendered regions. |
| 慈愛微型 | Image-only, 4 pages | Several large visual regions change. OCR snippets alone are not enough to review the page-level edits. |
| 新扶愛 | Image-only, 4 pages | Large redesign/content movement across pages. The reviewer should see title/header changes and changed table/section regions; fragmented OCR add/delete snippets are low value. |
| 美保發 | Image-only, 4 pages | Page 2 has the important table/value region change. Page 4 is mainly footer/control text. Alignment-only customer-service text is secondary and must not hide the page-2 visual diff. |
| 美利保 | Image-only, 6 pages | Small visual/control-region changes only; no recall strategy difference in this run. |
| 美鑫傳家 | Image-only, 6 pages | Pages 2-3 contain the key table/rate/value changes, including visible rate and total-value updates. Reviewers need table/region evidence plus high-confidence OCR snippets such as `3.90% -> 4.00%`. |

This confirms the important split: some EDMs are pure image scans, while
`平安Call 家庭版` is mixed text + image. The recall experiment should therefore
not be read as "OCR should replace visual diff"; OCR recall is a supplement, and
image-diff fallback remains required for large image-rendered table/section
changes.

## April Reference

The better April direction was not a single detector. It was triangulation:

- native text recognition for real text-layer PDFs, so OCR noise does not create
  fake wording changes;
- OCR only where needed, especially image-only or outlined-text regions, and only
  when the recognized text has enough signal;
- bbox / position as the reviewer-facing truth, so a detected change lands on the
  exact page, table cell, clause block, or footer area.

Relevant April commits reinforce this:

- `79cd358` and `675c01a`: table extraction moved toward cell-level bboxes and
  precise highlights;
- `25d25d9`: table cell changes were refined to character-level spans instead of
  giant table overlays;
- `6c79347`, `7f4a4ce`, `efb6d7a`, `7a15917`: visual diffing gained pHash,
  shift-invariant NCC, local OCR, and graphic-line suppression, so pixel
  evidence was cross-checked instead of blindly reported.

So the rule for this regression is: use native text, OCR text, and position
together. A recall item is useful only when it either explains a visible
positioned region or gives a high-confidence text snippet that helps the reviewer
inspect that region faster.

## Result Summary

| EDM pair | alignment after postprocess | heuristic | Finding |
| --- | ---: | ---: | --- |
| 新保安心 | 4 | 2 | Alignment is less fragmented than the first run (`11 -> 4`) but still not reviewer-ready for page 2. The PDF shows broad clause changes, so image-diff regions remain necessary. |
| 鳳守愛 | 0 | 0 | No recall strategy difference. PDF-first review shows only tiny visual/control-area changes. |
| 平安Call 家庭版 | 0 | 0 | No recall strategy difference. This is a mixed text + image PDF, so normal text diff should remain the main path. |
| 慈愛微型 | 3 | 1 | Alignment still emits small OCR/date fragments. PDF-first review shows larger visual page changes, so recall snippets alone are insufficient. |
| 新扶愛 | 3 | 1 | Alignment improved from the first run (`8 -> 3`) but still contains title/phone/date fragments. The true review target is page/section redesign visibility. |
| 美保發 | 1 | 0 | Alignment-only candidate is a footer/customer-service line. PDF-first review shows the key change is page-2 table/value visual content, so image-diff fallback is the important evidence. |
| 美利保 | 0 | 0 | No recall strategy difference. |
| 美鑫傳家 | 7 | 7 | Alignment now keeps a clean `3.90 -> 4.00` rate item, but table totals and dense numeric changes still need visual table-region evidence. |

## Interpretation

Alignment post-processing helps, but the PDF-first review changes the judgment:
OCR recall is not the primary evidence for image-only EDMs with large table or
clause-region edits. The old heuristic should not receive more rules. Alignment
should remain the preferred recall experiment because it handles OCR
re-segmentation better, but its output must be judged against the rendered PDF:

- keep reviewer-sized numeric/rate snippets such as `3.90 -> 4.00`;
- suppress tiny one-sided heading/footer fragments unless backed by a strong
  amount, percent, phone, or long CJK signal;
- suppress moved identical clauses that appear elsewhere in the other document;
- keep image-diff fallback as first-class evidence for large image-rendered
  table/section changes.

The practical target is not "more recall items"; it is "the reviewer can quickly
see the real changed location and then confirm whether the content is correct."

## Detailed Lessons

1. Count-based A/B is not enough.
   The first A/B compared alignment and heuristic by item count, but the PDF
   review showed that fewer or more items does not mean better review quality.
   For image-only EDMs, a single crop-backed visual region can be more useful
   than several unreadable OCR fragments.

2. PDF reality must be inspected before code output.
   The samples include both image-only PDFs and mixed text + image PDFs. A mixed
   text PDF should stay on the native text-layer path first; an image-only PDF
   needs visual evidence and targeted OCR assistance. Treating all files as the
   same category is the source of several false conclusions.

3. The correct decision model is three-way fusion.
   The stable reviewer signal should come from native text recognition, OCR
   recognition, and bbox/visual position together. Native text answers "what did
   the PDF already know"; OCR answers "what can we read from image-rendered
   content"; bbox/visual diff answers "where should the reviewer look".

4. OCR recall is an explanation layer, not the ground truth.
   MinerU OCR can recover useful rate/date/amount snippets, but it also creates
   garbage around dense Chinese clauses, footer text, and tables. OCR-only output
   should not replace visual regions unless the text signal is strong and the
   bbox is positioned on the actual changed area.

5. The April approach remains the better north star.
   Cell-level bboxes, character/token-level comparison, pHash, NCC, local OCR,
   and graphic suppression all point to the same principle: cross-check evidence
   before surfacing a diff. This regression work should keep moving toward that
   fusion model instead of adding more one-off recall heuristics.

## Update And Fix Log

### Commit `5545440` - A/B baseline

- Added the EDM MinerU OCR A/B audit for `IMAGE_TEXT_RECALL_STRATEGY=alignment`
  vs `heuristic`.
- Recorded that alignment improved recall in some non-IoU cases but produced
  too many fragmented OCR snippets.
- Confirmed recall remained default OFF and image-diff fallback remained the
  safety net.

### Commit `a83fa5e` - Alignment post-processing

- Increased nearby alignment opcode grouping so related header/date/control
  number changes are kept as one reviewer-sized span.
- Expanded diff groups to include full numeric tokens such as decimal rates and
  percentages.
- Suppressed moved identical clauses when the same normalized text already
  exists elsewhere in the opposite document without new numeric evidence.
- Suppressed tiny one-sided number fragments unless they carry a stronger
  signal: amount, percent, phone-like number, or longer CJK text.
- Added tests for header number merging, moved clause suppression, tiny heading
  filtering, one-sided amount retention, and decimal-rate token expansion.
- Re-ran MinerU OCR A/B after the change:
  - New Bao An Xin: alignment reduced from 11 to 4, but page 2 still needs
    visual region evidence.
  - Xin Fu Ai: alignment reduced from 8 to 3, but remaining OCR snippets are
    still secondary to page/section visual changes.
  - Mei Xin Chuan Jia: alignment keeps a cleaner `3.90 -> 4.00` signal, but
    dense table changes still need table/region evidence.
  - Mei Bao Fa: alignment-only footer text is not the main change; page 2 visual
    table/value diff remains the key reviewer evidence.

### Current documentation update

- Added the PDF-first review summary so future work does not judge the output by
  OCR item count alone.
- Added the April reference section and explicitly documented the three-way
  fusion principle: native text + OCR + bbox/position.
- Added this detailed lesson/fix log so the next implementation step can start
  from the user-facing review goal, not from another isolated heuristic rule.

### Current implementation update - Visual/Text fusion

- Added a first fusion layer inside `merge_diff_results()` for image-PDF mode
  when visual fallback is retained.
- When an OCR/native-text item overlaps a visual `IMAGE_DIFF` region, the output
  now keeps the visual region bbox as the reviewer-facing location and attaches
  the text/OCR summary as the explanation.
- Numeric OCR explanations, such as rate changes, promote the fused item to
  `number_modified` while preserving the larger table/section bbox.
- Non-numeric OCR explanations remain `image_diff` so the final numeric filter
  does not accidentally delete the visual fallback.
- Unexplained visual regions still remain visible, preserving the zero-miss
  behavior for image-only tables, clauses, and layout changes.
- Fusion now assigns each OCR/text item to the best matching visual region by
  bbox coverage and IoU, so a tight table-row/field region wins over a broad
  page-level region when both overlap the same text.
- `generate_diff_report()` summary now reports `visual_fused=N` when visual
  regions are explained by OCR/text.
- Added tests covering:
  - visual-only fallback retention;
  - numeric OCR fusion into a visual region;
  - non-numeric OCR preserving `image_diff` fallback type;
  - preference for tighter visual regions over broad overlapping regions;
  - full `generate_diff_report()` fusion summary.

## Remaining Risks

- The visual review sheets are local runtime artifacts and are not committed.
  They are useful evidence, but a repeatable script/report should eventually
  generate a compact reviewer-facing artifact.
- Some OCR text in local console output appears garbled due encoding, so final
  product evaluation should rely on UI crops/positions and normalized values,
  not raw console text alone.
- The fusion layer currently uses bbox overlap and content type. It does not yet
  score confidence from OCR quality, table structure, page class, and visual
  region size together.
- Image-only table pages still need a stronger table-region or cell-region
  explanation path. OCR can identify rates and totals, but the reviewer must see
  the table area that changed.

## Next Implementation Direction

The next implementation should deepen the fusion layer instead of extending the
old heuristic:

1. Classify each page as native-text, image-only, or mixed text + image.
2. Generate candidate regions from pixel/image diff and table/cell bboxes.
3. Attach native text and OCR snippets to the nearest candidate region using
   bbox overlap first, then distance and reading-order proximity.
4. Score each candidate by evidence type:
   - high: numeric/rate/amount text with matching visual region;
   - medium: large visual region with weak OCR, surfaced as crop-backed
     `image_diff`;
   - low: OCR-only tiny heading/footer fragments, suppressed unless they match a
     known high-value pattern.
5. Show the reviewer the positioned region first, then the best text/OCR summary.

## Validation

- `python -m py_compile backend\services\align_service.py backend\tests\test_align_service.py` - pass
- `python -m pytest backend\tests\test_align_service.py backend\tests\test_image_text_recall.py --basetemp backend\tmp_pytest_probe -p no:cacheprovider -q` - 28 passed
- `python -m py_compile backend\services\diff_service.py backend\tests\test_diff.py` - pass
- `python -m pytest backend\tests\test_diff.py --basetemp backend\tmp_pytest_probe -p no:cacheprovider -q` - 26 passed
- `python -m pytest backend\tests --basetemp backend\tmp_pytest_probe -p no:cacheprovider -q` - 71 passed on the current local worktree
- MinerU OCR A/B over 8 EDM pairs after alignment post-processing - pass
- PDF-first visual sheets generated with PyMuPDF from `C:\Users\JY\Downloads\DM` - pass
