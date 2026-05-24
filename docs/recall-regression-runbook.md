# 影像型 PDF 召回層 — 真實容器回歸 Runbook

如何在**這台開發機**上，用**運行中的 MinerU 容器**對真實 PDF 跑一次端到端 `generate_diff_report`，
驗證召回層（`ENABLE_IMAGE_TEXT_RECALL`）的行為。**單元測試（host `pytest`）只驗純邏輯，
不經過真實 OCR**；要看真實行為一定要用本流程。最後一次驗證：2026-05-24。

## 環境事實（為什麼要這樣跑）

- **Host（你的 PowerShell / Git Bash 的 Python）沒有 `fitz`/`tesseract`/`docling`** —— 這是設計如此，
  所有解析/OCR 都在容器內。所以**不能**用 host python 跑整條管線；只能跑不依賴它們的單元測試。
- **容器內全都有**：`pdf-check-backend:latest`（fitz、tesseract `/usr/bin/tesseract`、docling、scipy…）、
  `mineru-api:pipeline`（torch `cu130`）。兩個容器平時就由 `docker compose up -d` 跑著。
- **MinerU 跑 CPU**：compose 沒開 GPU；本機只有 MX570 2GB，且正式環境 OCI 也無 GPU → **CPU 即目標環境**。
  一份 6 頁影像 PDF 的 OCR 約數分鐘；兩三份就 6–10 分鐘，請用背景執行。
- 內部網路名稱：`pdf_check_mineru_internal`；MinerU 服務 DNS：`mineru-api-minerU:18080`。
- **Git Bash 路徑陷阱**：MSYS 會把容器內路徑（`/repo`、`-w /repo/backend`）改寫成 `C:/Program Files/Git/...`。
  **務必**在 `docker run` 前加 `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`。

## 步驟

1. 在 `backend/scripts/` 放一支臨時 runner（**跑完即刪、勿 commit**），例如：

```python
import sys; sys.path.insert(0, "/repo/backend")
from pathlib import Path
from collections import Counter
from services.parser_service import _parse_via_fitz
from services.diff_service import generate_diff_report
from config import settings
old = Path("/samples/舊檔.pdf"); new = Path("/samples/新檔.pdf")
print("recall_enabled:", settings.enable_image_text_recall)
rep = generate_diff_report("x", old.name, new.name,
                           _parse_via_fitz(old), _parse_via_fitz(new), str(old), str(new))
print("SUMMARY:", rep.summary, "| suppressed:", rep.suppressed_count)
print("TYPES:", dict(Counter(i.diff_type.value for i in rep.items)))
for it in rep.items:
    b = it.new_bbox or it.old_bbox
    print(f"  {it.id} {it.diff_type.value} p{b.page if b else '?'} "
          f"{(it.old_value or '')[:70]!r} => {(it.new_value or '')[:70]!r} | {(it.context or '')[:50]}")
```

2. 掛載**當前 repo（含你改的程式）** + 樣本資料夾，接上 MinerU 網路，開召回旗標，背景跑：

```bash
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' docker run --rm \
  --network pdf_check_mineru_internal \
  -e ENABLE_IMAGE_TEXT_RECALL=true \
  -e MINERU_API_URL=http://mineru-api-minerU:18080 \
  -e OCR_LANGS=chi_tra+chi_sim+eng \
  -e PYTHONIOENCODING=utf-8 -e DATA_DIR=/tmp/runtime \
  -v "C:\Users\JY\Desktop\PDF_check_minerU:/repo:ro" \
  -v "C:\Users\JY\Downloads:/samples:ro" \
  -w /repo/backend \
  pdf-check-backend:latest \
  python scripts/your_runner.py
```

- repo 內的 `商品DM/` 會出現在 `/repo/商品DM/`（不必另外掛）。
- 設 `ENABLE_IMAGE_TEXT_RECALL=false` 即可比對「現預設 OFF」的輸出（且不需 MinerU、很快）。
- 健康檢查：容器內 `python -c "import requests,os;print(requests.get(os.environ['MINERU_API_URL']+'/health').text)"` 應回 `healthy`。

## 判讀（必過底線，改 PDF diff / 召回層後都要重跑）

- **真改全召回**：商品文號/頁尾 Version·Control No、宣告利率（如 3.90%→4.00%）、整段新增條款（如臻美利「註3」）。
- **無重切誤報**：新舊**完全相同**的長註腳/頁註（本範例數值僅供參考、未變的註2/註3）不得冒出 ADDED/DELETED/MODIFIED。
- **無 OCR 亂碼**：結果中不得出現 `[PAYV` 之類字串（`_is_reliable_ocr_text` 應擋下）。
- 密集數字格網（試算表）OCR 不可靠：單格變更可接受歸 IMAGE_DIFF + `suppressed_count` 橫幅，不要求逐格召回。

## 目前狀態快照（2026-05-24）

- **美鑫傳家 1130101→1130701**：✅ 乾淨（跨頁重切 FP 消、3.90→4.00／註5 2.25→2.50／祝壽總額／頁尾皆召回）。
- **臻美利 1130101→1130418**：⚠️ **回歸中**——「數字為主訊號（移除 `_NOISE_SIM`）」修好美鑫卻讓 註1 長註腳的 OCR 位數雜訊 FP 復活（d002/d004/d006），另有公式塊 DELETED FP（d007）。
- **美保發 1130101→1130418**：✅ 僅頁尾（乾淨，無 FP）。
- 結論：`ENABLE_IMAGE_TEXT_RECALL` **維持預設關**。下一步需「位數有變 **且** 相似度未過高」的複合判斷取代純 digit-master，並先量測各區塊相似度定門檻。詳見 `historical_issues.md` §7–§8。
