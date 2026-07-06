import os, sys, warnings, json, time

# --- XỬ LÝ LỖI FONT AN TOÀN ---
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# --- CẤU HÌNH ĐỒNG BỘ ---
CONFIG_FILE = "trading_parameters.json"
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    full_cfg = json.load(f)
sc = full_cfg['active_scenario']
cfg = full_cfg['scenarios'][sc]

RSI_PERIOD = cfg['technical']['rsi_period']
ADX_PERIOD = cfg['technical']['adx_period']
PROFIT_THRESHOLD = cfg['portfolio']['profit_threshold']
TS_NORMAL_BASE = cfg['portfolio']['ts_normal_base']
TS_WEAK_BASE = cfg['portfolio']['ts_weak_base']
TS_CAP = cfg['portfolio']['ts_cap']

# --- CHỐT LỜI TỪNG PHẦN (mới) ---
# Khớp khung R:R đã thống nhất: stop-loss tham chiếu -7% (~biên HOSE) →
# tier1 ở R:R 1:2 (+14%), tier2 ở R:R 1:3 (+21%). Là key TÙY CHỌN trong JSON
# (portfolio.*) — thiếu thì dùng mặc định, không phá vỡ file cấu hình cũ.
TP_TIER1_PCT = cfg['portfolio'].get('tp_tier1_pct', 0.14)
TP_TIER1_FRACTION = cfg['portfolio'].get('tp_tier1_fraction', 1/3)
TP_TIER2_PCT = cfg['portfolio'].get('tp_tier2_pct', 0.21)
TP_TIER2_FRACTION = cfg['portfolio'].get('tp_tier2_fraction', 1/3)

API_KEY_ENV = "VNSTOCK_API_KEY"
FILE_SO_LENH = 'portfolio.json'
LOG_FILE = 'lich_su_danh_muc.txt'

api_key = os.environ.get(API_KEY_ENV)
if not api_key:
    print(f"❌ Không tìm thấy biến môi trường {API_KEY_ENV}.")
    print("   KHÔNG hardcode API key trong source code. Đặt biến môi trường trước khi chạy:")
    print(f"   export {API_KEY_ENV}='your_key_here'   (Linux/Mac)")
    print(f"   set {API_KEY_ENV}=your_key_here        (Windows, mở terminal MỚI sau khi set)")
    sys.exit(1)

try:
    import vnstock
    vnstock.config.api_key = api_key
except ImportError:
    print("❌ Lỗi: Chưa cài đặt thư viện vnstock (pip install vnstock)")
    sys.exit(1)

warnings.filterwarnings("ignore")

def log_print(msg, end='\n'):
    print(msg, end=end)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(str(msg) + end)

def get_free_float_resilient(symbol):
    """Lấy Free Float thực tế (Ưu tiên bảng tra cứu)"""
    hard_coded = {'DCM': 24.4, 'SAS': 11.5, 'MSH': 35.0, 'ITD': 45.2, 'NT2': 25.0}
    if symbol in hard_coded: return hard_coded[symbol]
    try:
        info = vnstock.stock_data.listing_info()
        row = info[info['ticker'] == symbol]
        if not row.empty:
            cols = [c for c in row.columns if 'free' in c.lower() and 'float' in c.lower()]
            for c in cols:
                val = row[c].values[0]
                if val and val > 0: return float(val) if val > 1 else float(val) * 100
    except: pass
    return 50.0

def calculate_manual_beta(stk_df, vni_df):
    """Tính Beta thực tế dựa trên biến động 1 năm"""
    try:
        df = pd.merge(stk_df[['close']], vni_df[['close']], left_index=True, right_index=True, suffixes=('_s', '_v'))
        returns = df.pct_change().dropna()
        matrix = np.cov(returns['close_s'], returns['close_v'])
        return matrix[0, 1] / matrix[1, 1]
    except: return 1.0

def calculate_full_indicators(df):
    df = df.copy()
    delta = df['close'].diff()
    gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + (avg_gain / avg_loss)))
    df['TR'] = pd.concat([df['high']-df['low'], abs(df['high']-df['close'].shift(1)), abs(df['low']-df['close'].shift(1))], axis=1).max(axis=1)
    df['ATR'] = df['TR'].ewm(alpha=1/ADX_PERIOD, adjust=False).mean()
    up_move = df['high'].diff(); down_move = df['low'].shift(1) - df['low']
    df['+DI'] = 100 * (pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0)).ewm(alpha=1/ADX_PERIOD, adjust=False).mean() / df['ATR'])
    df['-DI'] = 100 * (pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0)).ewm(alpha=1/ADX_PERIOD, adjust=False).mean() / df['ATR'])
    dx = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = dx.ewm(alpha=1/ADX_PERIOD, adjust=False).mean()
    df['MA200'] = df['close'].rolling(200).mean()
    return df

def manage():
    try:
        quote_vni = vnstock.Quote(symbol='VNINDEX', source='VCI')
        vni_df_raw = quote_vni.history(start=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'), resolution='D').rename(columns=str.lower)
        df_vni = calculate_full_indicators(vni_df_raw)
        vni = df_vni.iloc[-1]
        m_status = "NORMAL"
        if vni['RSI'] < 40: m_status = "WEAK"
        
        log_print("\n" + "="*75)
        log_print("🌍 THỊ TRƯỜNG (VN-INDEX):")
        log_print(f"   RSI VNI: {vni['RSI']:.1f} | Trạng thái: {m_status}")
        log_print(f"   Xung lực: ADX {vni['ADX']:.1f} (DI+ {vni['+DI']:.1f} | DI- {vni['-DI']:.1f})")
        log_print("="*75)
    except: return

    if not os.path.exists(FILE_SO_LENH): return
    with open(FILE_SO_LENH, 'r', encoding='utf-8') as f: portfolio = json.load(f)

    for symbol, lots in portfolio.items():
        if isinstance(lots, dict): lots = [lots]
        try:
            quote = vnstock.Quote(symbol=symbol, source='VCI')
            df_raw = quote.history(start=(datetime.now()-timedelta(days=365)).strftime('%Y-%m-%d'), resolution='D').rename(columns=str.lower)
            if df_raw['close'].iloc[-1] < 1000: df_raw[['open','high','low','close']] *= 1000 # Chuẩn hóa đơn vị
            
            beta = calculate_manual_beta(df_raw, vni_df_raw)
            ff = get_free_float_resilient(symbol)
            peak_1y = df_raw['high'].max()
            df = calculate_full_indicators(df_raw)
            stk = df.iloc[-1]
            discount = ((peak_1y - stk['close']) / peak_1y) * 100
            score = (stk['ADX'] * 0.4) + (max(0, 100 - abs(stk['RSI'] - 35) * 2) * 0.3) + (discount * 0.3)

            log_print(f"\n📊 BÁO CÁO CHIẾN LƯỢC V23.5 | MÃ: {symbol}")
            log_print("-" * 75)
            log_print(f"📈 CHỈ SỐ CỔ PHIẾU {symbol}:")
            log_print(f"   Giá: {stk['close']:,.0f} | MA200: {stk['MA200']:,.0f} | RSI: {stk['RSI']:.1f}")
            log_print(f"   ADX: {stk['ADX']:.1f} | Phe phái: Mua (DI+) {stk['+DI']:.1f} | Bán (DI-) {stk['-DI']:.1f}")
            log_print(f"📊 RỦI RO: Beta: {beta:.2f} | Free Float: {ff:.1f}%")
            log_print("-" * 30)
            log_print(f"🎯 ĐIỂM SỐ: Composite Score: {score:.2f} | Chiết khấu: {discount:.1f}%")
            log_print("-" * 75)
            
            for lot in lots:
                # 1. Cập nhật Giá cao nhất và Giá hiện tại
                lot['gia_hien_tai'] = int(round(stk['close']))
                peak = lot.get('gia_cao_nhat', lot['gia_von'])
                if stk['close'] > peak: 
                    peak = stk['close']
                    lot['gia_cao_nhat'] = int(round(peak))
                
                profit = (stk['close'] - lot['gia_von']) / lot['gia_von']
                
                # 2. Logic Trailing Stop theo Beta
                base_ts = TS_NORMAL_BASE * beta
                if profit > PROFIT_THRESHOLD: ts_pct = 0.05
                elif m_status == "WEAK": ts_pct = min(TS_WEAK_BASE, base_ts)
                else: ts_pct = max(0.08, min(TS_CAP, base_ts))
                
                stop_p = peak * (1 - ts_pct)

                # 2b. CHỐT LỜI TỪNG PHẦN (mới) - khóa dần lợi nhuận theo R:R đạt
                # được, độc lập với trailing stop theo peak ở trên. Dùng cờ lưu
                # trong portfolio.json để KHÔNG lặp lại khuyến nghị đã thực hiện.
                lot.setdefault('chot_loi_1_da_thuc_hien', False)
                lot.setdefault('chot_loi_2_da_thuc_hien', False)
                partial_action = None

                if profit >= TP_TIER2_PCT:
                    if not lot['chot_loi_2_da_thuc_hien']:
                        lot['chot_loi_2_da_thuc_hien'] = True
                        lot['chot_loi_1_da_thuc_hien'] = True  # tier2 bao hàm tier1
                        partial_action = (f"🎯 CHỐT LỜI ĐỢT 2: bán thêm {TP_TIER2_FRACTION*100:.0f}% "
                                          f"khối lượng còn lại (lãi +{profit*100:.1f}%, ~R:R 1:3)")
                    # Luôn khóa sàn stop tối thiểu ở mức lãi tier1, kể cả các lần
                    # chạy sau khi đã chốt tier2 - bảo vệ phần lãi đã đạt được.
                    stop_p = max(stop_p, lot['gia_von'] * (1 + TP_TIER1_PCT))
                elif profit >= TP_TIER1_PCT:
                    if not lot['chot_loi_1_da_thuc_hien']:
                        lot['chot_loi_1_da_thuc_hien'] = True
                        partial_action = (f"🎯 CHỐT LỜI ĐỢT 1: bán {TP_TIER1_FRACTION*100:.0f}% khối lượng "
                                          f"(lãi +{profit*100:.1f}%, ~R:R 1:2). Dời stop phần còn lại về hòa vốn.")
                    # Khóa sàn stop tối thiểu = giá vốn (hòa vốn) cho phần còn lại
                    stop_p = max(stop_p, lot['gia_von'])

                # 3. Cập nhật Stop Loss vào JSON
                lot['stop_loss'] = int(round(stop_p))
                
                action = "🔹 HOLD"
                if stk['close'] < stk['MA200']: action = "❌ SELL TOÀN BỘ (Thủng MA200)"
                elif stk['close'] < stop_p: action = f"⚠️ SELL (Stop {((peak - stop_p)/peak)*100:.0f}% từ đỉnh)"
                elif stk['ADX'] > 25 and stk['+DI'] > stk['-DI']: action = "MUA GIA TĂNG 🔥"

                if partial_action:
                    log_print(f"💡 {partial_action}")
                log_print(f"💡 KHUYẾN NGHỊ TỔNG: {action} (Lãi: {profit:+.1%})")
            time.sleep(0.5)
        except: continue

    # 4. LƯU LẠI TOÀN BỘ THÔNG TIN VÀO FILE JSON
    with open(FILE_SO_LENH, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, indent=4, ensure_ascii=False)
    log_print("\n✅ Đã cập nhật giá hiện tại và stop loss vào " + FILE_SO_LENH)
    log_print("=" * 75)

if __name__ == "__main__": manage()
