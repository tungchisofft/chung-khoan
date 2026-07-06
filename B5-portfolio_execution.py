import os, sys, warnings
import pandas as pd
from datetime import datetime, timedelta

# --- XỬ LÝ LỖI FONT AN TOÀN ---
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

warnings.filterwarnings("ignore")

API_KEY_ENV = "VNSTOCK_API_KEY"

# ============================================================
# CẤU HÌNH (đưa lên đầu để minh bạch tham số, dễ tinh chỉnh
# mà không phải sửa logic bên trong các class)
# ============================================================
CONFIG = {
    # --- Ngưỡng quản trị rủi ro tuyệt đối (giữ nguyên giá trị gốc) ---
    "DE_MIN": 0.0,
    "DE_MAX": 0.5,
    "PE_MAX": 15,
    "ROE_MIN": 15,
    "GROWTH_MIN": 20,
    "PRICE_MIN": 10000,
    "RSI_MAX": 65,
    # Tăng trưởng LNST vượt ngưỡng này -> CẢNH BÁO nghi hiệu ứng nền thấp,
    # KHÔNG tự động loại (để người dùng tự đối chiếu BCTC cùng kỳ)
    "GROWTH_FLAG_THRESHOLD": 100,
    # --- Trọng số scoring ---
    "W_VALUE": 0.4,
    "W_QUALITY": 0.4,
    "W_TECHNICAL": 0.2,
    "TECH_RSI_TARGET": 40,
    "W_TECH_RSI": 0.5,
    "W_TECH_DISCOUNT": 0.5,
    # --- Quản trị danh mục ---
    "MAX_WEIGHT_PER_STOCK": 0.45,   # trần tỷ trọng 1 mã, tránh tập trung quá mức
    "STOP_LOSS_PCT": -0.07,
    # Proxy YẾU cho thanh khoản thấp (B4 không có dữ liệu khối lượng/vốn hóa)
    "LOW_LIQUIDITY_PRICE_FLAG": 20000,
}


class MarketRegimeModel:
    """Đo lường thời tiết vĩ mô tự động qua API (VN-Index vs MA200)."""

    def __init__(self):
        self.current = None
        self.ma200 = None
        self.data_ok = False
        self._vnstock = None
        self._configure_api()
        self._fetch_data()

    def _configure_api(self):
        api_key = os.environ.get(API_KEY_ENV)
        if not api_key:
            print(f"❌ Không tìm thấy biến môi trường {API_KEY_ENV}.")
            print("   KHÔNG hardcode API key trong source code. Đặt biến môi trường trước khi chạy:")
            print(f"   export {API_KEY_ENV}='your_key_here'   (Linux/Mac)")
            print(f"   set {API_KEY_ENV}=your_key_here        (Windows)")
            sys.exit(1)
        try:
            import vnstock
            vnstock.config.api_key = api_key
            self._vnstock = vnstock
        except ImportError:
            print("❌ Lỗi: Chưa cài đặt thư viện vnstock (pip install vnstock)")
            sys.exit(1)

    def _fetch_data(self):
        print("🌍 Đang quét dữ liệu vĩ mô (VN-Index)...")
        try:
            quote = self._vnstock.Quote(symbol='VNINDEX', source='VCI')
            df = quote.history(
                start=(datetime.now() - timedelta(days=350)).strftime('%Y-%m-%d'),
                end=datetime.now().strftime('%Y-%m-%d'),
                resolution='1D'
            )
            if df is not None and len(df) > 200:
                df.columns = df.columns.str.lower()
                self.current = df['close'].iloc[-1]
                self.ma200 = df['close'].rolling(200).mean().iloc[-1]
                self.data_ok = True
                print(f"📊 VN-Index: {self.current:,.2f} | MA200: {self.ma200:,.2f}")
            else:
                print("⚠️  Dữ liệu trả về không đủ 200 phiên để tính MA200 đáng tin cậy.")
        except Exception as e:
            print(f"❌ Lỗi lấy dữ liệu vĩ mô: {e}")

    def is_risk_on(self):
        if not self.data_ok:
            # Không xác thực được dữ liệu -> mặc định THẬN TRỌNG (risk-off),
            # không để hệ thống tự ý mở vị thế khi không có cơ sở.
            print("⚠️  Không xác thực được trạng thái thị trường -> mặc định RISK-OFF để bảo toàn vốn.")
            return False
        above_ma200 = self.current > self.ma200
        if above_ma200:
            print("ℹ️  Lưu ý: tín hiệu 'Trên MA200' chỉ phản ánh xu hướng giá, KHÔNG thay thế việc")
            print("    kiểm tra thủ công độ rộng thị trường, thanh khoản và dòng vốn khối ngoại.")
        return above_ma200


class QuantStockScreener:
    """Lớp xử lý dữ liệu và định lượng rủi ro tuyệt đối, có audit log loại trừ
    để người dùng đối chiếu thay vì tin tuyệt đối vào bộ lọc."""

    CORE_COLS = ['Mã CK', 'D/E', 'P/E', 'ROE Năm (%)', 'Tăng trưởng LNST (%)',
                 'RSI', 'Giá hiện tại']

    def __init__(self, data_path, config=None):
        self.df = pd.read_csv(data_path)
        self.cfg = config or CONFIG
        self.exclusions = {}  # reason -> [mã CK]

    def _log_exclusion(self, reason, ma_list):
        ma_list = [m for m in ma_list if pd.notna(m)]
        if ma_list:
            self.exclusions.setdefault(reason, []).extend(ma_list)

    def clean_data(self):
        cfg = self.cfg
        df = self.df.copy()

        # --- 1. Tách riêng nhóm D/E rỗng (thường là NGÂN HÀNG - cấu trúc vốn dựa
        #     trên huy động tiền gửi, chỉ số D/E truyền thống không áp dụng được).
        #     Bản gốc gộp chung với lỗi dữ liệu NaN khác -> mất minh bạch lý do loại. ---
        bank_like = df[df['D/E'].isna()]
        self._log_exclusion(
            "D/E rỗng (khả năng là ngân hàng - D/E không phù hợp, cần mô hình riêng cho ngành ngân hàng)",
            bank_like['Mã CK'].tolist())

        df = df.dropna(subset=self.CORE_COLS)

        # --- 2. D/E âm: KHÔNG mặc định kết luận "vốn chủ âm" một cách mù quáng.
        #     Có thể là vốn chủ sở hữu âm THỰC (rủi ro thật, ví dụ PIV) hoặc lỗi nhập liệu
        #     nguồn (ví dụ QNS D/E -2.53 nhiều khả năng là sai số liệu).
        #     -> Loại khỏi danh mục mua NGAY, nhưng log riêng để đối chiếu BCTC gốc. ---
        neg_de = df[df['D/E'] < cfg["DE_MIN"]]
        self._log_exclusion(
            "D/E âm (vốn chủ âm thực HOẶC lỗi dữ liệu nguồn - bắt buộc đối chiếu BCTC gốc trước khi kết luận)",
            neg_de['Mã CK'].tolist())
        df = df[df['D/E'] >= cfg["DE_MIN"]]

        high_de = df[df['D/E'] > cfg["DE_MAX"]]
        self._log_exclusion(f"D/E > {cfg['DE_MAX']} (đòn bẩy cao)", high_de['Mã CK'].tolist())
        df = df[df['D/E'] <= cfg["DE_MAX"]]

        bad_pe = df[(df['P/E'] <= 0) | (df['P/E'] > cfg["PE_MAX"])]
        self._log_exclusion(f"P/E ngoài khoảng (0, {cfg['PE_MAX']}]", bad_pe['Mã CK'].tolist())
        df = df[(df['P/E'] > 0) & (df['P/E'] <= cfg["PE_MAX"])]

        low_roe = df[df['ROE Năm (%)'] < cfg["ROE_MIN"]]
        self._log_exclusion(f"ROE < {cfg['ROE_MIN']}%", low_roe['Mã CK'].tolist())
        df = df[df['ROE Năm (%)'] >= cfg["ROE_MIN"]]

        low_growth = df[df['Tăng trưởng LNST (%)'] < cfg["GROWTH_MIN"]]
        self._log_exclusion(f"Tăng trưởng LNST < {cfg['GROWTH_MIN']}%", low_growth['Mã CK'].tolist())
        df = df[df['Tăng trưởng LNST (%)'] >= cfg["GROWTH_MIN"]]

        penny = df[df['Giá hiện tại'] < cfg["PRICE_MIN"]]
        self._log_exclusion(f"Giá < {cfg['PRICE_MIN']:,}đ (penny / thanh khoản rác)", penny['Mã CK'].tolist())
        df = df[df['Giá hiện tại'] >= cfg["PRICE_MIN"]]

        overbought = df[df['RSI'] > cfg["RSI_MAX"]]
        self._log_exclusion(f"RSI > {cfg['RSI_MAX']} (quá mua)", overbought['Mã CK'].tolist())
        df = df[df['RSI'] <= cfg["RSI_MAX"]]

        # --- 3. CẢNH BÁO (không loại) tăng trưởng LNST cực đoan: có thể do hiệu ứng
        #     nền thấp (base effect) của năm trước, chứ không phản ánh chất lượng tăng
        #     trưởng bền vững. Gắn cờ để người dùng tự kiểm tra, không tự ý quyết thay. ---
        df = df.copy()
        df['Cảnh_báo_tăng_trưởng_bất_thường'] = df['Tăng trưởng LNST (%)'] > cfg["GROWTH_FLAG_THRESHOLD"]

        # Kế thừa cờ minh bạch từ B1 (nếu pipeline chạy bản B1 mới): tăng trưởng
        # tính QoQ fallback và ROE ước lượng x4 là số liệu KÉM TIN CẬY hơn - hiển
        # thị để người dùng tự cân nhắc, không tự động loại.
        if 'Tăng_trưởng_YoY_thật' in df.columns:
            df['Cảnh_báo_growth_QoQ'] = ~df['Tăng_trưởng_YoY_thật'].astype(str).str.lower().eq('true')
        if 'ROE_TTM_thật' in df.columns:
            df['Cảnh_báo_ROE_x4'] = ~df['ROE_TTM_thật'].astype(str).str.lower().eq('true')

        return df

    def apply_factor_scoring(self):
        cfg = self.cfg
        data = self.clean_data().copy()
        if data.empty:
            return pd.DataFrame()

        # A. Chất lượng (Quality): ROE càng cao càng tốt
        data['Quality_Score'] = data['ROE Năm (%)'].rank(pct=True, ascending=True) * 100

        # B. Định giá (Value): P/E càng thấp càng tốt
        data['Value_Score'] = data['P/E'].rank(pct=True, ascending=False) * 100

        # C. Kỹ thuật (Entry Timing): kết hợp RSI hội tụ vùng tích lũy (mục tiêu ~40)
        #    VÀ "Chiết khấu từ đỉnh (%)" - cột đã có sẵn trong file B4 nhưng bản B5 gốc
        #    CHƯA dùng tới, dù đây chính là thước đo "đang mua ở vùng giá tốt hay không".
        data['RSI_Distance'] = abs(data['RSI'] - cfg["TECH_RSI_TARGET"])
        rsi_component = data['RSI_Distance'].rank(pct=True, ascending=False) * 100

        if 'Chiết khấu từ đỉnh (%)' in data.columns:
            discount_component = data['Chiết khấu từ đỉnh (%)'].rank(pct=True, ascending=True) * 100
            data['Technical_Score'] = (rsi_component * cfg["W_TECH_RSI"] +
                                        discount_component * cfg["W_TECH_DISCOUNT"])
        else:
            data['Technical_Score'] = rsi_component

        data['Total_Score'] = (data['Value_Score'] * cfg["W_VALUE"] +
                                data['Quality_Score'] * cfg["W_QUALITY"] +
                                data['Technical_Score'] * cfg["W_TECHNICAL"])

        final_portfolio = data.sort_values(by='Total_Score', ascending=False)
        top = final_portfolio.head(5).copy()

        # --- Phân bổ tỷ trọng theo điểm tin cậy (Conviction-Weighted), thay cho
        #     Equal Weight máy móc của bản gốc. Có trần tối đa/mã để tránh tập trung. ---
        raw_weight = top['Total_Score'] / top['Total_Score'].sum()
        capped = raw_weight.clip(upper=cfg["MAX_WEIGHT_PER_STOCK"])
        top['Tỷ_trọng_đề_xuất_%'] = (capped / capped.sum() * 100).round(1)

        # Cảnh báo thanh khoản: PROXY YẾU vì B4 không có dữ liệu khối lượng/vốn hóa.
        # Chỉ mang tính gợi ý kiểm tra thêm, không phải kết luận thanh khoản thực tế.
        top['Cảnh_báo_thanh_khoản(proxy)'] = top['Giá hiện tại'] < cfg["LOW_LIQUIDITY_PRICE_FLAG"]

        display_cols = ['Mã CK', 'Total_Score', 'P/E', 'D/E', 'ROE Năm (%)',
                         'Tăng trưởng LNST (%)', 'RSI', 'Giá hiện tại',
                         'Tỷ_trọng_đề_xuất_%', 'Cảnh_báo_tăng_trưởng_bất_thường',
                         'Cảnh_báo_thanh_khoản(proxy)']
        # Cột minh bạch tùy chọn (chỉ xuất hiện khi chạy B1/B4 bản mới)
        for opt_col in ['Cảnh_báo_growth_QoQ', 'Cảnh_báo_ROE_x4', 'Xu hướng DI', 'Giá_rescale_x1000']:
            if opt_col in top.columns:
                display_cols.append(opt_col)
        out = top[display_cols].copy()
        out['Total_Score'] = out['Total_Score'].map('{:.1f}'.format)
        out['D/E'] = out['D/E'].map('{:.2f}'.format)
        return out

    def print_exclusion_audit(self):
        if not self.exclusions:
            print("Không có mã nào bị loại.")
            return
        print("\n📋 NHẬT KÝ LOẠI TRỪ (đối chiếu thủ công, tránh tin mù quáng vào bộ lọc):")
        for reason, codes in self.exclusions.items():
            print(f"  - {reason}: {', '.join(codes)}")


# ==========================================
# KHU VỰC THỰC THI (EXECUTION LOGIC)
# ==========================================
if __name__ == "__main__":
    print("=== [B5-PRO] HỆ THỐNG QUẢN TRỊ RỦI RO & PHÂN BỔ DÒNG TIỀN ===\n")

    regime = MarketRegimeModel()

    if regime.is_risk_on():
        print("\n✅ XÁC NHẬN VĨ MÔ: Thị trường duy trì xu hướng (Trên MA200). Kích hoạt module TÌM KIẾM.")

        DATA_FILE = 'Bao_cao_B4_Final.csv'
        if not os.path.exists(DATA_FILE):
            print(f"❌ Không tìm thấy '{DATA_FILE}'. Hãy chạy file cập nhật data trước.")
            sys.exit()

        screener = QuantStockScreener(DATA_FILE)
        portfolio = screener.apply_factor_scoring()
        screener.print_exclusion_audit()

        if not portfolio.empty:
            print("\n🏆 TOP CỔ PHIẾU VƯỢT QUA KIỂM ĐỊNH RỦI RO (CẦN TỰ THẨM ĐỊNH THÊM TRƯỚC KHI MUA):")
            print("=" * 130)
            print(portfolio.to_string(index=False))
            print("=" * 130)
            print("\n💡 HÀNH ĐỘNG CHIẾN LƯỢC:")
            print("- Phân bổ vốn: theo cột 'Tỷ_trọng_đề_xuất_%' (trọng số theo điểm tin cậy,")
            print(f"  trần tối đa {CONFIG['MAX_WEIGHT_PER_STOCK']*100:.0f}%/mã) — KHÔNG còn chia đều máy móc")
            print("  cho các mã có rủi ro thanh khoản khác nhau.")
            print(f"- Quản trị: Stop-loss tham chiếu {CONFIG['STOP_LOSS_PCT']*100:.0f}% từ điểm mua. LƯU Ý ĐẶC THÙ VN:")
            print("  (1) Chu kỳ thanh toán T+2,5: cổ phiếu mua mới chỉ bán được sớm nhất từ phiên")
            print("      CHIỀU ngày T+2 -> stop-loss KHÔNG bảo vệ được trong ~2,5 ngày đầu nắm giữ.")
            print("  (2) Biên độ trần/sàn: HOSE ±7%, HNX ±10%, UPCoM ±15% -> một phiên giảm sàn")
            print("      HOSE đã chạm mức cắt lỗ; chuỗi giảm sàn có thể MẤT THANH KHOẢN (dư bán")
            print("      sàn không khớp) khiến lệnh cắt lỗ không khớp được ở mức mong muốn.")
            print("  Với mã gắn cờ 'Cảnh_báo_thanh_khoản(proxy)': nới biên hoặc dùng lệnh giới hạn.")
            print("- Mã có 'Cảnh_báo_tăng_trưởng_bất_thường'=True: đối chiếu LNST cùng kỳ năm")
            print("  trước khi tin vào % tăng trưởng (khả năng do hiệu ứng nền thấp).")
        else:
            print("\n❌ KHÔNG CÓ CỔ PHIẾU ĐẠT CHUẨN. Hệ thống ưu tiên bảo vệ vốn. Bỏ qua nhịp này.")

    else:
        print("\n🚨 CẢNH BÁO ĐỎ (RISK-OFF): Thị trường gãy vỡ vùng hỗ trợ Dài hạn (MA200),")
        print("    hoặc dữ liệu vĩ mô chưa xác thực được.")
        print("🛑 HÀNH ĐỘNG: Đóng băng toàn bộ lệnh giải ngân tấn công. Bảo vệ tỷ trọng Tiền mặt.")
