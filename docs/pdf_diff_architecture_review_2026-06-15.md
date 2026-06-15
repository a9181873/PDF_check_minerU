# PDF Diff Architecture Review 2026-06-15

下次修改 PDF 比對、OCR、表格偵測、效能或 OCI 部署前，先讀本文件、`docs/pdf_diff_recent_summary_2026-06-14.md` 與 `docs/pdf_diff_guardrails.md`。

## 背景

使用者回報兩個阻擋問題：

1. `商品DM/新扶愛`：新舊版大表格明顯不同，但正式差異清單沒有顯示大表格區域。
2. `商品DM/美利保`：表格內大量數字變更，但正式清單只抓到少數局部數字。

同時效能退化，新扶愛實測 `diff_pixels` 約 61 秒，raw pixel candidates 124 筆，正式報告只剩 9 筆，代表大量 OCR/候選處理成本最後被後段 filter 丟掉。

## 專家檢討結論

這不是單一 heuristic bug，而是 image-only PDF 的架構順序錯誤：

1. `parse_pdf()` 判定 `is_image_pdf=True` 後直接回傳，image-only PDF 沒有進入 MinerU/Docling 表格層。
2. `generate_diff_report()` 在 image-only 模式走 pixel-only，不跑 `diff_tables()`。
3. `diff_pixels()` 有抓到大表格或大版面區域，但通常只能產生 `IMAGE_DIFF / Page N 表格/版面變更`。
4. 正式合併時過去使用 `keep_image_diffs=False`，導致大表格 visual evidence 被靜默移除。
5. 局部 Tesseract OCR 嘗試解釋大量小候選，造成速度慢；但 OCR 不可靠時又被 gate 丟掉，形成「先花時間、後丟棄」。

## 2026-06-15 P0/P1 修正

### P0：大表格不再靜默漏報

- image-only 分支改用 `keep_image_diffs=True`。
- 新增 `_is_reviewable_visual_item()`：
  - 保留大面積 `表格/版面變更`。
  - 保留有 OCR/text explanation 的 visual item。
  - 小圖形、線條、色差、低可信度 visual item 仍會被壓掉。
- `_drop_non_numeric_modifications()` 在 image-only 模式會保留可審核表格/版面區域。
- `suppressed_count` 不再硬設 0；image-only 模式會回報被降噪的低可信度 visual 候選數。

### P1：先止住 OCR 浪費

- `diff_pixels()` 補 candidate funnel metrics：
  - `pixel_pages_scanned`
  - `pixel_pages_with_diffs`
  - `pixel_raw_regions`
  - `pixel_region_categories`
  - `pixel_pre_ocr_candidates`
  - `pixel_priority_ocr_attempts`
  - `pixel_priority_ocr_regions`
  - `pixel_priority_ocr_skips`
  - `pixel_ocr_calls_total`
  - `pixel_high_zoom_ocr_calls`
  - `pixel_numeric_fallback_ocr_calls`
  - `pixel_numeric_fallback_skips`
  - `pixel_ocr_budget_skips`
  - `pixel_large_visual_candidates`
- OCR 前先分類區域：
  - `large_visual`
  - `text_band`
  - `small`
  - `mid_visual`
- 忙碌頁面加 OCR budget：
  - region 數 > 45 時，每頁最多 14 個一般 OCR candidate，numeric fallback 最多 4 個。
  - 其他頁最多 28 個一般 OCR candidate，numeric fallback 最多 8 個。
- 中型無文字 visual 區域不再全部丟進 OCR，只讓小型候選與文字帶進 OCR。
- 頁首/頁尾 priority OCR 改為先看 changed component，再只 OCR 實際變動範圍；footer 只保留右側候選，避免整條頁尾反覆 OCR。

## 前端顯示修正

- `IMAGE_DIFF` 顯示名稱從「視覺差異」改為「表格/版面」。
- popup 無 OCR 文字時，提示使用者看區域截圖。
- suppressed banner 改為「低可信度表格/版面候選已降噪」，避免使用者以為系統在比較顏色。
- 差異統計仍使用「版面/區域」欄位。

## 尚未完成的 P2/P3

這次是止血與效能降浪費，不是完整表格 OCR 重構。

後續仍要做：

1. image-only forced OCR 的 `tables` 接入表格 diff，不只用 paragraphs。
2. 建立 `TableArtifact`：page、bbox、row/column/cell、cell OCR text、confidence、source engine。
3. 表格配對改成 page + bbox IoU + structure signature，不再只靠順序。
4. 美利保這類密集數字表要支援：
   - OCR 可靠時逐格報數字差異。
   - OCR 不可靠時報整表/整欄需人工核對，且附高信心樣本。

## 驗收底線

修改後必跑：

```bash
python3 -m pytest backend/tests
git diff --check
```

有 Docker 與 `商品DM/` 時，必跑真實 PDF 回歸：

| 樣本 | P0 必過 |
|---|---|
| 新扶愛 | 大表格/版面區域不可靜默消失；電話、標點、同數字段落重排不可誤報。 |
| 美利保 | 不可只剩一個局部表格數字；至少要有主要表格區域級可審核項目。 |
| 鳳守愛 | Page 2 `24 -> 28` 與 Page 6 footer 必須保留。 |
| 慈愛微型 | 單一位數序號噪音不可回來。 |
| 美保發 | Page 2 內容與 footer 必須保留。 |
| 臻美利 | 大段註解與 footer 必須保留，不可出現假 `Version: 975.18`。 |

## 本輪 Docker 回歸結果

環境：`pdf-check-backend:latest`，掛載目前工作區程式碼，`ENABLE_IMAGE_TEXT_RECALL=false`，`DATA_DIR=/tmp/runtime`。

| 樣本 | total | report 秒數 | 結果 |
|---|---:|---:|---|
| 鳳守愛 | 2 | 5.5s | 保留 Page 2 `24 -> 28` 與 Page 6 footer。 |
| 慈愛微型 | 3 | 19.3s | 單一位數序號噪音未回來；保留 Page 3 表格/版面與 Page 4 footer。 |
| 新扶愛 | 6 | 31.1s | Page 1/2/3/4 表格/版面皆進正式清單；Page 4 內容與 footer 保留；電話/標點噪音未回來。 |
| 美保發 | 2 | 10.6s | Page 2 表格/版面與 Page 4 footer 保留。 |
| 美利保 | 2 | 24.8s | Page 3 表格/版面保留，不再只顯示單一局部數字；Page 6 footer 保留。 |
| 臻美利 | 4 | 15.3s | Page 2/3/4 表格/版面保留；長段 OCR 亂碼被壓掉；Page 6 footer 保留。 |

效能從新扶愛先前約 62 秒降到約 31 秒；美利保約 35 秒降到約 25 秒。這是 P1 止血，不是 3~5 秒最終目標。要再壓到 3~5 秒，需要 P2/P3：pre-OCR region coalesce、表格 artifact、OCR cache 或低優先 OCR 背景化。

## 不要再回退

- 不要把 image-only 的 `IMAGE_DIFF` 一律丟掉。
- 不要用擴大 Tesseract 小框 OCR 來解大表格。
- 不要把低可信度 OCR 文字硬塞進正式差異。
- 不要只看 `total_diffs` 判斷成功；要看必抓項與必禁誤報。
- 不要把 PaddleOCR 直接升為正式 diff 來源，除非固定樣本證明漏報下降且誤報沒有增加。
