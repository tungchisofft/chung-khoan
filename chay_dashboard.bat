@echo off
cd /d "%~dp0"
echo Dang khoi dong Dashboard Chung Khoan...
echo Trinh duyet se tu mo sau vai giay. Dung dong cua so nay khi dang dung dashboard.
streamlit run dashboard_pipeline.py
pause
