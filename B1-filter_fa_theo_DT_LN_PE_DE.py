import os, sys, warnings, time, io
from contextlib import redirect_stdout
import pandas as pd

API_KEY_ENV = "VNSTOCK_API_KEY"

# --- CẤU HÌNH TIÊU CHUẨN LỌC ---
ROE_MIN = 12
GROWTH_MIN = 15
PE_MAX = 17
DE_MAX = 1.5

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


def get_metric_values(df, keywords):
    """Hàm dò tìm cấu trúc: Quét theo Hàng (Row). Lấy giá trị quý mới nhất + quý
    liền trước. Dùng cho ROE/P/E/D/E - các chỉ số không cần so sánh YoY."""
    try:
        if df is None or 'item' not in df.columns:
            return None, None
        for kw in keywords:
            mask = df['item'].astype(str).str.contains(kw, case=False, na=False)
            if mask.any():
                row = df[mask].iloc[0]
                data_cols = [c for c in df.columns if c not in ['item', 'item_id']]
                if len(data_cols) >= 2:
                    val_latest = float(row[data_cols[0]]) if pd.notnull(row[data_cols[0]]) else None
                    val_prev = float(row[data_cols[1]]) if pd.notnull(row[data_cols[1]]) else None
                    return val_latest, val_prev
        return None, None
    except Exception:
        return None, None


def get_net_profit_yoy(df, keywords):
    """Lấy LNST quý mới nhất và LNST CÙNG KỲ NĂM TRƯỚC (cách 4 quý) để tính tăng
    trưởng theo YoY thực.

    SỬA LỖI QUAN TRỌNG so với bản gốc: bản gốc lấy data_cols[1] tức quý LIỀN TRƯỚC
    (so QoQ - quý-với-quý) để tính growth, thay vì so cùng kỳ năm trước (YoY). Với
    doanh nghiệp có lợi nhuận theo mùa vụ (nông sản, đường, du lịch, xây dựng...),
    QoQ tạo ra % tăng trưởng méo mó cực đoan (nghi vấn chính là nguồn gốc các con số
    bất thường như +5267%, +1986%, +1461% từng phát hiện ở vòng lọc B4 trước đó).

    Nếu dữ liệu không đủ 5 quý để so YoY thật, fallback về QoQ và đánh dấu rõ
    is_yoy=False để người dùng biết con số này cần thận trọng hơn.
    """
    try:
        if df is None or 'item' not in df.columns:
            return None, None, None
        for kw in keywords:
            mask = df['item'].astype(str).str.contains(kw, case=False, na=False)
            if mask.any():
                row = df[mask].iloc[0]
                data_cols = [c for c in df.columns if c not in ['item', 'item_id']]
                if len(data_cols) < 2:
                    return None, None, None
                val_latest = float(row[data_cols[0]]) if pd.notnull(row[data_cols[0]]) else None
                if val_latest is None:
                    return None, None, None
                if len(data_cols) >= 5 and pd.notnull(row[data_cols[4]]):
                    return val_latest, float(row[data_cols[4]]), True
                if pd.notnull(row[data_cols[1]]):
                    return val_latest, float(row[data_cols[1]]), False
                return val_latest, None, None
        return None, None, None
    except Exception:
        return None, None, None


def get_roe_ttm(df, keywords):
    """ROE 4 quý gần nhất cộng dồn (TTM) thay cho 'quý mới nhất x 4'.

    SỬA (đặc thù TTCK VN): nhiều doanh nghiệp niêm yết VN có lợi nhuận mùa vụ đậm
    (mía đường, du lịch, xây dựng, nông sản, bán lẻ mùa Tết...). Lấy ROE quý cao
    điểm x4 sẽ thổi phồng ROE năm gấp 2-3 lần thực tế; lấy quý thấp điểm x4 lại
    đánh trượt oan doanh nghiệp tốt. Cộng dồn 4 quý phản ánh đúng hơn.
    Không đủ 4 quý dữ liệu -> fallback x4 như cũ + gắn cờ để người dùng biết.
    Giữ heuristic nhân 100 khi |giá trị| < 1 (đoán dạng thập phân) như bản gốc vì
    không biết chắc đơn vị nguồn KBS - đây là giới hạn cần soát thủ công.
    """
    try:
        if df is None or 'item' not in df.columns:
            return None, None
        for kw in keywords:
            mask = df['item'].astype(str).str.contains(kw, case=False, na=False)
            if mask.any():
                row = df[mask].iloc[0]
                data_cols = [c for c in df.columns if c not in ['item', 'item_id']]
                vals = []
                for c in data_cols[:4]:
                    if pd.notnull(row[c]):
                        v = float(row[c])
                        if abs(v) < 1:
                            v *= 100
                        vals.append(v)
                if len(vals) == 4:
                    return sum(vals), True   # TTM thật
                if vals:
                    return vals[0] * 4, False  # fallback x4, kém tin cậy hơn
                return None, None
        return None, None
    except Exception:
        return None, None


def fetch_finance_data_with_retry(symbol, max_retries=3):
    """Hàm an toàn: Tự động thử lại NGẦM nếu dính Rate Limit (giữ nguyên chế độ
    tàng hình - không in chi tiết từng lần thử, chỉ tổng hợp số liệu ở cuối)."""
    for attempt in range(max_retries):
        try:
            with redirect_stdout(io.StringIO()):
                finance = vnstock.Finance(symbol=symbol, source='KBS')
                df_is = finance.income_statement(period='quarterly')
                df_ratio = finance.ratio(period='quarterly')

            if df_is is None or df_ratio is None or df_is.empty or df_ratio.empty:
                raise ConnectionError("Rate limit hoặc dữ liệu trống")

            return df_is, df_ratio
        except Exception:
            time.sleep(9)

    return None, None


def loc_hybrid(symbol, stats):
    """Hàm lõi kiểm tra các tiêu chí tài chính. `stats` được truyền vào để ghi
    nhận lý do loại/cảnh báo, phục vụ báo cáo minh bạch ở cuối chương trình."""
    try:
        df_is, df_ratio = fetch_finance_data_with_retry(symbol)
        if df_is is None or df_ratio is None:
            stats['fetch_failed'] += 1
            return False, None, None

        lnst_nay, lnst_truoc, is_yoy = get_net_profit_yoy(
            df_is, ['Lợi nhuận sau thuế của cổ đông công ty mẹ', 'Lợi nhuận sau thuế', 'Net profit'])
        if lnst_nay is None or lnst_truoc is None or lnst_truoc == 0:
            stats['no_profit_data'] += 1
            return False, None, None
        growth = ((lnst_nay - lnst_truoc) / abs(lnst_truoc)) * 100
        if not is_yoy:
            stats['growth_fallback_qoq'] += 1

        roe_annual, roe_is_ttm = get_roe_ttm(df_ratio, ['ROE', 'Return on Equity'])
        if roe_annual is not None and not roe_is_ttm:
            stats['roe_annualized_x4'] += 1
        pe, _ = get_metric_values(df_ratio, ['P/E', 'Price to Earning', 'PE'])
        # SỬA (đặc thù nhãn BCTC VN): bỏ từ khóa trần 'Nợ phải trả' vì nó khớp cả
        # dòng "Nợ phải trả/Tổng nguồn vốn" (tức Nợ/Tổng tài sản - luôn <1) khiến
        # doanh nghiệp đòn bẩy cao vẫn lọt lưới D/E. Chỉ giữ nhãn đúng nghĩa Nợ/VCSH.
        de, _ = get_metric_values(df_ratio, ['Nợ/VCSH', 'Nợ / VCSH', 'Debt/Equity',
                                             'Nợ phải trả/Vốn chủ sở hữu', 'Nợ phải trả/VCSH'])
        if de is None:
            stats['de_missing'] += 1
            # CHẨN ĐOÁN: D/E None ở gần như mọi mã (không phải vài mã lẻ tẻ) là dấu hiệu
            # từ khóa dò tìm không khớp tên chỉ tiêu THẬT của nguồn KBS. In ra tối đa 3 lần
            # (tránh làm ngợp log) toàn bộ danh sách 'item' thật để xác định đúng từ khóa
            # cần dùng, thay vì tiếp tục đoán mù không có căn cứ.
            if stats['de_missing'] <= 3 and df_ratio is not None and 'item' in df_ratio.columns:
                print(f"🔬 CHẨN ĐOÁN D/E [{symbol}] - Danh sách chỉ tiêu thật từ nguồn KBS:")
                for item_name in df_ratio['item'].astype(str).tolist():
                    print(f"     - {item_name}")

        if de and de > 5:
            de = de / 100
            stats['de_unit_rescaled'] += 1  # suy đoán đơn vị - log lại để đối chiếu thủ công

        is_ok = True
        if not roe_annual or roe_annual < ROE_MIN: is_ok = False
        if growth < GROWTH_MIN: is_ok = False
        if pe and pe > PE_MAX: is_ok = False

        # SỬA LỖI: bản gốc dùng điều kiện `"Ngân hàng" not in symbol` để định miễn trừ
        # filter D/E cho ngân hàng - điều kiện này KHÔNG BAO GIỜ đúng vì mã CK (vd:
        # "VCB", "ACB") không chứa chữ "Ngân hàng", nên trên thực tế đây là code chết,
        # không hề có tác dụng. Việc ngân hàng "lọt qua" filter D/E trong bản gốc xảy ra
        # HOÀN TOÀN NGẪU NHIÊN, vì BCTC ngân hàng thường không có dòng "Nợ/VCSH" nên de
        # trả về None, khiến điều kiện `if de and ...` tự động bỏ qua bất kể banking hay
        # không. Code dưới đây loại bỏ điều kiện kiểm tra "Ngân hàng" gây hiểu nhầm và
        # XÁC NHẬN TƯỜNG MINH hành vi thực tế: D/E không xác định -> không áp filter D/E.
        if de is not None and de > DE_MAX:
            is_ok = False

        if is_ok:
            pe_str = f"{pe:.1f}" if pe else "N/A"
            de_str = f"{de:.2f}" if de else "N/A"
            yoy_tag = "" if is_yoy else " [QoQ~ cần thận trọng]"
            roe_tag = "" if roe_is_ttm else " [x4~]"
            msg = f"✅ {symbol:<5} | ĐẠT: ROE={roe_annual:.1f}%{roe_tag}, Tăng trưởng={growth:.1f}%{yoy_tag}, P/E={pe_str}, D/E={de_str}"
            data_row = (symbol, roe_annual, growth, pe, de, is_yoy, roe_is_ttm)
            return True, msg, data_row

        return False, None, None
    except Exception:
        stats['error'] += 1
        return False, None, None


if __name__ == "__main__":
    print("=== [B1] LỌC FA HYBRID (CHẾ ĐỘ TÀNG HÌNH) ===")

    try:
        lister = vnstock.Listing(source='KBS')
        all_ma = lister.all_symbols()['symbol'].tolist()
    except Exception as e:
        print(f"⚠️  Nguồn KBS lỗi ({e}), thử nguồn dự phòng MSN...")
        try:
            lister = vnstock.Listing(source='MSN')
            all_ma = lister.all_symbols()['symbol'].tolist()
        except Exception as e2:
            print(f"❌ Lỗi mạng: Không thể lấy danh sách mã từ cả 2 nguồn KBS và MSN ({e2}).")
            sys.exit(1)

    if not all_ma:
        print("❌ Lỗi mạng: Không thể lấy danh sách mã.")
        sys.exit(1)

    ds_dat = []
    total = len(all_ma)
    stats = {'fetch_failed': 0, 'no_profit_data': 0, 'growth_fallback_qoq': 0,
             'de_unit_rescaled': 0, 'roe_annualized_x4': 0, 'de_missing': 0, 'error': 0}
    print(f"⏳ Bắt đầu quét ngầm {total} mã toàn thị trường. Quá trình này có thể mất thời gian, vui lòng đợi...\n")

    for i, ma in enumerate(all_ma):
        is_passed, msg, data_row = loc_hybrid(ma, stats)

        if is_passed:
            print(msg)
            ds_dat.append(data_row)

        time.sleep(2.2)

    print("\n" + "=" * 60)
    print("📊 BÁO CÁO MINH BẠCH (đối chiếu thủ công trước khi tin số liệu):")
    print(f" - Không lấy được dữ liệu BCTC (lỗi mạng / rate-limit sau 3 lần thử): {stats['fetch_failed']} mã")
    print(f" - Có dữ liệu nhưng thiếu chỉ tiêu LNST để tính tăng trưởng:          {stats['no_profit_data']} mã")
    print(f" - Tăng trưởng phải fallback QoQ (không đủ 5 quý để so YoY thật):     {stats['growth_fallback_qoq']} mã")
    print(f" - D/E bị suy đoán lại đơn vị (giá trị gốc > 5, tự chia 100):         {stats['de_unit_rescaled']} mã")
    print(f" - ROE phải ước lượng x4 (không đủ 4 quý để tính TTM thật):           {stats['roe_annualized_x4']} mã")
    print(f" - Không tìm thấy chỉ tiêu D/E (bỏ qua filter D/E - soát thủ công):   {stats['de_missing']} mã")
    print(f" - Lỗi không xác định khác:                                          {stats['error']} mã")
    print("=" * 60)

    file_name = "Bao_cao_FA_AI.csv"
    try:
        with open(file_name, "w", encoding="utf-8-sig") as f:
            f.write("Mã CK,ROE Năm (%),Tăng trưởng LNST (%),P/E,D/E,Tăng_trưởng_YoY_thật,ROE_TTM_thật\n")
            for item in ds_dat:
                ma_ck = item[0]
                roe_val = f"{item[1]:.1f}"
                growth_val = f"{item[2]:.1f}"
                pe_val = f"{item[3]:.1f}" if item[3] else "N/A"
                de_val = f"{item[4]:.2f}" if item[4] else "N/A"
                yoy_val = "True" if item[5] else "False"
                ttm_val = "True" if item[6] else "False"
                f.write(f"{ma_ck},{roe_val},{growth_val},{pe_val},{de_val},{yoy_val},{ttm_val}\n")
        print(f"\n✅ XONG HOÀN TOÀN B1! Đã lưu {len(ds_dat)} mã vào '{file_name}'.")
    except PermissionError:
        print(f"\n❌ Lỗi: File '{file_name}' đang mở bằng Excel. Hãy đóng lại để lưu dữ liệu!")
