# PDF Diff Recent Change Summary 2026-06-14

下次修改 PDF 比對、OCR、截圖、同步滑動或 OCI 部署前，先讀本文件與 `docs/pdf_diff_guardrails.md`。這份摘要整理 2026-06-13 到 2026-06-14 幾次修正的根因、目前設計、必跑樣本與不要再踩的邊界。

## 最近相關 Commit

| Commit | 主題 | 核心變更 |
|---|---|---|
| `a50c4b5` | 新舊 PDF 同步滑動 | 改用 scroll ratio、`requestAnimationFrame`、programmatic scroll marker，降低左右窗格速度不一致與互相觸發問題。 |
| `c785aaa` | 比對任務可用速度 | old/new PDF 並行解析；報告先可用，snapshot/crop 可背景產生；加入 pipeline timing。 |
| `0eb7c79` | image PDF OCR 降噪 | 純 `IMAGE_DIFF` 不進正式清單；只保留 priority field、強數字變更、可靠 OCR 文字。 |
| `572f68a` | 圖片內小數字偵測 | 保留鳳守愛 Page 2 `24 -> 28` 這種小型 graphic number change。 |
| `5677b89` | 流程文件化 | 記錄正式流程不是全頁 OCR，也不是 PaddleOCR 主流程。 |
| `620eb94` | 收緊 image OCR 數字過濾 | `NUMBER_MODIFIED` 也套 OCR gate；壓掉單一位數 OCR 噪音；金額 OCR 髒字元高倍率重讀。 |

## 這次真正發現

1. 為了抓鳳守愛 `24 -> 28` 加的高倍率小區塊 OCR fallback 太寬，會在新扶愛、慈愛微型這類掃描 DM 上把段落重排、標點差異、清單序號誤當數字變更。
2. image PDF 的可靠度 gate 原本只擋 `TEXT_MODIFIED`，沒有擋 `NUMBER_MODIFIED`。只要 OCR 文字裡有電話、年齡、保費、15 足歲等數字，就可能繞過 gate。
3. `圖片數字變更` 只能用在短小、緊湊、確定是圖片內數字的結果，例如 `24 -> 28`。長段 OCR 文字即使包含數字，也要顯示為一般 `內容變更`。
4. 單一位數 OCR pair 風險高，例如 `2 -> 3`、`3 -> 5`、`9 -> 1`，常見來源是列表序號、段落位移、OCR 片段，不應直接進正式差異。
5. 金額 OCR 可能把 `1` / `0` 誤讀成 `i` / `O`。只在同一局部 crop 追加高倍率 OCR 可以改善顯示值，例如美利保從 `447,6i12` 修成 `447,612`。

## 目前正式流程

正式差異清單採分層策略，不是全頁 OCR：

1. 有文字層 PDF：優先用 PyMuPDF / fitz 文字層與表格層。
2. 表格（2026-06-27 更新）：先做 PyMuPDF 輕量快篩；疑似表格才依 Docling → MinerU 循序 fallback。舊雙引擎競速僅供 A/B。
3. image-only PDF：先 pixel diff 找差異頁與差異框。
4. 局部 OCR：只在 header/footer priority field、小型差異框、可靠文字/數字訊號上使用。
5. PaddleOCR：目前只做 A/B metadata，預設不進正式差異。

## 必跑黃金樣本

本機有 `商品DM/` 時，至少跑下列自然配對：

| 樣本 | 預期重點 |
|---|---|
| 鳳守愛 `20260213 -> 20260506` | 2 筆：Page 2 `24 -> 28`，Page 6 footer Control No/version。 |
| 慈愛微型 `1140825 -> 1141003` | 壓掉單一位數序號噪音，保留 Page 3 內容差異與 Page 4 footer。 |
| 新扶愛 `1131001 -> 20251020` | 不要把電話、標點、同數字段落重排列為差異；保留 Page 4 條文變更與 footer。 |
| 美保發 `1130101 -> 1130418` | 保留 Page 2 內容變更與 Page 4 footer；不要誤叫圖片數字變更。 |
| 美利保 `1130522 -> 1130701` | 金額 OCR 要可讀，`447,612 -> 463,071.00` 類結果不要出現 `i/O` 髒字元。 |
| 臻美利 `1130101 -> 1130418` | 大段註解新增/移動是內容差異，不是純顏色；footer 要保留。 |

## 下次修改檢查清單

1. 先看 `git status --short`，不要把 `商品DM` PDF 加進 commit。
2. 改 OCR/filter 前先讀 `docs/pdf_diff_guardrails.md` 與本文件。
3. 先跑單元測試：

```bash
python3 -m pytest backend/tests
git diff --check
```

4. 影響 `diff_pixels()`、`_drop_non_numeric_modifications()`、OCR gate 時，要用 Docker 跑上述 6 組 PDF 摘要。
5. UI scroll 或 PDF viewer 變更，要用實際 PDF 手動檢查新舊同步滑動。
6. 涉及任務速度時，看 `engine_stats.pipeline_timings_seconds`，不要只看體感。
7. 推送前確認只有應提交檔案 staged。
8. OCI 部署時只更新 `/home/ubuntu/pdf-check-minerU`，只重建 `backend-minerU`，不得覆蓋 OCI 的 compose override。

## 不要再做

- 不要把全頁 OCR 當主流程，會慢且誤報回來。
- 不要讓 PaddleOCR 直接改正式 diff item，除非完整固定樣本證明誤報沒有增加。
- 不要新增另一套 OCR/model 來遮掩規則問題。
- 不要讓 `NUMBER_MODIFIED` 跳過 image PDF OCR 可靠度 gate。
- 不要把單一位數 OCR pair 當成可靠正式差異。
- 不要把長段 OCR 文字標成 `圖片數字變更`。
- 不要為了截圖/crop 完成才讓報告可用，報告可用性要優先。
- 不要直接覆蓋 OCI `docker-compose.yml`，遠端有本機不同設定。

## 最近驗證結果

2026-06-14 最後一輪 Docker 摘要：

| 樣本 | 結果 |
|---|---|
| 鳳守愛 | `total=2`, `number_modified=2`, 保留 `24 -> 28` 與 footer。 |
| 慈愛微型 | `total=3`, 單一位數序號噪音未回來。 |
| 新扶愛 | `total=9`, Page 1/2 電話與標點噪音未回來，Page 4 條文與 footer 保留。 |
| 美保發 | `total=2`, Page 2 內容變更與 footer。 |
| 美利保 | `total=3`, 金額 OCR 顯示為 `447,612 -> 463,071.00`。 |
| 臻美利 | `total=4`, 大段註解內容差異與 footer。 |

單元測試：`backend/tests` 共 107 passed。
