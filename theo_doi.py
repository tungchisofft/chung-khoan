"""theo_doi.py - Công cụ theo dõi TỐI GIẢN (thay cho cả B7 + B8)

Ý tưởng: bạn tự ghi những mã BẠN HIỂU vào file so_tay.csv (3 cột). Script này tự
đối chiếu với dữ liệu B4 mỗi lần chạy và BÁO khi mã của bạn về vùng đáng chú ý.

KHÔNG có lệnh phức tạp, KHÔNG có trạng thái, KHÔNG có JSON. Chỉ:
  1. Bạn điền so_tay.csv (mở bằng Excel, 3 cột: Mã, Hiểu gì, Giá muốn mua)
  2. Chạy: python theo_doi.py
  3. Nó báo: mã nào trong sổ tay đang <= giá bạn muốn, HOẶC đang chiết khấu sâu

Lần đầu chạy mà chưa có so_tay.csv -> script tự tạo file mẫu để bạn điền.
"""
import os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass
import pandas as pd

SO_TAY = "so_tay.csv"
B4_FILE = "Bao_cao_B4_Final.csv"


def tao_so_tay_mau():
    """Tạo file sổ tay mẫu để người dùng điền, kèm vài dòng ví dụ."""
    mau = pd.DataFrame({
        "Mã": ["QNS", "FPT", "(xóa dòng này, thêm mã của bạn)"],
        "Hiểu doanh nghiệp này thế nào (1 câu)": [
            "Đường + sữa đậu nành Vinasoy, đầu ngành",
            "Xuất khẩu phần mềm + viễn thông",
            "",
        ],
        "Giá muốn mua (đồng)": [48000, 90000, 0],
    })
    mau.to_csv(SO_TAY, index=False, encoding="utf-8-sig")
    print(f"📝 Đã tạo file mẫu '{SO_TAY}'.")
    print("   Mở bằng Excel, điền các mã BẠN HIỂU (chỉ ghi mã hiểu được, bỏ qua mã lạ).")
    print("   Cột 'Giá muốn mua' = mức giá bạn thấy đáng mua. Xong thì chạy lại script này.")


def main():
    # Lần đầu chưa có sổ tay -> tạo mẫu rồi dừng
    if not os.path.exists(SO_TAY):
        tao_so_tay_mau()
        return

    so_tay = pd.read_csv(SO_TAY)
    so_tay["Mã"] = so_tay["Mã"].astype(str).str.strip().str.upper()
    # bỏ dòng mẫu/trống
    so_tay = so_tay[so_tay["Mã"].str.match(r"^[A-Z]{3}$")]
    if so_tay.empty:
        print(f"⚠️ '{SO_TAY}' chưa có mã hợp lệ nào. Mở Excel điền mã (3 ký tự) rồi chạy lại.")
        return

    if not os.path.exists(B4_FILE):
        print(f"⚠️ Chưa có '{B4_FILE}'. Chạy pipeline (B1->B4) trước để có dữ liệu giá/kỹ thuật.")
        return
    b4 = pd.read_csv(B4_FILE)
    b4["Mã CK"] = b4["Mã CK"].astype(str).str.strip().str.upper()

    # Ghép sổ tay với dữ liệu B4
    gop = so_tay.merge(b4, left_on="Mã", right_on="Mã CK", how="left")

    print("=" * 60)
    print(f"🔭 THEO DÕI SỔ TAY ({len(so_tay)} mã bạn đang theo dõi)")
    print("=" * 60)

    canh_bao = []
    theo_doi = []
    chua_co_dl = []

    for _, r in gop.iterrows():
        ma = r["Mã"]
        gia_muon = r.get("Giá muốn mua (đồng)", 0)
        gia_ht = r.get("Giá hiện tại")
        rsi = r.get("RSI")
        chiet_khau = r.get("Chiết khấu từ đỉnh (%)")

        if pd.isna(gia_ht):
            chua_co_dl.append(ma)
            continue

        # Điều kiện cảnh báo: giá hiện tại <= giá muốn mua (nếu có đặt giá)
        ve_gia_tot = pd.notna(gia_muon) and gia_muon > 0 and gia_ht <= gia_muon
        # Hoặc: chiết khấu sâu + RSI chưa quá mua (vùng tích lũy)
        vung_tot = pd.notna(rsi) and pd.notna(chiet_khau) and rsi <= 45 and chiet_khau >= 12

        if ve_gia_tot:
            canh_bao.append((ma, gia_ht, gia_muon, "về giá bạn muốn"))
        elif vung_tot:
            canh_bao.append((ma, gia_ht, gia_muon, f"chiết khấu {chiet_khau:.0f}% từ đỉnh, RSI {rsi:.0f}"))
        else:
            theo_doi.append((ma, gia_ht, gia_muon))

    # In cảnh báo
    if canh_bao:
        print("\n🔔 ĐÁNG CHÚ Ý - mã trong sổ tay đang về vùng tốt:")
        for ma, gia_ht, gia_muon, ly_do in canh_bao:
            print(f"   💎 {ma}: giá hiện tại {gia_ht:,.0f}đ ({ly_do})")
        print("   → Xem lại vì sao bạn hiểu mã này trước khi quyết định. Cảnh báo ≠ lệnh mua.")
    else:
        print("\n🔕 Không mã nào trong sổ tay về vùng giá tốt hôm nay.")
        print("   → Không có gì để làm là điều BÌNH THƯỜNG và TỐT. Kiên nhẫn chờ giá.")

    # In danh sách đang theo dõi (chưa tới giá)
    if theo_doi:
        print("\n⏳ Đang theo dõi (chưa tới giá muốn mua):")
        for ma, gia_ht, gia_muon in theo_doi:
            khoang_cach = ""
            if pd.notna(gia_muon) and gia_muon > 0:
                pct = (gia_ht - gia_muon) / gia_muon * 100
                khoang_cach = f" — còn cách giá mua {pct:+.0f}%"
            print(f"   {ma}: {gia_ht:,.0f}đ{khoang_cach}")

    if chua_co_dl:
        print(f"\n(Chưa có dữ liệu B4 cho: {', '.join(chua_co_dl)} — "
              "mã chưa lọt qua B1-B4 tuần này, vẫn giữ trong sổ tay để theo dõi.)")
    print("=" * 60)


if __name__ == "__main__":
    main()
