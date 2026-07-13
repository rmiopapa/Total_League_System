@echo off
chcp 65001 > nul

echo ========================================
echo Totala_League_Post exe作成
echo ========================================

if not exist LeaguePost.ico (
    echo.
    echo エラー: LeaguePost.ico が見つかりません。
    pause
    exit /b 1
)

py -m pip install -r requirements.txt

pyinstaller --clean --noconfirm LeaguePost.spec

echo.
echo 完了しました。
echo dist フォルダ内に exe が作成されています。
pause