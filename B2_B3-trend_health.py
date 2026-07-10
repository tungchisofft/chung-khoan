import os, sys, warnings, time, json

# --- XỬ LÝ LỖI FONT AN TOÀN ---
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

from datetime import datetime, timedelta
import pandas as pd
import numpy as np

API_KEY_ENV = "VNSTOCK_API_KEY"

# --- CẤU HÌNH ---
CONFIG_FILE = "trading_parameters.json"
INPUT_FILE = "Bao_cao_FA_AI.csv"
OUTPUT_FILE = "Bao_cao_B3.csv"

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


def auto_update_market_regime():
    """Hàm tự động quét VN-Index và cập nhật file trading_parameters.json"""
    print("\n=== [1] TỰ ĐỘNG CHUẨN ĐOÁN THỊ TRƯỜNG CHUNG (VN-INDEX) ===")
    regime = None
    try:
        # Lấy dữ liệu VN-Index qua nguồn VCI
        quote = vnstock.Quote(symbol='VNINDEX', source='VCI')
        df = quote.history(start=(datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d'),
                           end=datetime.now().strftime('%Y-%m-%d'), resolution='1D')

        if df is None or len(df) < 200:
            print("⚠️ Cảnh báo: Không lấy được đủ dữ liệu VN-Index. Giữ nguyên kịch bản cũ.")
        else:
            df.columns = df.columns.str.lower()
            price = df['close'].iloc[-1]
            ma50 = df['close'].rolling(50).mean().iloc[-1]
            ma200 = df['close'].rolling(200).mean().iloc[-1]

            print(f"📊 Chỉ số: {price:,.2f} | MA50: {ma50:,.2f} | MA200: {ma200:,.2f}")

            # Logic phân định kịch bản
            if price > ma50 and ma50 > ma200:
                regime = "BULL"
            elif price < ma50 and ma50 < ma200:
                regime = "BEAR"
            else:
                regime = "NEUTRAL"
            print(f"👉 Chuẩn đoán thị trường: {regime}\n")
    except Exception as e:
        print(f"⚠️ Lỗi chuẩn đoán thị trường: {e}\n")

    # Đọc và Cập nhật file JSON
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            full_cfg = json.load(f)
    except FileNotFoundError:
        print(f"❌ Không tìm thấy file cấu hình '{CONFIG_FILE}'.")
        print("   File này cần được tạo thủ công với khóa 'active_scenario' và 'scenarios'")
        print("   (mỗi kịch bản gồm 'technical.avg_vol_min', 'technical.volatility_max',")
        print("   'technical.rsi_period', 'technical.adx_period').")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ File '{CONFIG_FILE}' không phải JSON hợp lệ: {e}")
        sys.exit(1)

    try:
        old_regime = full_cfg.get('active_scenario', 'NEUTRAL')

        if regime and regime != old_regime:
            full_cfg['active_scenario'] = regime
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(full_cfg, f, indent=2, ensure_ascii=False)
            print(f"⚙️ HỆ THỐNG ĐÃ TỰ ĐỘNG CẬP NHẬT FILE '{CONFIG_FILE}' SANG KỊCH BẢN: {regime}\n")
            active_sc = regime
        else:
            active_sc = old_regime
            print(f"⚙️ Kịch bản hiện tại vẫn là '{active_sc}'. Không cần thay đổi file cấu hình.\n")

        cfg = full_cfg['scenarios'][active_sc]
        # SỬA (đặc thù TTCK VN): thêm ngưỡng GIÁ TRỊ giao dịch bình quân (tỷ/phiên).
        # Khối lượng đơn thuần gây nhiễu: 200k cp x 5.000đ = 1 tỷ/phiên (rất mỏng,
        # khó thoát hàng khi cắt lỗ) trong khi 200k cp x 80.000đ = 16 tỷ/phiên (ổn).
        # Key 'min_value_bn' là TÙY CHỌN trong JSON; thiếu -> mặc định 3.0 tỷ để
        # tương thích ngược với file cấu hình cũ.
        min_value_bn = cfg['technical'].get('min_value_bn', 3.0)
        return active_sc, cfg['technical']['avg_vol_min'], cfg['technical']['volatility_max'], min_value_bn

    except KeyError as e:
        print(f"❌ File '{CONFIG_FILE}' thiếu khóa cấu hình bắt buộc: {e}")
        sys.exit(1)


def fetch_price_history_with_retry(symbol, max_retries=3, wait_seconds=15):
    """Lấy lịch sử giá có thử lại khi gặp lỗi tạm thời (rate-limit/timeout).
    SỬA: 8s -> 15s, khớp đúng thời gian chờ mà thông báo lỗi RateLimitExceed của
    chính VCI khuyến nghị ("Vui lòng thử lại sau 15 giây") - xác nhận từ blog
    chính thức vnstock. VCI có bộ đếm rate-limit RIÊNG BIỆT với các nguồn khác."""
    for attempt in range(max_retries):
        try:
            quote = vnstock.Quote(symbol=symbol, source='VCI')
            df = quote.history(start=(datetime.now() - timedelta(days=350)).strftime('%Y-%m-%d'),
                               end=datetime.now().strftime('%Y-%m-%d'), resolution='1D')
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        if attempt < max_retries - 1:
            time.sleep(wait_seconds)
    return None


def check_technical_health_diagnostics(symbol, avg_vol_min, vol_max, min_value_bn):
    """Hàm test kỹ thuật cho từng mã cổ phiếu (Dùng thông số động từ JSON)"""
    try:
        df = fetch_price_history_with_retry(symbol)

        if df is None or len(df) < 200:
            return False, 'data'

        df.columns = df.columns.str.lower()

        # 1. Trend MA200
        ma200 = df['close'].rolling(200).mean().iloc[-1]
        price = df['close'].iloc[-1]
        if price < ma200:
            return False, 'ma200'

        # 2. Thanh khoản (Áp dụng tiêu chuẩn từ file JSON)
        avg_vol = df['volume'].tail(20).mean()
        if avg_vol < avg_vol_min:
            return False, 'vol'

        # 2b. GTGD bình quân 20 phiên (tỷ đồng) - SỬA đặc thù VN: lọc theo GIÁ TRỊ
        # giao dịch, không chỉ khối lượng. Đồng bộ heuristic đơn vị giá với B4
        # (nguồn VCI có thể trả giá theo đơn vị nghìn đồng).
        price_factor = 1000 if df['close'].iloc[-1] < 1000 else 1
        avg_value_bn = (df['volume'] * df['close'] * price_factor).tail(20).mean() / 1e9
        if avg_value_bn < min_value_bn:
            return False, 'value'

        # 3. Biến động (Áp dụng tiêu chuẩn từ file JSON)
        df['pct'] = df['close'].pct_change()
        volatility = df['pct'].tail(20).std() * 100
        if volatility > vol_max:
            return False, 'volatility'

        success_reason = f"Giá > MA200 ({price:,.0f} > {ma200:,.0f}), GTGD: {avg_value_bn:.1f} tỷ/phiên, Biến động: {volatility:.1f}%"
        return True, success_reason
    except Exception:
        return False, 'error'


if __name__ == "__main__":
    # BƯỚC 1: Tự động phân tích thị trường & lấy thông số cấu hình
    sc, sys_vol_min, sys_vol_max, sys_min_value_bn = auto_update_market_regime()

    print("="*60)
    print(f"=== [2] TIẾN HÀNH LỌC KỸ THUẬT (KỊCH BẢN ÁP DỤNG: {sc}) ===")
    print("="*60)

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Không tìm thấy {INPUT_FILE}. Hãy chạy file B1 trước!"); sys.exit(1)

    df_fa = pd.read_csv(INPUT_FILE)
    if df_fa.empty:
        print("❌ File dữ liệu trống!"); sys.exit(1)

    total_ma = len(df_fa)
    print(f"⏳ Bắt đầu test TA cho {total_ma} mã FA (Đang chạy ngầm)...\n")

    passed_rows = []
    stats = {'data': 0, 'ma200': 0, 'vol': 0, 'value': 0, 'volatility': 0, 'error': 0}
    excl_detail = {k: [] for k in stats}  # audit: mã nào bị loại vì lý do gì

    for index, row in df_fa.iterrows():
        ma_ck = row['Mã CK']

        # BƯỚC 2: Gọi hàm kiểm tra và truyền thông số từ Kịch bản vào
        is_passed, reason = check_technical_health_diagnostics(ma_ck, sys_vol_min, sys_vol_max, sys_min_value_bn)

        if is_passed:
            print(f"✅ {ma_ck:<5} | ĐẠT CHUẨN TA | {reason}")
            passed_rows.append(row)
        else:
            stats[reason] += 1
            excl_detail[reason].append(str(ma_ck))

        if (index + 1) % 20 == 0:
            print(f"🔄 Đang rà soát đến mã thứ {index + 1}/{total_ma}")

        # SỬA: 0.5s -> 1.2s. Gói API vnstock Cộng đồng giới hạn 60 request/phút;
        # 0.5s tương đương ~120 req/phút - VƯỢT GẤP ĐÔI giới hạn, là nguyên nhân
        # trực tiếp gây lỗi hàng loạt (rate-limit) khi chạy trên GitHub Actions.
        # 1.2s -> ~50 req/phút, có biên an toàn dưới ngưỡng 60.
        time.sleep(1.2)

    print("\n" + "="*55)
    print("📊 BÁO CÁO NGUYÊN NHÂN BỊ LOẠI:")
    print(f" - Gãy Trend dài hạn (Giá < MA200):     {stats['ma200']} mã")
    print(f" - Thanh khoản thấp (< {sys_vol_min}):        {stats['vol']} mã")
    print(f" - GTGD bình quân < {sys_min_value_bn} tỷ/phiên:        {stats['value']} mã")
    print(f" - Biến động quá mạnh (> {sys_vol_max}%):          {stats['volatility']} mã")
    print(f" - Dữ liệu lịch sử không đủ 200 ngày:   {stats['data']} mã")
    print(f" - Lỗi kết nối API/Không có dữ liệu:    {stats['error']} mã")
    print("="*55)
    print("📋 CHI TIẾT MÃ BỊ LOẠI (audit - đối chiếu thủ công khi cần):")
    for reason, codes in excl_detail.items():
        if codes:
            print(f"  - {reason}: {', '.join(codes)}")

    if passed_rows:
        df_b3 = pd.DataFrame(passed_rows)
        try:
            df_b3.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
            print(f"\n✅ Đã lọc được {len(passed_rows)} mã đạt chuẩn. Lưu tại: {OUTPUT_FILE}")
        except PermissionError:
            print(f"\n❌ LỖI: File '{OUTPUT_FILE}' đang bị khóa (thường do đang mở bằng Excel).")
            print(f"   File CŨ trên đĩa CHƯA được cập nhật — nếu chạy B4 tiếp theo lúc này,")
            print(f"   B4 sẽ đọc nhầm dữ liệu CŨ, không phải {len(passed_rows)} mã vừa lọc được ở trên.")
            print(f"   → Hãy đóng file '{OUTPUT_FILE}' rồi chạy lại B2/B3 trước khi chạy B4.")
            sys.exit(1)
    else:
        print("\n❌ TRẮNG BẢNG! Không có mã nào vượt qua các màng lọc kỹ thuật.")
