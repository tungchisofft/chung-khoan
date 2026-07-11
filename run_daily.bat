@echo off
echo --- BAT DAU QUY TRINH 15:00 ---

:: 1. Di chuyen den thu muc chua code (QUAN TRONG!)
cd /d "D:\OneDrive - tapdoanxangdau\PERSONAL\Chứng khoán\đánh giá hàng tuần"

:: 2. B1 - CHỈ chạy vào Chủ nhật (giống logic bên GitHub Actions), vì B1 quét
::    toàn thị trường rất lâu. Cac ngay thuong dung lai FA_AI.csv co san.
::    %date:~0,3% lay 3 ky tu dau cua ngay (vd: "CN," neu he thong tieng Viet).
::    Neu may ban hien thi khac, doi dieu kien ben duoi cho dung.
echo Kiem tra co can chay B1 khong...
echo %date%
set /p XACNHAN="Hom nay co phai Chu nhat va muon chay lai B1 (quet toan thi truong, RAT LAU)? (y/n): "
if /i "%XACNHAN%"=="y" (
    echo Dang chay B1 - Loc FA toan thi truong...
    python B1-filter_fa_theo_DT_LN_PE_DE.py
) else (
    echo Bo qua B1, dung lai Bao_cao_FA_AI.csv hien co trong thu muc nay.
)

:: 3. Chay lan luot cac script con lai - LUON dung file FA_AI.csv VUA CO O TREN,
::    dam bao B2/B4/B5 khong bao gio lech pha voi B1 nhu truoc day.
echo.
echo Dang chay B2 (Loc TA)...
python B2_B3-trend_health.py

echo.
echo Dang chay B4 (Xep Hang)...
python B4-ranking_prestige.py

echo.
echo Dang chay B5 (Danh muc)...
python B5-portfolio_execution.py

:: 4. Ghi file trigger (.py) - GIONG HET buoc GitHub Actions lam - de web
::    Streamlit Cloud nhan dien day la thay doi CODE (dang tin cay hon CSV don
::    thuan) va tu tai lai. QUAN TRONG: nho upload CA file nay len GitHub cung
::    voi 3 file CSV, neu khong web se khong tu cap nhat nhu da gap truoc day.
echo.
echo Dang ghi file trigger cho web...
powershell -Command "$now = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm'); Set-Content -Path '_last_update_marker.py' -Value ('\"\"\"File nay duoc ghi tu dong sau moi lan chay local.\"\"\"' + [Environment]::NewLine + 'LAST_UPDATE_UTC = \"' + $now + ' UTC (chay local)\"') -Encoding UTF8"

echo.
echo --- HOAN TAT! ---
echo NHAC: Neu ban dung web tren GitHub/Streamlit, dung quen UPLOAD 5 file sau len GitHub:
echo   Bao_cao_FA_AI.csv, Bao_cao_B3.csv, Bao_cao_B4_Final.csv,
echo   trading_parameters.json, _last_update_marker.py (file MOI - bat buoc de web tu cap nhat)
echo Chay o day KHONG tu dong dong bo len web - phai tu tay upload.
pause
