#!/bin/bash
cd "$(dirname "$0")"

echo "===================================="
echo "  PDF 比對系統 - Mac 一鍵啟動"
echo "===================================="

if ! command -v docker &> /dev/null; then
  echo "找不到 Docker，請先前往下載並安裝 Docker Desktop for Mac。"
  echo "請按任一鍵結束..."
  read -n 1
  exit 1
fi

if ! docker info > /dev/null 2>&1; then
  echo "Docker 尚未啟動，請先確保已開啟 Docker Desktop 應用程式。"
  echo "請按任一鍵結束..."
  read -n 1
  exit 1
fi

echo "啟動中，第一次可能需要幾分鐘下載模型..."
docker compose up --build -d

if [ $? -ne 0 ]; then
  echo ""
  echo "啟動失敗，請檢查上方訊息。"
  echo "請按任一鍵結束..."
  read -n 1
  exit 1
fi

echo ""
echo "等待服務完成初始化..."
READY=0
for i in {1..30}; do
  if curl -fsS "http://localhost:8001/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 3
done

echo ""
if [ "$READY" -eq 1 ]; then
  echo "啟動成功。"
  open "http://localhost:8001"
else
  echo "容器已啟動，系統可能仍在初始化中。"
  echo "請稍後手動開啟瀏覽器前往。"
fi

echo "前端介面: http://localhost:8001"
echo "API: http://localhost:8001/api"
echo ""

# Keep terminal open momentarily for user to read output
sleep 2
