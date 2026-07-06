import os, sys, warnings, time, json

# --- XỬ LÝ LỖI FONT AN TOÀN ---
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass  # Bỏ qua nếu môi trường không hỗ trợ ép font

from datetime import datetime, timedelta
import pandas as pd
import numpy as np

API_KEY_ENV = "VNSTOCK_API_KEY"

# --- CẤU HÌNH ĐỒNG BỘ ---
CONFIG_FILE = "trading_parameters.json"
try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        full_cfg = json.load(f)
    sc = full_cfg['active_scenario']
    cfg = full_cfg['scenarios'][sc]
    RSI_PERIOD = cfg['technical']['rsi_period']
    ADX_PERIOD = cfg['technical']['adx_period']
except FileNotFoundError:
    print(f"❌ Không tìm thấy file cấu hình '{CONFIG_FILE}'. File này phải được tạo từ bước B2_B3 trước.")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"❌ File '{CONFIG_FILE}' không phải JSON hợp lệ: {e}")
    sys.exit(1)
except KeyError as e:
    print(f"❌ File '{CONFIG_FILE}' thiếu khóa cấu hình bắt buộc: {e}")
    sys.exit(1)

# CHỈ ĐỊNH FILE INPUT/OUTPUT CSV
INPUT_FILE = "Bao_cao_B3.csv"
OUTPUT_FILE = "Bao_cao_B4_Final.csv"

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


def calculate_indicators(df):
    df = df.copy()
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()

    # --- SỬA LỖI CHIA 0 (RSI) ---
    # Bản gốc: avg_gain/avg_loss có thể chia 0 khi avg_loss=0 (cổ phiếu chỉ tăng,
    # không giảm phiên nào trong kỳ EWM). Về mặt số học pandas/numpy không crash
    # (trả về inf hoặc NaN do warnings đã bị tắt), nhưng giá trị NaN có thể âm thầm
    # lan vào bước xếp hạng percentile ở B5 (rank() xử lý NaN không nhất quán).
    # Xử lý tường minh 2 trường hợp biên:
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # avg_loss=0 và avg_gain>0 (chỉ tăng, không giảm) -> RSI=100 đúng về bản chất
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100)
    # avg_loss=0 và avg_gain=0 (giá đứng yên hoàn toàn cả kỳ, ví dụ mã bị treo/đình
    # chỉ giao dịch) -> RSI trung tính = 50, không suy diễn xu hướng
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain == 0)), 50)
    df['RSI'] = rsi

    df['TR'] = pd.concat([df['high']-df['low'], abs(df['high']-df['close'].shift(1)), abs(df['low']-df['close'].shift(1))], axis=1).max(axis=1)
    plus_dm = np.where((df['high'].diff() > (df['low'].shift(1)-df['low'])) & (df['high'].diff() > 0), df['high'].diff(), 0)
    minus_dm = np.where(((df['low'].shift(1)-df['low']) > df['high'].diff()) & ((df['low'].shift(1)-df['low']) > 0), df['low'].shift(1)-df['low'], 0)

    df['ATR'] = df['TR'].ewm(alpha=1/ADX_PERIOD, adjust=False).mean()

    # --- SỬA LỖI CHIA 0 (ADX) ---
    # Bản gốc chia trực tiếp cho df['ATR'] và cho (+DI + -DI), cả hai đều có thể
    # bằng 0 với mã gần như không biến động (thanh khoản cực thấp/bị treo).
    atr_safe = df['ATR'].replace(0, np.nan)
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/ADX_PERIOD, adjust=False).mean() / atr_safe)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/ADX_PERIOD, adjust=False).mean() / atr_safe)
    df['+DI'] = plus_di.fillna(0)   # ATR=0 (không có biến động giá) -> không có lực hướng -> DI=0
    df['-DI'] = minus_di.fillna(0)

    denom = (df['+DI'] + df['-DI']).replace(0, np.nan)
    dx = 100 * abs(df['+DI'] - df['-DI']) / denom
    df['ADX'] = dx.ewm(alpha=1/ADX_PERIOD, adjust=False).mean().fillna(0)  # không có lực hướng -> ADX=0 (không có xu hướng)

    return df


def score_stock(symbol, stats):
    try:
        quote = vnstock.Quote(symbol=symbol, source='VCI')
        df = quote.history(start=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'), end=datetime.now().strftime('%Y-%m-%d'), resolution='1D')
        if df is None or df.empty:
            stats['no_data'] += 1
            return None
        df.columns = df.columns.str.lower()
        if df['close'].iloc[-1] < 1000:
            df[['open', 'high', 'low', 'close']] *= 1000
            stats['unit_rescaled'] += 1  # log lại để đối chiếu - đây là suy đoán đơn vị giá

        peak_1y = df['high'].max()
        curr_price = df['close'].iloc[-1]
        discount = ((peak_1y - curr_price) / peak_1y) * 100 if peak_1y else 0

        df = calculate_indicators(df)
        last = df.iloc[-1]

        # Scoring Logic: Composite Score
        rsi_score = max(0, 100 - abs(last['RSI'] - 35) * 2)
        score = (last['ADX'] * 0.4) + (rsi_score * 0.3) + (discount * 0.3)

        return {
            'Giá hiện tại': curr_price,
            'ADX': round(last['ADX'], 1),
            'RSI': round(last['RSI'], 1),
            'Chiết khấu từ đỉnh (%)': round(discount, 1),
            'Điểm sức mạnh': round(score, 2)
        }
    except Exception:
        stats['error'] += 1
        return None


if __name__ == "__main__":
    print("=== [B4] XẾP HẠNG TỔNG HỢP PRESTIGE (HỢP NHẤT FA & TA) ===")

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Không tìm thấy {INPUT_FILE}. Hãy chạy Bước 2-3 trước!"); sys.exit(1)

    df_b3 = pd.read_csv(INPUT_FILE)
    results = []
    stats = {'no_data': 0, 'unit_rescaled': 0, 'error': 0}

    print(f"📋 Đang tính toán điểm số kỹ thuật cho {len(df_b3)} mã...")

    for index, row in df_b3.iterrows():
        ma = row['Mã CK']
        ta_stats = score_stock(ma, stats)

        if ta_stats:
            combined_row = {**row.to_dict(), **ta_stats}
            results.append(combined_row)
        time.sleep(0.5)

    print("\n" + "=" * 55)
    print("📊 BÁO CÁO MINH BẠCH BƯỚC B4:")
    print(f" - Không lấy được dữ liệu giá / lỗi kết nối:    {stats['no_data']} mã")
    print(f" - Lỗi tính toán không xác định khác:           {stats['error']} mã")
    print(f" - Giá bị tự động nhân 1000 (suy đoán đơn vị):  {stats['unit_rescaled']} mã")
    print("=" * 55)

    if results:
        df_final = pd.DataFrame(results).sort_values(by='Điểm sức mạnh', ascending=False)

        print("\n🏆 DANH SÁCH XẾP HẠNG ƯU TIÊN:")
        print(df_final.to_string(index=False))

        df_final.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
        print(f"\n✅ XONG MỌI BƯỚC! Đã lưu kết quả hoàn chỉnh vào file: '{OUTPUT_FILE}'")
        print(f"📁 Hãy upload file '{OUTPUT_FILE}' này cho tôi để nhận phân tích chuyên sâu nhé!")
    else:
        print("❌ Lỗi: Không thể chấm điểm các mã.")
