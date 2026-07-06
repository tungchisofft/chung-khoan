@echo off
echo --- BAT DAU QUY TRINH 15:00 ---

:: 1. Di chuyen den thu muc chua code (QUAN TRONG!)
:: Ban hay thay doi duong dan duoi day thanh duong dan that cua ban
cd /d "D:\OneDrive - tapdoanxangdau\PERSONAL\Chứng khoán\đánh giá hàng tuần"

:: 2. Chay lan luot cac script
echo Dang chay B2 (Loc TA)...
python B2_B3-trend_health.py

echo.
echo Dang chay B4 (Xep Hang)...
python B4-ranking_prestige.py

echo.
echo Dang chay B5 (Xep Hang)...
python B5-portfolio_execution.py


echo.
echo --- HOAN TAT! ---
:: Lenh pause de cua so khong tat ngay, giup ban xem ket qua
pause