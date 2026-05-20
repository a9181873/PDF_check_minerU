# PDF Diff Diagnosis - 2026-05-19

## 2026-05-20 Update

The diagnosis below was acted on before deployment. The current fix restores broad visual scanning, adds a protected header/footer OCR pass, extracts `Version` and `Control No` patterns, and prevents low-quality OCR garbage from becoming ordinary text diffs. The specific Page 2 footer change is now detected as:

- Old: `Version: 2023.02; Control No: 2301-2501-OP2-0043`
- New: `Version: 2024.07; Control No: OP-2407-2607-0503`

MinerU + Docling table parsing was also returned to the original parallel default.

## Case

Files:

- `台灣人壽新保安心住院醫療終身健康保險_商品DM(公版)-FINAL(製作人-陳柏婷)-1120209.pdf`
- `台灣人壽新保安心住院醫療終身健康保險_商品DM_20240701適用.pdf`

User-observed problems after the last change:

1. The top area still shows OCR garbage text.
2. Some middle-page regions look visually identical to the reviewer but are still reported as differences.
3. The bottom-right footer version/date and `Control No.` change is missed.
4. The last fix (`fa358c6 fix: keep PDF diff markers granular`) over-corrected the behavior. This area used to be detected well before that change.

## PDF Structure Findings

Both PDFs are image-only PDFs:

- 2 pages each.
- Each page contains one full-page embedded image.
- PyMuPDF native text extraction returns `0` text chars and `0` words on every page.
- Therefore, the comparison cannot rely on native PDF text layer for these files.

This case must be treated as scanned/image EDM comparison, with OCR as a targeted assist and pixel diff as visual evidence.

## Critical Footer Finding

Page 2 bottom-right footer is a real change, not a false positive and not visually unchanged.

Measured pixel facts:

- Page 2 footer-right region has `2162` changed pixels.
- The `Control No.` area has a largest connected component of `1086 px`.
- This means the footer version/control number change is present in the rendered image.

Targeted OCR on the full Page 2 footer can read the relevant content:

- Old footer: `《2023.02》 Control No : 2301-2501-OP2-0043`
- New footer: `《2024.07》 Control No : OP-2407-2607-0503`

Conclusion:

The footer miss is not because OCR cannot read it. It is likely caused by the current pixel component/NCC filtering path suppressing small text differences before a sufficiently wide footer OCR pass is performed.

## Regression Note

The previous behavior was better for this footer/control-number case. The last change reduced/altered pixel grouping and merge behavior to avoid oversized page markers, but it also made the engine too dependent on small local components. That can lose small-but-important text like page footer version numbers.

Do not treat `fa358c6` as a complete fix. It should be revised or partially reverted before deploying.

However, not every idea in `fa358c6` is necessarily wrong. Lowering the nearby text-diff merge radius may still be useful, because it reduces the chance that separate paragraphs, table cells, or left/right columns get merged into one oversized marker. The mistake was allowing the broader small-component/NCC filtering strategy to suppress important footer/control-number changes.

## Strategy Direction

Recommended direction for the next fix:

1. Preserve the prior ability to catch footer/control-number changes.
2. Keep the reduced text merge radius under consideration, but decouple it from footer/header filtering.
3. Use a broad-to-fine comparison pipeline:
   - broad scan to find changed zones across the two rendered pages
   - refinement pass to split those zones by text bands, table rows/cells, footer/header patterns, and local visual similarity
4. Some pages really do have broad layout movement. The system can report layout movement, but it should not immediately merge everything into one giant marker. Try to refine into reviewable local differences first.
5. Add a dedicated high-priority footer/header OCR pass for image-only PDFs.
6. Match important patterns such as `Control No`, version dates like `2024.07`, and policy/document control numbers.
7. Use pixel diff as evidence, but do not let NCC suppress known high-value footer/header zones.
8. Suppress OCR garbage in UI when OCR quality is low or the extracted text does not match meaningful patterns.
9. For middle-page false positives, compare larger OCR text bands/paragraph zones before reporting pixel-only differences.

## Do Not Forget

For this specific case, remember:

> Page 2 footer-right has `2162` changed pixels, and the `Control No.` area has a largest component of `1086 px`. It is a real change. Missing it is a regression introduced by the last adjustment, not an absence of visual difference.
