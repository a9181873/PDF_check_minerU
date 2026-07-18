# PDF Check MinerU 工程歷程與決策紀錄

> 最後整理：2026-07-19
> 本文件是 PDF／OCR／MinerU／OCI／準度與效能修改歷程的唯一敘事入口。其他日期型文件與 benchmark 原始檔仍保留作為證據，但若對「目前狀態」說法不同，以本文件、實際執行中的部署稽核與對應 commit 為準。

## 1. 閱讀方式

本文件使用四種狀態：

| 狀態 | 定義 |
|---|---|
| **現行** | 已進入 Git 正式基線，且未被後續設計取代。是否已在 OCI 執行，需再看部署欄位。 |
| **已取代** | 曾經有效或用來止血，但後續架構、門檻或流程已更換。只保留作根因追查。 |
| **實驗** | 可選功能或 A/B 路徑，不直接作正式差異來源。 |
| **待驗證** | 已在本機工作樹實作或規劃，但尚未完成正式映像、OCI 部署或同版正式多輪驗收。 |

判讀來源的優先順序如下：

1. 實際執行中的 OCI／本機容器稽核。
2. 指定 commit 的程式碼與設定。
3. 有原始 JSON 的固定條件 benchmark。
4. 本文件的里程碑摘要。
5. 舊日期型文件、交接筆記與一次性診斷紀錄。

「召回 100%」只表示固定回歸錨點全數命中，不代表所有保險商品 EDM 的母體準確率。沒有完整 item-level 人工真值前，不得延伸宣稱 precision、recall、F1 或零漏報。

## 2. 2026-07-19 基線快照

### 2.1 本機 Git 與工作樹

| 項目 | 狀態 | 說明 |
|---|---|---|
| 分支／Git HEAD | **現行** | `main@0d3c0e8`；此 commit 是 2026-07-05 文件與 OCI 漸進式分析紀錄基線。 |
| 本輪最佳化 | **待驗證** | `pixel-v7`、連通元件向量化、不可變 raster bytes 雙路 OCR、全頁圖片 metadata 快篩、數字語意閘門、process-wide PyMuPDF 鎖、runtime 指紋與 Golden 語意負例均在尚未提交的本機工作樹；本機正式五輪已通過，尚未做 OCI 同版驗收。 |
| 使用者新增樣本 | **待驗證** | 心動溢生 `1140121 → 1140815` 與金放心85 `1120701 → 1140825` 已完成鎖後 cold／warm smoke，但尚未形成正式版本化 Golden v2。 |
| OCI 部署 | **未執行** | 本輪程式碼與 MinerU CPU final 尚未部署到 OCI。 |

### 2.2 OCI 實際狀態

| 項目 | 已部署／稽核結果 | 判讀 |
|---|---|---|
| 主機 | Ampere A1，4 OCPU／24GB RAM；磁碟約 193GB，86GB 已用、107GB 可用；稽核時 uptime 約 99 天 | 容器均健康，未發現 restart、OOM 或主機資源耗盡。 |
| Backend | 已部署 `b875a9b`；`torch 2.12.1+cpu`、CUDA 不可用，image API `.Size` 約 764MB、展開磁碟占用約 3.17GB | **現行已部署**。7/5 鳳守愛單案例 smoke 已通過。 |
| MinerU | MinerU 3.4.0；實際仍為 `torch 2.12.1+cu130`，含 18 個 CUDA／NVIDIA 套件，image 約 5.414GB；主機沒有 GPU | **現行但待修**。實際以 CPU 執行，CUDA 套件只造成映像、建置與磁碟浪費。 |
| 本輪 MinerU CPU 映像 | Dockerfile 與 CPU constraints 已在本機工作樹調整 | **待驗證**。尚待包含模型下載層的完整 `final` build 驗證，亦尚未部署。 |
| 比對資料 | 34 組上傳配對／300 頁；依 SHA 去重後約 13 組獨立配對、23 份 PDF／91 頁；其中 14 份無文字層、9 份有原生文字層 | 歷史資料有代表性，但重複案件多，不能直接當 34 組獨立樣本。 |
| 審核標註 | 27 份報告、201 個 diff item，僅 13 次 review action；可對齊標籤約 10 筆、約占 5%，只有 3 案完整審核 | 標註密度不足，不能由 OCI 歷史資料計算可靠的母體 precision／recall。 |
| 實際工作負載 | 33 筆 resource log：完成時間 P50 27.4 秒、P95 133.4 秒、最大 225.8 秒；RSS P50 631MB、P95 3.231GB、最大 3.384GB | 長尾主要來自像素分析與 OCR。這是混合工作負載分布，不是固定樣本 benchmark。 |

OCI 另有 1 筆長時間停在 `diffing` 的舊紀錄，以及 6 組上傳檔沒有對應 DB row；這些屬資料治理問題，不應混入演算法準度統計。

部署拓樸稽核另發現：MinerU API 的執行期併發上限為 3，但 backend 完整比對上限為 1；兩者在 CPU-only 主機上不一致。PDF 服務也與數個不相關容器共用通用 `internal` 網路，MinerU 沒有自己的驗證層，容器普遍未設 resource limit／log rotation。雲端入口目前擋住 backend 動態 host port，沒有直接曝露事件，但仍應改成 PDF 專用私有網路與最小暴露面。

## 3. 工程里程碑

### 3.1 2026-04：定位與座標基礎

| 日期 | Commit | 狀態 | 決策與影響 |
|---|---|---|---|
| 04-13 | `25d25d9`、`79cd358`、`675c01a` | **現行原則** | 表格由整表大框改為 cell bbox、字元級差異與左右頁精準高亮。後續演算法雖已重構，「差異必須落在可審核位置」仍是核心原則。 |
| 04-17 | `78c1f78` | **現行原則** | 建立文字層 PDF 與 image-only PDF 的核心分流，並補 Mac 支援與 UI 清理。 |
| 04-24 | `6c79347`、`7f4a4ce`、`efb6d7a`、`7a15917` | **部分現行** | 加入 pHash、shift-invariant NCC、區域 OCR、格線降噪與 recompare API。`cc16691` 曾做第一次文件整併，但後續歷程再次分散。 |

這一階段留下的有效經驗是：原生文字、視覺相似度與 bbox 必須交叉驗證，不能只靠單一路徑。

### 3.2 2026-05：MinerU、召回與過度降噪回歸

| 日期 | Commit | 狀態 | 問題、決策與驗證 |
|---|---|---|---|
| 05-04～05-08 | `cc25b80`、`db3334a`、`5e79bbc` | **部分現行** | 導入 MinerU cell-level 表格、並行解析、動態 DPI、Sliding Window、SSIM 子區域與 Tesseract ROI OCR。當時「兩個重型 parser 預設競速」後來被循序路由取代。 |
| 05-16 | `fc21cab` | **現行** | 加入案號、封存與審核修改歷程；同一 PDF 不同案號可分案留存。 |
| 05-19 | `fa358c6` | **已取代** | 為減少巨型標記而縮小 component／merge 行為，造成 image-only EDM 頁尾 Control No 漏抓。問題區實測有 2,162 個 changed pixels，最大 component 1,086 px，證明是過濾回歸而非沒有差異。 |
| 05-20 | `f23c2ba` | **現行護欄** | 恢復 broad visual scan，加入 protected header/footer OCR，保留 Version／Control No，並阻止 `[PAYV` 類亂碼進入一般文字差異。 |
| 05-21 | `c60ae99` | **已取代** | 以丟棄全部 `IMAGE_DIFF` 與非數字終端過濾換取降噪，結果使大段條款與密集表格真變更靜默消失。這是「先看到、後刪掉」的重要失敗案例。 |
| 05-22～05-25 | `c22e7f7`、`d3118f1`、`69f1c1f`、`186de7c` | **實驗／部分沿用** | 建立 MinerU image-text recall，依序處理標點漂移、重切、跨頁重配、digit-master 回歸，最後改以 `_aligned_length` 抑制重切噪音。五樣本曾在 recall ON 下收斂，但正式預設仍維持 OFF。 |
| 05-25 | `533c139`、`ca717f8`、`be513ce` | **現行** | 修正左右 bbox 混用、image-PDF 70% 門檻取整、review lost-update、未授權 `/uploads`、flagged 統計與跨視窗同步。OCI 正式分支自此統一追蹤 `main`。 |
| 05-25～05-27 | `9ec5544`、`9f6ca22`、`3cc95dd`、`1ea8166` | **現行原則／實驗路徑** | image-only 保留 visual fallback；新增 alignment recall 與視覺／OCR 融合。OCR 被定位為視覺證據的解釋層，而非真值來源。 |

這段歷程證明：在影像型保險 EDM 上，單純增加 OCR 規則會出現「修一組、破一組」。可靠方向是保留可見區域，再用高信心文字補充說明。

### 3.3 2026-06：混合召回、數字閘門與效能止血

| 日期 | Commit | 狀態 | 決策與驗證 |
|---|---|---|---|
| 06-12 | `a9c8f37`、`b7360a4` | **實驗** | 加入 cached hybrid recall，整合 alignment 與 heuristic；仍需人工以 PDF 畫面判斷，不能只比較候選筆數。 |
| 06-13 | `57bd147`、`c785aaa` | **實驗／部分現行** | PaddleOCR 接成 metadata-only A/B；old/new 解析並行、報告可先使用，snapshot/crop 延後處理，並加入 pipeline timing。 |
| 06-14 | `572f68a`、`620eb94` | **現行但已加強** | 為鳳守愛 `24→28` 建立 compact numeric fallback，並將 OCR reliability gate 套到 `NUMBER_MODIFIED`、排除單一位數與髒字元。2026-07-19 再補上等位數、前導零片段與語意負例閘門。 |
| 06-15 | `1030781` | **現行** | image-only 的大表格／版面 visual evidence 不再一律丟棄，並加入 OCR candidate 分類與每頁 budget。新扶愛約 62→31 秒，美利保約 35→25 秒；這是止血，不是逐格表格 OCR 完成。 |
| 06-28 | `6863872`、`6ffd8dd` | **現行** | 比對流程抽成 job runner／orchestrator，加入有限佇列、重型 parser semaphore、PyMuPDF 表格快篩、`docling_first → MinerU fallback`、SHA-256 parser cache 與 single-flight。六組／12 份 PDF／60 個輸入頁完成 Docker 回歸，後端 120 tests。 |

06-28 forced-OCR A/B 共 698 段；模型載入後的 54 個輸入頁耗時 345.44 秒，約 6.40 秒／頁、9.38 頁／分鐘。這個數字沒有完整 cold start、phase timing、CPU/RSS，也沒有 item-level 真值，只能作當時 OCR 吞吐觀察。

### 3.4 2026-07-05：漸進分析與版本化回歸

`b875a9b` 建立下列正式能力，`0d3c0e8` 補齊部署與文件紀錄：

- `preliminary_result → result_updated → complete` 漸進式分析。
- `content` 與 `needs_visual_review` 雙軌審核；確定有實質變更但 OCR 不可靠時仍保留 bbox 與裁切證據。
- 穩定 `candidate_id`、風險、決策原因、證據與 runtime/model 資訊。
- 144 DPI 初步候選、200 DPI 完整補強與頁首／頁尾保護 OCR。
- `TableArtifact` 與 page、bbox IoU、列欄結構、表頭簽章配對。
- 像素分析跨重啟磁碟快取。
- 封存前要求分析完成，且高風險與待人工區域均已審核。
- 六對商品 DM Golden v1 與跨主機 benchmark runner。
- Backend CPU-only Torch 與供應鏈版本約束；這項修正當時只完整落在 backend，不能推論 MinerU image 也已 CPU-only。

當時正式驗證為後端 127 tests、前端 production build；Mac 原生與 Mac Docker 的 cold／warm 各完成 30 runs。OCI 僅跑鳳守愛單案例 smoke，未完成同版全六組正式多輪。

### 3.5 2026-07-19：`pixel-v7` 本機最佳化

本輪仍屬 **待驗證／未部署**，重點如下：

- 將 connected-component 幾何統計改為 `numpy.bincount`＋`scipy.ndimage.find_objects`，移除每個 label 重掃全頁像素的 `O(K × page_pixels)` 熱點。
- 同一 ROI 先在呼叫端循序完成 PyMuPDF render 並轉成不可變 raster bytes，再把舊版／新版 Tesseract OCR 以兩路並行執行；MinerU 服務併發則收斂為 1，避免 CPU-only 主機過度競爭。
- `diff_images()` 先讀 PyMuPDF image placement metadata；全頁背景圖不再解碼後才做 pHash。
- compact numeric 必須通過語意條件；不可靠的局部數字 OCR 不再硬解讀為 `NUMBER_MODIFIED`，改保留成 visual review。
- Golden runner 改為一個 diff item 只能滿足一個 must-detect 錨點，新增 bbox coverage、diff type 與 `must_not_interpret` 語意負例。
- 像素快取鍵加入 PyMuPDF、Tesseract、traineddata 與演算法版本指紋；runtime/model manifest 另記錄 Poppler，避免不相關版本變動誤殺像素快取，也避免真正相關版本改變後誤用舊結果。
- 新增 process-wide `RLock`，涵蓋 parser、pixel/image diff、Paddle 實驗、snapshot/crop 與 PDF export 的完整 PyMuPDF 物件生命週期；thread-based compare runner 在設定與執行器兩層都固定為 1。
- 本機新增 MinerU CPU constraints；runtime stage 已驗證為 `torch 2.12.1+cpu`、CUDA 套件 0。模型 volume 掛載已移除，建置與 healthcheck 會檢查 7 組模型；完整 final image 因 ModelScope 下載降至約 100 KB/s 而中止，仍待正式 build 與 pipeline smoke。
- Docker build context 已排除 `商品DM`、`samples`、`backend/output`、所有 PDF 與暫存渲染，避免保險文件進入映像建置內容；最終 backend image 已實測不含 PDF。

本輪驗證為 backend 148 tests、frontend production build、backend image build、MinerU CPU runtime build 與 `docker compose config` 全數通過；完整 MinerU final image 不在通過清單內。

## 4. 仍有效的準度護欄

1. **先判斷 PDF 結構**：native-text、image-only、mixed text/image 不得走完全相同的辨識路徑。
2. **影像型 PDF 採 broad-to-fine**：先找變更頁與區域，再局部 OCR；不得把全頁 OCR 恢復成主流程。
3. **視覺證據不可靜默消失**：大表格、版面或 OCR 無法可靠解讀的實質變更，至少要留在 `needs_visual_review`。
4. **頁首／頁尾是保護區**：Version、Control No、文號等高價值欄位不得被一般 component、NCC 或 OCR budget 先行抑制。
5. **數字必須是完整語意，不是 OCR 碎片**：單一位數、不等位數、裸前導零片段、長段低可信 OCR 不能直接升成正式數字變更。
6. **OCR 是解釋層**：bbox／crop 告訴 reviewer 在哪裡看；OCR 只有可靠時才說明改了什麼。
7. **左右座標不可 fallback 混用**：ADDED 只畫新版、DELETED 只畫舊版；MODIFIED／visual item 各自使用正確側 bbox。
8. **固定回歸要同時看正負條件**：必抓、必禁誤報、語意誤讀、頁碼、bbox coverage 與候選量都要記錄，不能只看 `total_diffs`。
9. **人工審核不得被背景更新覆寫**：背景補強以穩定 candidate ID 合併，並保留 reviewer 狀態。
10. **PyMuPDF 必須全程序序列化**：不只 old/new parser；匯出、封存、即時裁切與背景產物也共用同一把可重入鎖。OCR 只能在脫離 PyMuPDF 物件後，以不可變 bytes 並行。

## 5. 準度證據成熟度

### 5.1 Golden v1 的能力邊界

歷史 Golden v1 有 6 對商品 DM、30 個配對頁面與 16 個人工錨點，主要驗證：

- 鳳守愛 `24→28` 與 footer。
- 慈愛微型內容區與 footer，排除單一位數序號噪音。
- 新扶愛四頁主要表格／版面區域，排除電話、標點與同數字重排。
- 美保發主要內容區與 footer。
- 美利保主要表格區與 footer。
- 臻美利註解／版面區與 footer。

這些錨點多為頁級或區域級條件，不是完整逐筆 ground truth。2026-07-19 前的 runner 也允許一個 item 同時滿足多個錨點；新 runner 已改為一對一配對，並補上語意負例。

### 5.2 `pixel-v7` 本機正式驗證

| 測試集 | 規模 | 執行條件 | Initial P95 | Complete P95 | 人工錨點 | 錯誤數字解讀 |
|---|---|---|---:|---:|---:|---:|
| 歷史 Golden | 6 對／30 個 page pairs／60 個 input pages | cold、每案例 repeat 5，共 30 runs | 7.0993 秒 | 29.8284 秒 | 16／16 | 0 |
| 使用者新增兩對 | 2 對／10 個 page pairs／20 個 input pages | cold、每案例 1 run，共 2 runs | 7.1539 秒 | 30.5046 秒 | 7／7 | 0 |

新增兩對為：

- 心動溢生醫療定期健康保險 `1140121 → 1140815`。
- 金放心85長期照顧定期健康保險 `1120701 → 1140825`。

歷史 Golden 正式五輪另有 warm 30 runs：Initial P95 0.0139 秒、Complete P95 0.0378 秒；cold Complete mean 18.6409 秒、峰值 RSS 1,243.6MB。相較 2026-07-05 同一台 Mac M4 原生 `pixel-v4` 正式五輪，cold Initial P95 由 7.4144 降至 7.0993 秒（降低 4.25%），Complete P95 由 38.4532 降至 29.8284 秒（降低 22.43%），Complete mean 由 21.7451 降至 18.6409 秒（降低 14.28%）。

這次驗證可證明 `pixel-v7` 在 8 對固定文件上守住 23／23 個人工錨點，且命中的 `must_not_interpret` 錯誤數字解讀為 0。它仍然**不是母體 precision／recall／F1**，原因包括：

- 樣本只有 8 對，且集中於台灣人壽商品 DM。
- 多數錨點是頁級／區域級，不是完整 item-level 標註。
- 未逐一標註所有正確差異、所有誤報與 bbox 真值。
- 使用者新增兩對仍只有每案例 1 次，該列 P95 是小樣本 smoke 指標，不是容量規劃數字。

正式準度結論仍需 Golden v2：至少 30 對、每個差異具 type、page、old/new bbox、舊新值、可接受 visual-only 標記，以及完整 must-not-detect／must-not-interpret 真值。

## 6. 效能基準演進

不同時期的量測方法不同，以下只保留可追溯數字，不做不公平的倍數結論。

| 日期／環境 | 方法 | Initial | Complete／總時間 | 備註 |
|---|---|---:|---:|---|
| 2026-06-15 Mac Docker | 單案例工程回歸 | — | 新扶愛約 31.1 秒；美利保約 24.8 秒 | OCR budget 止血後；先前約 62／35 秒。 |
| 2026-06-28 Docker | MinerU forced-OCR A/B | — | 模型載入後 54 個輸入頁 345.44 秒 | 約 6.40 秒／頁；不是完整 compare SLA。 |
| 2026-07-05 Mac M4 原生 | `pixel-v4` 正式五輪 | cold P95 7.41 秒；warm 0.014 秒 | cold P95 38.45 秒；warm 2.09 秒 | 每模式 30 runs。 |
| 2026-07-05 Mac M4 Docker 10 vCPU／8GB | 正式映像五輪 | cold P95 10.13 秒；warm 0.020 秒 | cold P95 56.04 秒；warm 2.62 秒 | 每模式 30 runs；無 OOM。 |
| 2026-07-05 OCI A1 | 鳳守愛單案例 smoke | cold 4.74 秒；warm 0.011 秒 | cold 18.62 秒；warm 3.77 秒 | 只有 1 run，不是 P95。 |
| 2026-07-19 Mac M4 原生 | `pixel-v7`＋process-wide lock 正式五輪 | cold P95 7.0993 秒；warm 0.0139 秒 | cold P95 29.8284 秒；warm 0.0378 秒 | 每模式 30 runs；16／16 錨點、數字誤讀 0。 |
| 2026-07-19 Mac M4 原生 | `pixel-v7` 使用者兩對 cold smoke | P95 7.1539 秒 | P95 30.5046 秒 | 2 runs；7／7 錨點、數字誤讀 0。 |

本輪熱點分析另確認：密集頁面的 connected-component 幾何掃描是主要可消除成本；兩側 OCR 並行與全頁圖片 metadata prefilter 則分別降低 Tesseract 等待與不必要的 image decode。Mac 原生同方法正式數據已完成；跨環境結論仍須在固定 Docker image 與 OCI 上重跑 cold／warm 多輪。

## 7. OCI 與部署歷程

| 日期 | 狀態 | 事件與決策 |
|---|---|---|
| 2026-05-25 | **現行流程起點** | OCI 從孤立舊 `master` 校正為追蹤 `main`；只重建 `backend-minerU`，保留資料卷與 MinerU。OCI compose 有動態 host port 與既有 external network 客製，不可直接被本機 compose 覆蓋。 |
| 2026-06-28 | **歷史基線** | MinerU 3.4.0／six 1.17.0 健康；同時確認 ARM64 未鎖 transitive dependency 會下載大型 CUDA wheel。 |
| 2026-07-05 | **已部署** | `b875a9b` backend CPU-only image 部署；backend API `.Size` 約 764MB、展開磁碟占用約 3.17GB，鳳守愛 smoke 通過。此結果只證明 backend，不代表 MinerU image 已 CPU-only。 |
| 2026-07-19 | **稽核結果** | OCI backend 仍健康；MinerU 實際為 `+cu130`、18 個 CUDA／NVIDIA 套件、約 5.414GB。33 筆實際任務顯示 P95 133.4 秒與 RSS P95 3.231GB，需優先處理 OCR 長尾與映像浪費。 |
| 2026-07-19 本輪 | **待驗證／未部署** | MinerU CPU runtime 已建置驗證：510,546,376 bytes、84 個依賴 pin 全數吻合、`torch 2.12.1+cpu`、CUDA 不可用、CUDA/NVIDIA 套件 0；舊 `mineru-api:pipeline` 為 5,414,027,692 bytes，runtime 部分縮小 90.6%。完整 final 的模型下載受外部頻寬阻擋，不能用 runtime 大小推稱最終映像大小；尚待 final build、7 模型 gate、真實 pipeline smoke 與維護時段部署。 |

部署前後必須把 backend 與 MinerU 分開驗證：

- `torch.__version__`、`torch.version.cuda` 與 CUDA/NVIDIA package count。
- 各自 image API size 與實際展開磁碟占用。
- `/health` 之外，至少送一份真實 `/file_parse`，避免只有 API 健康但 pipeline 缺相依套件。
- `verify_models.py` 必須確認 `mineru.json` 與 7 組 pipeline 模型；模型不可再被既有 `/root/.cache/modelscope` volume 遮蔽。
- 固定 Golden cold／warm benchmark、容器 RSS、restart／OOM 與分析 cache 命中。
- OCI 反向代理網路、動態 port 與資料卷不能因套用本機 compose 而改壞。

## 8. 現行、實驗與待辦矩陣

| 項目 | 狀態 | 說明 |
|---|---|---|
| PyMuPDF 快篩 → Docling → MinerU fallback | **現行** | `TABLE_PARSER_STRATEGY=docling_first`；舊 `parallel_race` 只供回歸 A/B。 |
| `content`／`needs_visual_review` 雙軌 | **現行** | OCI `b875a9b` 已部署。 |
| Image text recall | **實驗** | 預設 `false`；alignment／heuristic／hybrid 可做 A/B。 |
| PaddleOCR／PP-StructureV3 | **實驗** | 預設關閉，只處理 ROI metadata，不直接產生正式 diff。 |
| VLM | **實驗／未部署** | 需先證明可解決至少 30% 待判讀區域、額外誤報不超過 5%，且 Complete P95 不超過 90 秒。 |
| `pixel-v7` 與語意數字閘門 | **待驗證** | 本機正式五輪與使用者兩對 smoke 通過；尚未提交、容器正式五輪或 OCI 同版部署。 |
| MinerU 純 CPU final image | **待驗證** | CPU runtime 與 7 模型 gate 已驗證；完整模型層 build 因外部下載過慢中止，最終容量、真實 pipeline 與 OCI 回歸尚未完成。 |
| MinerU 供應鏈可重現性 | **待處理** | Python 84 個 pin 已固定；ModelScope 仍取 `master`，APT 套件與模型 snapshot／內容 digest 尚未固定。 |
| Golden v2 | **待建立** | 需擴充至少 30 對並完成 item-level、bbox 與負例真值。 |
| OCI 同版正式 benchmark | **待執行** | 應使用隔離 `DATA_DIR`，避免 cold 測試清除正式 persistent cache。 |
| OCI 資料治理 | **待處理** | 清查 stale comparison、無 DB row uploads、重複 SHA pair 與 review label 匯出。 |
| OCI 網路與容器強化 | **待處理** | MinerU 應置於 PDF 專用私有網路；補 resource limits、log rotation，並避免不必要的 host exposure。 |

## 9. 已取代或容易誤讀的說法

| 舊說法 | 現行判讀 |
|---|---|
| MinerU 與 Docling 預設並行，誰先完成採誰 | 2026-06-27 起改為 PyMuPDF 快篩、`docling_first`、必要時 MinerU fallback；並行只做 A/B。 |
| 所有純 `IMAGE_DIFF` 都不進正式清單 | 已取代。實質 visual evidence 進 `needs_visual_review`，只有 rendering noise 可降噪。 |
| 四路聯集即可做到「零漏報」 | 不具統計依據。只能說固定 Golden 錨點是否全數命中。 |
| 所有 cache 都在程序內，重啟即失效 | parser cache 仍是程序內；像素分析自 7/5 起已有跨重啟 persistent cache。 |
| `TableArtifact` 與結構配對尚未完成 | 7/5 已完成基本 artifact 與 page／bbox／結構配對；密集表格逐格可靠 OCR 仍未完成。 |
| OCI 已是完整 CPU-only 映像 | 只有 backend 已確認 CPU-only；MinerU 在 7/19 稽核時仍為 `+cu130`。 |
| `summary.flagged` 固定為 0 | `533c139` 已修正；舊開發手冊描述已過時。 |
| OCI 鳳守愛數字是 P95 | 只有單次 smoke，不能稱為 P95。 |

## 10. Evidence index

### 現行架構與護欄

- [README](../README.md)：使用者入口與設定摘要；日期型效能數字仍須回到 benchmark 原始檔。
- [技術架構](technical-architecture.md)：現行模組、資料流、部署拓樸與 2026-07-05 架構基線。
- [PDF Diff Guardrails](pdf_diff_guardrails.md)：頁首／頁尾、OCR reliability、compact numeric 與 OCI 部署護欄。
- [效能量測方法](performance-benchmark.md)：parser、resource logs、forced-OCR A/B 的量測分工。
- [召回回歸 Runbook](recall-regression-runbook.md)：歷史 Windows／Docker 真實 OCR 回歸流程；環境版本描述需視為日期快照。

### 歷史診斷與決策證據

- [2026-05-19 Handoff](handoff_2026-05-19.md) 與 [Diagnosis](pdf_diff_diagnosis_2026-05-19.md)：同一頁尾漏抓事件的交接與像素證據。
- [歷史問題 Archive](historical_issues.md)：05-20～05-25 的詳細迭代、ground truth、召回回歸與安全稽核；不是目前狀態來源。
- [2026-05-25 Regression Audit](pdf_diff_regression_audit_2026-05-25.md)：`c60ae99` 過度降噪根因與 alignment 決策。
- [2026-05-26 OCR A/B](image_text_recall_strategy_ab_2026-05-26.md)：八對 EDM 的 PDF-first review、alignment／heuristic 比較與三路證據融合原則。
- [2026-06-14 Recent Summary](pdf_diff_recent_summary_2026-06-14.md)：compact number 修正與六組樣本護欄；其中純 `IMAGE_DIFF` 說法已被 6/15、7/5 取代。
- [2026-06-15 Architecture Review](pdf_diff_architecture_review_2026-06-15.md)：大表格 visual fallback、OCR budget 與當時的效能止血結果。
- [2026-06-28 Technical Status](technical-usage-status_2026-06-28.md) 與 [Full PDF Regression](full_pdf_regression_2026-06-28.md)：parser 路由重構與 forced-OCR 六組回歸快照。
- [2026-07-04/05 Optimization Record](ocr_optimization_implementation_2026-07-04.md)：`b875a9b` 漸進分析、Golden v1 與 backend CPU-only 紀錄。
- [OCI 2026-06-15 備份與縮規格筆記](oci_free_tier_backup_resize_2026-06-15.md)：日期型維運證據；免費額度具時效性，使用前需重新查證官方資料。

### Benchmark 原始證據

- [Mac／OCI 比較摘要](../benchmarks/results/mac_vs_oci_20260704.md)：不同環境結果與方法限制。
- [Mac M4 原生正式五輪 JSON](../benchmarks/results/macbook_air_m4_formal_20260705.json)。
- [`pixel-v7`＋process-wide lock 正式五輪 JSON](../benchmarks/results/macbook_air_m4_pixel_v7_formal_20260719.json)。
- [Mac M4 Docker 正式五輪 JSON](../benchmarks/results/macbook_air_m4_docker_formal_20260705.json)。
- [OCI 鳳守愛 smoke JSON](../benchmarks/results/oci_b875a9b_fengshouai_smoke_20260705.json)。
- [Golden v1 manifest](../benchmarks/golden/v1/manifest.json)：六對既有回歸條件；2026-07-19 工作樹已加入語意負例，但尚未形成新版本 commit。

舊文件不刪除，因為它們保存了當時的問題、環境與驗證證據；但它們不再各自作為「目前狀態」的權威入口。
