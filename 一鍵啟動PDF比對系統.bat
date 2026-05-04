@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ====================================
echo   PDF 比對系統 - 一鍵啟動
echo ====================================

where docker >nul 2>&1
if errorlevel 1 (
  echo 找不到 Docker，請先安裝 Docker Desktop。
  echo.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker 尚未啟動，請先開啟 Docker Desktop。
  echo.
  pause
  exit /b 1
)

echo 啟動中，第一次可能需要幾分鐘下載模型...
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo 啟動失敗，請檢查上方訊息。
  echo.
  pause
  exit /b 1
)

echo.
echo 等待服務完成初始化...
set "READY=0"
set "HAS_CURL=0"
where curl >nul 2>&1
if not errorlevel 1 (
  set "HAS_CURL=1"
  for /L %%i in (1,1,30) do (
    curl -fsS "http://localhost:8001/health" >nul 2>&1
    if not errorlevel 1 (
      set "READY=1"
      goto :health_done
    )
    ping 127.0.0.1 -n 3 >nul
  )
)

:health_done
echo.
if "!READY!"=="1" (
  echo 啟動成功。
) else (
  if "!HAS_CURL!"=="0" (
    echo 容器已啟動（本機無 curl，略過健康檢查）。
  ) else (
    echo 容器已啟動，系統仍在初始化。
    echo 請稍後手動開啟。
  )
)
echo 前端介面: http://localhost:8001
echo API: http://localhost:8001/api

if "!READY!"=="1" start "" "http://localhost:8001"

echo.
pause
