# PDF Diff Regression Audit - 2026-05-25

分析基準：`origin/main@d41c896`。

本機工作目錄在分析開始時停在 `main@b2fab1a`，落後 `origin/main` 18 個 commit。曾嘗試快轉本機分支，但沙盒不允許寫入 `.git/ORIG_HEAD.lock`，因此本文件以遠端快照與只讀 commit 檢視為準。

## Executive Summary

四月中旬以來的退化主因不是單一 OCR bug，而是降噪策略一路加強後，把真差異也納入「不要顯示」的範圍。

最可疑斷點是 `c60ae99`：它開始在合併後丟棄所有 `IMAGE_DIFF`，並加入最終非數字過濾。影像型 PDF 的大段文字變更常先被 pixel path 判成 `IMAGE_DIFF`；如果 `ENABLE_IMAGE_TEXT_RECALL=false`，這些變更沒有文字召回路徑，最後只剩 `suppressed_count` 提醒或直接從差異清單消失。

5/22 後新增的 MinerU OCR recall layer 方向正確，但仍是多層 heuristic 網路。它已被多次修補以處理 OCR 標點漂移、區塊重切、跨頁重切、長度不匹配、公式亂碼等情境。這些修補對個別樣本有效，但形成高度耦合的閘門網路，改一個條件就可能讓另一組樣本回歸。

## Evidence

### 1. `c60ae99` changed the failure mode from noisy to missing

`c60ae99` 在 `merge_diff_results` 後加入：

- drop all `DiffType.IMAGE_DIFF`
- final `_drop_non_numeric_modifications`

效果是：純視覺差異即使代表真實內容變更，也不再列入結果；純文字修改若沒有數字，也會被丟掉。這解釋「以前看得到框，後來清單不見」。

在 `origin/main@d41c896`，這個設計仍保留：

- `merge_diff_results` 計數 `suppressed_visual` 後移除 `IMAGE_DIFF`
- `_drop_non_numeric_modifications` 只保留 ADDED / DELETED / numbers changed / comprehensive markers

### 2. Recall layer exists, but production default is still off

`ENABLE_IMAGE_TEXT_RECALL=false` 是目前預設。關閉時，影像型 PDF 仍主要依賴 pixel path；大面積文字或表格內容變更若被歸入 `IMAGE_DIFF`，會被合併層移除。

因此，如果使用者在正式環境看到「原本可以辨識，後來不行」，不一定是 `diff_positioned_paragraphs` 修壞；可能是根本沒有開 recall layer。

### 3. Current recall layer is a heuristic network

`diff_positioned_paragraphs` 目前核心元件：

- `_PAGE_REDESIGN_RATIO = 0.45`
- `_BLOCK_REMATCH_RATIO = 0.60`
- `_CONTAINMENT_SUPPRESS = 0.85`
- `_ALIGNED_LEN_RATIO = 0.90`
- `_recall_norm`
- `_recall_digits`
- `_digits_covered`
- `_aligned_length`
- `_containment`
- `_reconcile_leftover_blocks`
- `_MATH_FORMULA_NOISE_RE`
- `_is_reliable_ocr_text`

這些元件都各自合理，但彼此形成複合決策。5/22 到 5/25 的歷史顯示同一模式反覆出現：修美鑫傳家會破臻美利；修臻美利又可能漏新保安心短文號；最後用 `_aligned_length` 才暫時在 5 樣本上收斂。

### 4. Architecture amplifies regressions

`diff_service.py` 從 4/17 的約 538 行成長到 5/25 的 2143 行。文字 diff、表格 diff、像素 diff、嵌入圖片 diff、OCR、SSIM、合併、去重、最終過濾、報告產生都在同一檔。

門檻值散落在流程中，且跨路徑互相影響。這使得局部調參很難只影響一個 failure mode。

## High-Risk Timeline

| Date | Commit | Risk |
|---|---|---|
| 2026-04-17 | `78c1f78` | 建立文字層 vs image-only pixel path 的核心路由。 |
| 2026-04-24 | `9067324` - `7a15917` | 大量像素/OCR 降噪，開始偏向 suppress。 |
| 2026-05-04 | `cc25b80` | 導入 MinerU 表格；早期 bbox 0-1000 正規化假設錯誤，表格聚合風險上升。 |
| 2026-05-04 | `454319e`, `db3334a` | 鄰近合併、72 DPI quick scan、parser first-completed，可能造成小變更漏入完整分析。 |
| 2026-05-08 | `5e79bbc` | SSIM/Tesseract 補強，但 NCC/大小閾值開始更複雜。 |
| 2026-05-19 | `fa358c6` | dilation 與 merge gap 變小，文件已確認造成 footer Control No/version 漏抓。 |
| 2026-05-20 | `f23c2ba` | 修復 footer priority OCR，是已知較穩定節點。 |
| 2026-05-21 | `c60ae99` | 最高嫌疑：丟 `IMAGE_DIFF` + 非數字最終過濾。 |
| 2026-05-22 | `c22e7f7` | 新增 image text recall，但預設關閉。 |
| 2026-05-24 | `69f1c1f` | digit-master 修美鑫，破臻美利長註腳。 |
| 2026-05-25 | `186de7c` | `_aligned_length` 取代 digit-master，5 樣本 recall ON 回歸全過。 |
| 2026-05-25 | `533c139` | 修 image-PDF 70% 門檻向下取整 bug。 |

## P0 Verification Matrix

先不要再調閾值。先跑下列 A/B，確認是哪一條路徑造成使用者看到的退化。

| Test | Revisions / Flags | Purpose | Expected Signal |
|---|---|---|---|
| A/B-1 | `f1b0f64` vs `c60ae99` | 驗證 `IMAGE_DIFF` 丟棄與非數字過濾是否是主要斷點。 | 真差異在前者有、後者消失或只進 `suppressed_count`。 |
| A/B-2 | `fa358c6` vs `f23c2ba` | 驗證 footer Control No/version 已知回歸與修復。 | `fa358c6` 漏 footer，`f23c2ba` 找回。 |
| A/B-3 | `origin/main`, recall OFF vs ON | 驗證現行預設是否仍漏影像型 OCR 文字變更。 | OFF 漏核心條款/利率；ON 召回但需檢查 FP。 |
| A/B-4 | `cc25b80` vs `c22e7f7` | 驗證 MinerU bbox 正規化與整表聚合行為。 | `c22e7f7` 後 bbox/table aggregate 較合理。 |
| A/B-5 | `186de7c` vs `69f1c1f` | 驗證 `_aligned_length` 是否真的修掉 digit-master 回歸。 | 臻美利註1 FP 消失，美鑫利率仍保留。 |

每次輸出至少記錄：

- `summary`
- `total_diffs`
- `suppressed_count`
- 每個 diff 的 `id/type/page/context/old_value/new_value`
- 是否含 `[PAYV` 類亂碼
- 必抓真差異是否出現
- 不應出現的重切誤報是否出現

## Golden Sample Set

最小固定樣本應包含：

| Sample | Purpose |
|---|---|
| 新保安心 | 短文號大幅數字變更；測 similarity gate 是否誤殺。 |
| 鳳守愛 | footer 與嵌入點陣數字；測 pixel/OCR 邊界。 |
| 美鑫傳家 | 3.90 -> 4.00、2.25 -> 2.50、祝壽金額；測 recall 真陽性。 |
| 臻美利 | 長註腳重切與公式亂碼；測 false positive。 |
| 美保發 | footer 與揭露值；測 recall 乾淨度。 |
| native-text PDF | 確保 text-layer path 不被 image-only 修法拖累。 |

每組需有人標註：

- 必須出現的真改
- 必須不得出現的誤報
- 可接受只用截圖提示的密集表格/公式變更
- 頁碼與大致 bbox 範圍

## Stopgap Recommendation

在 alignment shadow 原型完成前，若需要立刻止血：

1. 不要再新增 recall heuristic。
2. 保持 `ENABLE_IMAGE_TEXT_RECALL=false`，除非該環境已跑完固定樣本回歸。
3. 對 `IMAGE_DIFF` 的處理改產品決策：不要讓真變更只剩 `suppressed_count`。至少應能切換「保留高信號視覺差異供人工審核」。
4. 將 `suppressed_count > 0` 的任務列為需要人工截圖複核，不可視為 0 差異。

## Alignment Shadow Plan

目標不是立刻替換現行 diff，而是新增一條只輸出 trace/metrics 的旁路，讓現有 heuristic 與 alignment 結果並排比較。

### Phase 1 - `align_service.py`

新增獨立服務，不改 `diff_service.py` 正式輸出：

- input: `list[ParsedParagraph]`
- output: `AlignmentDiff` / `AlignmentTrace`
- 不依賴 bbox 做主要配對；bbox 僅用於回填定位與 tie-breaker

核心資料結構：

```python
@dataclass
class AlignmentSpan:
    text: str
    norm: str
    page: int
    bbox: BBox | None
    source_index: int
    numbers: tuple[str, ...]

@dataclass
class AlignmentDiff:
    kind: str  # added, deleted, modified
    old_text: str | None
    new_text: str | None
    old_bbox: BBox | None
    new_bbox: BBox | None
    confidence: float
    reason: str
```

### Phase 2 - Sequence Alignment

先用句/短段層級，避免全文字元級 O(n^2)：

1. 依頁面與閱讀順序排序 OCR paragraphs。
2. 將文字切成 CJK punctuation / whitespace / long-run windows。
3. 用 `SequenceMatcher(autojunk=False)` 或 bounded Needleman-Wunsch 對 windows 對齊。
4. 對 modified windows 再做字元級或 token 級比較。
5. 只在候選差異上套分類器。

分類規則先保持小於 5 條：

- 太短且無數字：drop
- 無 CJK 且非 priority pattern：drop
- 數學公式/亂碼：drop
- numbers changed：keep as NUMBER_MODIFIED
- large added/deleted CJK block：keep as ADDED/DELETED

### Phase 3 - Shadow Comparison

新增診斷腳本，對同一樣本同時輸出：

- current heuristic report
- alignment shadow report
- overlap / only-current / only-alignment
- golden truth match

只有當 shadow 在固定樣本上 precision/recall 明顯勝出，才考慮接入正式 `generate_diff_report`。

## Decision

立即凍結 `diff_service.py` 的 recall 調參。允許的變更限於：

- golden regression harness
- trace/log/diagnostic output
- alignment shadow prototype
- P0 hotfix with a failing golden case first

這樣才能停止「修一組、破一組」的循環。
