# PDF 比對系統 - 歷史問題與優化紀錄 (Archive)

這份文件總結了系統在早期開發與優化過程中遇到的問題及解決方案，供未來技術追查參考。

## 1. 視覺與高亮標示優化 (Phase 1)
- **問題**：早期引擎採用像素級相減，導致抗鋸齒、字體渲染差異被標示成大量雜訊。且半透明標示顏色不夠顯眼。
- **解決方案**：
  - 調整標示顏色為不透明的鮮豔黃橘色，確保在灰階 PDF 上依然清晰。
  - 將像素比對移到後端執行，前端改為依據 `BBox` 繪製外框，而非單純的圖層相減。

## 2. 解析引擎聯集策略 (Phase 2-3)
- **問題**：部分保險 DM 使用「外框字」(Create Outlines)，導致 PyMuPDF 抓不到文字層；而 Docling 解析器雖能強制 OCR，但對表格的支援與中文抗鋸齒容忍度不足。
- **解決方案**：
  - 採用「四路聯集引擎」：將原生文字層比對、OCR 備援、表格特徵比對、圖片感知哈希 (pHash) 結合。
  - 只要任何一個引擎發現差異，即標示該區塊，做到「零漏報」(Zero-Miss)。

## 3. 表格與版面變更處理 (Phase 4-5)
- **問題**：大面積的表格或版面變更時，若強制送入 Tesseract OCR，會產生大量無意義的亂碼文字，導致使用者在審核「內容變更」時被亂碼干擾。
- **解決方案**：
  - **區域大小判定**：若差異區塊超過 8000px² 且寬高 > 40px，判定為「表格/版面變更」。
  - **條件式 OCR**：對大型區塊若無原生文字層，雖然仍會執行 OCR（以防漏掉單純加了引號等微小文字修改），但前端會以「僅供參考」標註 OCR 亂碼，並優先將高解析度 (2x) 的截圖放在最上方供人工比對。
  - **細線雜訊濾除**：針對寬高小於 20px 且沒有原生文字的差異（例如排版格線的微小位移），直接於後端濾除，不再誤判為版面變更。

## 4. 重新比對 API (Recompare)
- 由於比對任務結果會持久化寫入 SQLite，為避免每次引擎升級後都需要重新上傳檔案，新增了 `POST /api/compare/recompare/{task_id}` 功能，可直接使用本機暫存的原始檔案重跑比對。

## 5. 早期移機手冊 (已作廢)
- 早期移機需要手動操作 Docker image load，現已整合至 `DEPLOY.md` 並提供 `一鍵啟動PDF比對系統.bat`，自動化處理 Docker 的啟動與網頁開啟。

## 6. 2026-05-20 圖片型 PDF 頁尾漏抓與 OCR 亂碼修正
- **問題**：`fa358c6` 之後過度依賴較小的視覺 component / NCC 過濾，導致台灣人壽 EDM 第 2 頁右下角版號與 `Control No.` 漏抓；同時局部 OCR 仍可能把亂碼當成一般文字差異顯示。
- **重要事實**：
  - 該案例兩份 PDF 都是 image-only PDF，PyMuPDF 文字層為 0。
  - 第 2 頁頁尾右側有 `2162` changed pixels，`Control No.` 區域最大 component 有 `1086 px`，不是沒變。
  - 正確結果必須抓到 `2301-2501-OP2-0043` -> `OP-2407-2607-0503`。
- **解決方案**：
  - 恢復 broad visual scan，`diff_pixels()` 的 connected-component dilation 維持 `iterations=4`。
  - 新增 header/footer protected OCR pass，優先抽取 `Version`、`Control No.` 等高價值欄位。
  - OCR 只有在可靠或符合 priority pattern 時才進入 `old_value/new_value`，否則保留為 image diff，避免 UI 顯示亂碼。
  - 保留 MinerU + Docling 預設並行解析，不再誤寫成 Docling 僅備援。
- **完整護欄**：見 `docs/pdf_diff_guardrails.md`。未來修改 PDF diff/OCR/部署前，必須先看該文件。
