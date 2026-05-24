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

## 7. 2026-05-22 辨識召回稽核：影像型 PDF 大段內容變更會被靜默丟棄

專家團隊調查（目標：讓審核人員清晰、快速辨識兩份 PDF 差異）。對象為 4 份台灣人壽 DM，兩組改版對：
新保安心（1120209/FINAL → 20240701）、鳳守愛防癌（20260213 → 20260506）。皆為 image-only PDF。

### 各對的真實差異（ground truth，逐頁人工比對）
- 新保安心：
  - p1 商品文號 `112年2月9日…1110152342號` → `113年7月1日…11304921175號`（文字+數字）。
  - **p2 身故/喪葬段新增整句**：「訂立本契約時，以受監護宣告尚未撤銷者為被保險人，其身故保險金變更為喪葬費用保險金。」
  - p2 註1/註2 用語改寫、投保規則表字距（多為排版）。
  - p2 頁尾 `2023.02 / 2301-2501-OP2-0043` → `2024.07 / OP-2407-2607-0503`。
- 鳳守愛：
  - p2 資訊圖「**24**年增長超過4.2倍」→「**28**年增長超過4.2倍」（數字，嵌在點陣圖內）。
  - p6 頁尾 `2026.02 / OP-2602-0081` → `2026.05 / 2605-OP-0029`。
  - p1/p3/p4/p5 實質相同。

### 召回稽核結論（會不會被顯示）
- 會抓到：兩組頁尾 Version/Control No（受保護 OCR → NUMBER_MODIFIED）；鳳守愛 p2 `24→28`（diff_images SSIM+OCR，CJK 長串通過可靠性檢查）。
- **會被漏掉（最關鍵破口）**：新保安心 p2 新增的整句條款。它是大段 CJK，命中 `is_large_region`（`diff_service.py` 約 line 1003）→ 不做 OCR → 標成 IMAGE_DIFF → 在 `merge_diff_results`（約 line 1677）被全數丟棄。審核清單上看不到這條最重要的內容變更。
- 注意：先前一度誤判「影像型 PDF 全部歸零」並不正確；頁尾與高信號小區塊會存活。真正風險集中在「大區塊」與「OCR 不可靠」的真實內容變更。

### 核心張力（已知設計，非單純 bug）
`diff_service.py` 約 line 1677（丟棄所有 IMAGE_DIFF）與約 line 1685 `_drop_non_numeric_modifications`（只留新增/刪除與數字有變）是刻意的降噪策略。
副作用：整段新增、純文字條款改寫（無數字變化）會一併被丟。降噪 vs 不漏真改在影像型 DM 上直接衝突。

### 已驗證的兩個確定 bug
1. **MinerU content_list bbox 為 0–1000 正規化**，但 `parser_service.py` `_mineru_bbox_to_bbox`（約 line 136）當點座標用 → 表格框會畫錯位置。已用 repo 內 20 個 `*_content_list.json` 驗證：xmax/ymax 一致落在 968–983，與頁數/內容無關。影像型不走 MinerU 故主情境未爆，但文字型 PDF 表格標記會偏移。修法：x*=page_w/1000、y*=page_h/1000 後再翻 Y；或改用 `middle.json` 的像素座標。
2. **整表替換消失**：表格 ≥70% 變更時產生單一 item，其 old_value==new_value（同一句「整表替換」字串），隨後被 `_drop_non_numeric_modifications` 丟掉（`diff_service.py` 約 line 578 ↔ 1697）→ 大改費率表整個不見。

### 決議方向（2026-05-22）
- **採「加 MinerU 影像 OCR 召回層」**：影像型 PDF 也跑 MinerU `parse_method=ocr, lang_list=chinese_cht, table_enable=true, formula_enable=false`，取得區域文字+座標，做位置對齊文字比對，作為現有像素/頁尾護欄之後的「召回層」（不取代、不繞過護欄；原始 footer/Control-No、dilation iterations=4 一律不動）。MinerU 文字僅用於補既有像素變更區的 old/new，且必須通過既有可靠性檢查（`_is_reliable_ocr_pair`、priority pattern、長 CJK / dense numeric），不得單獨成為 TEXT_MODIFIED。
- 風險：中。失敗模式：無框表格虛構儲存格、新舊區塊重切導致 bbox 對不上、版面 reflow 產生位置型雜訊、延遲增加。
- **驗證**：使用者會把這 4 份 PDF 放入 `samples/`，再以容器內 `scripts/diagnose-pdf-samples.ps1` 跑真實回歸。必過底線（見 `pdf_diff_guardrails.md`）：`baoxinanxin` 不得出現 `[PAYV` 亂碼；兩組頁尾 Version/Control No 必須仍偵測到；`臻美利` 不得出現假 `Version: 975.18`。
- 旁支低風險修正（可先做）：上述兩個確定 bug；前端/回應加「已抑制 N 筆視覺變更」提示，避免靜默漏報。

### 實作狀態（2026-05-22）
- 已完成且通過單元測試（backend/tests 全套 39 passed；host 無 fitz/tesseract，故僅跑不依賴它們的純邏輯）：
  - Fix #1：`parser_service._mineru_bbox_to_bbox` 改為以頁面尺寸把 0–1000 正規化座標縮回點座標（新增 `_get_page_sizes_fitz`，`_parse_via_mineru` 改收 `page_sizes`）。測試見 `tests/test_parser_service.py`。
  - Fix #2：`diff_service._diff_table_cells` 的整表替換 item 改帶入實際變更樣本，使其在非數字過濾後存活；數字表標為 NUMBER_MODIFIED。測試見 `tests/test_table_diff.py`。
  - 召回層演算法：`diff_service.diff_positioned_paragraphs` + `_bbox_iou`（位置對齊、IoU 配對、可靠性閘擋亂碼）；`parser_service.parse_image_pdf_via_mineru_ocr`（MinerU `parse_method=ocr`）。測試見 `tests/test_image_text_recall.py`（5 例：IoU、找回新增條款、數字變更、擋 `[PAYV` 亂碼、同位同字不報）。
  - 整合：`generate_diff_report` 影像路徑在開關開啟時跑召回層；box-in-box 去重把 ADDED/DELETED 視為內容（避免被粗略視覺框吃掉）。
- 開關：`ENABLE_IMAGE_TEXT_RECALL`（`config.enable_image_text_recall`，預設 **false**）。compose 已加該 env（預設 false）。關閉時行為與改動前完全相同 → 零回歸風險。
- **尚待驗證（需容器 + MinerU 服務）**：host 無 fitz/tesseract/Docker，無法端到端驗證。請在容器內：
  1. 把 `ENABLE_IMAGE_TEXT_RECALL=true` 設到 `backend-minerU`，確認 `mineru-api-minerU` healthy。
  2. 把要測的 PDF（4 份附件樣本，或 `商品DM/美保發`、`商品DM/臻美利` 兩組 1130101→1130418）放到掃描根目錄，跑 `scripts/diagnose-pdf-samples.ps1`。
  3. 必過底線：`baoxinanxin` p2 新增條款（監護宣告）應以 ADDED 區塊出現且**無** `[PAYV` 亂碼；`fengshouai` p2 `24→28`、兩組頁尾 Version/Control No 仍須偵測；`臻美利` 不得出現假 `Version: 975.18`。
  4. 依結果調 `diff_positioned_paragraphs` 的 `iou_threshold` 與可靠性閘；確認召回未引入亂碼或重複後，才把預設開關打開。

### 容器回歸結果（2026-05-22，召回層啟用）
環境：`docker run` 接 `pdf_check_mineru_internal` 網路、`ENABLE_IMAGE_TEXT_RECALL=true`、`MINERU_API_URL=...:18080`，掛載本機改過的 repo，對 `商品DM/美保發`、`商品DM/臻美利`（皆 1130101→1130418，image_pdf=True）跑 `scripts/diagnose_pdf_samples.py`。MinerU `/health 200`、tesseract 5.5.0。

達成（召回層的價值，符合「不漏真改」目標）：
- 臻美利 p2/p3/p4 找回整段新增「註3：本商品於部分保單年度有基本保險金額對應之身故/完全失能保險金給付逐年遞減之特性…」——這是現行像素路徑會判 IMAGE_DIFF 後丟棄、審核最該看到的揭露新增。
- 兩組頁尾版本/文號變更皆正確：美保發 `2024.01/2312-2512-OP2-0300`→`2024.04/OP-2404-2604-0238`；臻美利 `…OP2-0274`→`…0234`。
- 無 `[PAYV` 類亂碼進入結果（可靠性閘有效）。

仍有的誤報（為什麼維持預設關閉的原因，待調）：
1. **OCR 標點不穩定**：同一句「宣告利率3.90%」在新舊兩份各自 OCR 後一邊讀成「3,90%」（逗點 vs 句點），被判 NUMBER_MODIFIED（臻美利 d002/d005/d007）。根因：兩份是各自獨立 OCR，標點層級雜訊不一致。
2. **區塊重切誤報**：相同內容因新舊 OCR 段落切分不同 → bbox 配不上 → 誤報 ADDED/DELETED（美保發 d003 客服電話行；臻美利 d008 公式塊）。

已實作的調整（2026-05-22 二次，`diff_positioned_paragraphs` 改為逐頁處理）：
- **降 OCR 誤報（針對「頁面其實大致相同」）**：
  - `_recall_norm`：比對前移除數字間的逗點/句點（`3.90`↔`3,90`→`390`），吸收 OCR 小數/千分位漂移 → 解 FP#1。
  - 區塊配對加「文字相似度回退」（`_BLOCK_REMATCH_RATIO=0.60`）：IoU 配不上時，用文字相似度再配一次；同文字移位 → 視為重切不報 → 解 FP#2。
- **整頁版面變更 → 全面標記（針對「整個版面真的重新設計」）**：逐頁計算文字相似度，低於 `_PAGE_REDESIGN_RATIO=0.45`（且兩側內容夠長）時，輸出**單一「整頁版面變更」綜合標記**涵蓋整頁，而非碎成大量區塊或被壓掉。
- **綜合標記保證存活**：`_drop_non_numeric_modifications` 對 context 含「整頁版面變更／整表替換」者一律保留（`_COMPREHENSIVE_MARKERS`），確保整頁重設計一定被標出。
- 單元測試：`tests/test_image_text_recall.py` 增 3 例（整頁重設計→單一標記、區塊重切不誤報、標點漂移不誤報）；後端全套件 42 passed。
- 仍維持 `ENABLE_IMAGE_TEXT_RECALL` 預設關；二次容器回歸（美保發/臻美利）確認誤報消失、真實召回（臻美利註3 新增、兩組頁尾）與無亂碼仍在後，再評估是否預設打開。

### 呈現面（2026-05-22）：已抑制視覺變更提示
- `DiffReport` 新增 `suppressed_count`（`merge_diff_results` 以可選 `stats` 參數回報被丟棄的 IMAGE_DIFF 數，`generate_diff_report` 帶入；不改變既有丟棄行為，既有測試與輔助腳本不受影響）。
- 前端 `ComparePage` 差異摘要區、`types.ts` `DiffReport.suppressed_count`：當 >0 時顯示「另偵測到 N 處視覺/排版變更未列入內容差異，請對照截圖再確認」橫幅，避免影像型 PDF「看到 0 筆」的靜默漏報感。

### 驗證迭代與相似度閘（2026-05-22 三次）
多輪容器回歸（美保發/臻美利，召回層啟用）逐步收斂誤報：
- 包含關係閘生效：美保發「客服電話新增」、臻美利「本範例數值僅供參考」等重切誤報消失；美保發收斂到 2 筆（揭露值刪除＋頁尾，皆為真）。
- 真實召回穩定保留：臻美利「註3：身故/完全失能保險金遞減特性」新增（p2/p3/p4）與兩組頁尾版本/文號變更皆在。
- **殘留誤報根因（重要）**：臻美利 p2/p3/p4 的「註1/註2」長註腳塊仍被報為內容變更。容器內合成測試證實程式碼與數字正規化皆正確；根因是**兩份各自 OCR，長註腳全文裡有位數誤讀**（同一段靜態文字，一次讀對一次讀錯），`_recall_norm` 的標點正規化修不了位數誤讀，且誤讀的數字會讓「數字有變」成立。
- **修法（三次，取代數字閘）**：matched 區塊改用**無條件相似度閘** `_NOISE_SIM=0.95`——新舊正規化後相似度 ≥0.95 即視為 OCR 不穩雜訊不報；真改（重寫的句子、短儲存格費率）相似度明顯較低仍會報。比「只看數字是否變」更穩健，且不誤殺短句真數字變更（單元測試涵蓋）。
- **已知取捨**：大型數字格網（費率/試算表）OCR 本身就讀成亂碼，召回層無法可靠偵測其中單一數值變更；這類改動由像素路徑標為 IMAGE_DIFF + `suppressed_count` 橫幅提示審核人員對照截圖人工確認。
- `ENABLE_IMAGE_TEXT_RECALL` 維持預設 **關**。相似度閘的長註腳實際效果以容器回歸最終確認後，再決定是否預設打開。
- 後端全套件 45 passed（`tests/test_image_text_recall.py` 共 10 例，涵蓋整頁重設計、重切回退、包含關係、標點漂移、相似度雜訊、真數字變更保留）。

### 決定性量測與下次待辦（2026-05-22，暫停於此）
直接在容器內以 `parse_image_pdf_via_mineru_ocr` 載入臻美利兩份、跑 `diff_positioned_paragraphs` 並印每筆相似度，確認：
- 程式碼確實是新版（`_NOISE_SIM=0.95` 在內，合成案例可正確抑制），**非 bind-mount 快取問題**。
- 殘留誤報 d002/d004/d006（「註1」長註腳）量到 **sim≈0.854–0.865**，且 **舊塊 203 字 vs 新塊 155 字**。
- **真正根因＝區塊重切（matched 但長度差很多）**：MinerU 把同一段註1/註2 在新舊 PDF 切成不同邊界 → 相似度落在 0.86，低於 0.95 雜訊閘所以沒被擋；3.90/3,90＋位數/括號漂移讓它看似 NUMBER_MODIFIED。先前「位數誤讀」的推測不完整，主因是重切。
- ✅ 真實價值仍正確：臻美利「註3」新增（p2/p3/p4，ADDED）、兩組頁尾、美保發收斂到 2 筆皆為真。

下次待辦（擇一）：
1. 對 **matched 配對也套包含關係閘**：若一邊文字大致包含於另一邊（重切）且無顯著數字差 → 視為重切不報。最小改動、直接命中本案。
2. 召回層**只留 ADDED/DELETED + 整頁綜合標記**，移除 matched 區塊「內容變更」路徑（長註腳/數字格網本就不可靠，footer 由像素路徑負責）。
3. 比對前**先把同頁區塊合併**再做 diff，消除重切造成的長度差。
- 在 1/2/3 任一完成並通過容器回歸（誤報清掉、註3＋頁尾仍在）前，`ENABLE_IMAGE_TEXT_RECALL` 維持預設 **關**。

### 實作：matched 配對包含關係閘（2026-05-24，採方案 1）
針對上述「區塊重切」殘留誤報，在 `_recall_block_item`（matched 配對路徑）於 `_NOISE_SIM` 閘之後加一道**重切閘**：
- 取兩塊正規化文字的**較短/較長**邊，若 `_containment(shorter, longer) >= _CONTAINMENT_SUPPRESS`（0.85，與 ADD/DEL 路徑同一常數）→ 短邊大致是長邊的子集，屬 MinerU 在新舊掃描把同段註腳切在不同邊界。
- **且** `_recall_digits(on) == _recall_digits(nn)`：以 `_recall_norm` 已去分隔符的字串抽 `\d+` 比對位數多重集（`3.90`/`3,90`→`390` 視為相同）→ 無真實數字變更時才視為重切丟棄；任一位數真的變了（`3.90`→`4.20`）digits 不等 → 仍照報。
- 新增 helper `_recall_digits`（分隔符容忍的位數抽取，置於 `_recall_norm` 旁）。
- 量測本案合成例：sim≈0.667（< 0.95，會進新閘）、containment=1.0（≥0.85）、digits 相等 → 正確抑制；數字真變版本（4.20%）digits 不等 → 仍報 NUMBER_MODIFIED。
- 取捨：matched 區塊「純改字、無數字變更」也會被此閘吃掉，但這類本就由下游 `_drop_non_numeric_modifications` 丟棄，無淨損失；真正新增的整段條款走 ADDED 路徑（不經此閘）仍會被召回。
- 單元測試：`tests/test_image_text_recall.py` 新增 2 例（重切長註腳對→抑制、重切但真數字變更→保留）；後端全套件 **47 passed**（host 無 fitz/tesseract，僅跑純邏輯）。
- **尚待容器回歸確認**才預設打開：必過底線不變 — 臻美利 d002/d004/d006 長註腳誤報消失、「註3」新增（p2/p3/p4 ADDED）與兩組頁尾版本/文號仍在、美保發仍收斂到 2 筆真改、無 `[PAYV` 亂碼。通過後再把 `ENABLE_IMAGE_TEXT_RECALL` 預設改 **true**；在此之前維持預設 **關**。

- **完整護欄**：見 `docs/pdf_diff_guardrails.md`。未來修改 PDF diff/OCR/部署前，必須先看該文件。
