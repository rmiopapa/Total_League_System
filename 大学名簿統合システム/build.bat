@echo off
chcp 65001 > nul

echo ========================================
echo 大学名簿統合システム exe作成
echo ========================================

if not exist UDIS.ico (
    echo.
    echo エラー: UDIS.ico が見つかりません。
    pause
    exit /b 1
)

py -m pip install -r requirements.txt

py -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name "大学名簿統合システム" ^
  --icon "UDIS.ico" ^
  main.py

echo.
echo 完了しました。
echo dist フォルダ内に exe が作成されています。
pause