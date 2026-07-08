"""Dashboard 2 tab: (1) Chứng khoán - gom toàn bộ pipeline B1→B5 vào MỘT trang
dễ hiểu cho người mới; (2) Vàng - theo dõi giá thế giới/trong nước + nhận định.

Tự làm mới dữ liệu: nội dung chính đặt trong st.fragment(run_every=600) - cứ 10
phút tự đọc lại file (kết hợp cache theo mtime), người xem KHÔNG cần F5 khi CSV
trong container đã đổi. Việc container nhận commit mới từ GitHub vẫn dựa vào cơ
chế file trigger _last_update_marker.py (đã thiết lập trong Actions).
"""
import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

try:
    from _last_update_marker import LAST_UPDATE_UTC
except ImportError:
    LAST_UPDATE_UTC = "(chưa có dữ liệu từ Actions)"

st.set_page_config(page_title="Chứng khoán & Vàng", layout="wide")

FILES = {"B1": "Bao_cao_FA_AI.csv", "B3": "Bao_cao_B3.csv", "B4": "Bao_cao_B4_Final.csv"}
GOLD_SNAP = "Bao_cao_vang.csv"
GOLD_HIST = "lich_su_vang.csv"

B5 = dict(de_max=0.5, pe_max=15, roe_min=15, growth_min=20,
          price_min=10000, rsi_max=65, growth_flag=100, max_weight=0.45)

TEN = {"Mã CK": "Mã CP", "ROE Năm (%)": "Sinh lời vốn (ROE %)",
       "Tăng trưởng LNST (%)": "Tăng trưởng lợi nhuận (%)", "P/E": "Độ đắt/rẻ (P/E)",
       "RSI": "Nóng/nguội (RSI)", "Giá hiện tại": "Giá hiện tại (đ)",
       "Chiết khấu từ đỉnh (%)": "Giảm so với đỉnh (%)", "Total_Score": "Điểm tổng",
       "Tỷ trọng (%)": "Nên mua bao nhiêu (%)"}


def load_csv(path):
    if not os.path.exists(path):
        return None
    return _cached(path, os.path.getmtime(path))


@st.cache_data
def _cached(path, _mtime):
    return pd.read_csv(path)


def mtime_str(path):
    if not os.path.exists(path):
        return "—"
    from datetime import datetime
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d/%m/%Y %H:%M")


def bang_cao(df, tran=350):
    return min(max(len(df), 1) * 35 + 38, tran)


def mau_rsi(v):
    try:
        v = float(v)
    except (ValueError, TypeError):
        return ""
    if v > 70: return "background-color: #ffd6d6"
    if v < 35: return "background-color: #fff3cd"
    return "background-color: #d6f5d6"


# ============================================================
# TAB 1 — CHỨNG KHOÁN (một trang duy nhất, cho người mới)
# ============================================================
def tab_chung_khoan():
    df_b1, df_b3, df_b4 = (load_csv(FILES[k]) for k in ("B1", "B3", "B4"))

    st.info("**Trang này làm gì?** Hệ thống tự quét toàn bộ cổ phiếu trên sàn mỗi ngày, "
            "lọc qua 4 vòng như một cái phễu (doanh nghiệp tốt → xu hướng giá lên → chấm điểm "
            "→ loại rủi ro) và cho ra **danh sách gợi ý nên cân nhắc mua** kèm tỷ trọng vốn. "
            "🟢 xanh = tín hiệu tốt • 🟡 vàng = lưu ý • 🔴 đỏ = thận trọng.")

    c1, c2 = st.columns([1, 2])
    c1.metric("🕐 Dữ liệu cập nhật lúc (UTC)", LAST_UPDATE_UTC,
              help="Do hệ thống tự động ghi mỗi lần chạy xong. Nếu số này quá cũ so với "
                   "phiên giao dịch gần nhất, dữ liệu bên dưới chưa phải mới nhất.")
    if df_b4 is None:
        st.warning("Chưa có dữ liệu (thiếu Bao_cao_B4_Final.csv). Hệ thống tự động sẽ tạo file "
                   "này sau lần chạy đầu tiên.")
        return

    # ---- KẾT QUẢ CHÍNH: danh mục gợi ý (logic B5) ----
    st.subheader("🏆 Danh sách gợi ý hôm nay")
    df = df_b4.copy()
    exclusions = {}

    def exclude(mask, reason):
        nonlocal df
        removed = df[mask]["Mã CK"].tolist()
        if removed:
            exclusions[reason] = removed
        df = df[~mask]

    exclude(df["D/E"].isna(), "Không có số liệu nợ (thường là ngân hàng — cần cách đánh giá riêng)")
    exclude(df["D/E"] < 0, "Nợ âm bất thường (có thể lỗi dữ liệu — cần kiểm tra lại)")
    exclude(df["D/E"] > B5["de_max"], f"Vay nợ quá cao (D/E > {B5['de_max']})")
    exclude((df["P/E"] <= 0) | (df["P/E"] > B5["pe_max"]), f"Giá quá đắt (P/E ngoài 0–{B5['pe_max']})")
    exclude(df["ROE Năm (%)"] < B5["roe_min"], f"Sinh lời vốn thấp (ROE < {B5['roe_min']}%)")
    exclude(df["Tăng trưởng LNST (%)"] < B5["growth_min"], f"Tăng trưởng thấp (< {B5['growth_min']}%)")
    exclude(df["Giá hiện tại"] < B5["price_min"], f"Giá quá thấp (< {B5['price_min']:,}đ)")
    exclude(df["RSI"] > B5["rsi_max"], f"Giá đang quá nóng (RSI > {B5['rsi_max']})")

    if df.empty:
        st.warning("Hôm nay KHÔNG có mã nào đạt chuẩn — hệ thống khuyên giữ tiền mặt, chờ cơ hội tốt hơn.")
    else:
        df["Quality"] = df["ROE Năm (%)"].rank(pct=True) * 100
        df["Value"] = df["P/E"].rank(pct=True, ascending=False) * 100
        rsi_c = abs(df["RSI"] - 40).rank(pct=True, ascending=False) * 100
        if "Chiết khấu từ đỉnh (%)" in df.columns:
            df["Tech"] = rsi_c * 0.5 + df["Chiết khấu từ đỉnh (%)"].rank(pct=True) * 100 * 0.5
        else:
            df["Tech"] = rsi_c
        df["Total_Score"] = df["Value"] * 0.4 + df["Quality"] * 0.4 + df["Tech"] * 0.2

        top = df.sort_values("Total_Score", ascending=False).head(5).copy()
        w = (top["Total_Score"] / top["Total_Score"].sum()).clip(upper=B5["max_weight"])
        top["Tỷ trọng (%)"] = (w / w.sum() * 100).round(2)
        top["⚠️ Cần kiểm tra"] = top["Tăng trưởng LNST (%)"] > B5["growth_flag"]

        cA, cB = st.columns([3, 2])
        with cA:
            cols = ["Mã CK", "Total_Score", "Tỷ trọng (%)", "ROE Năm (%)",
                    "Tăng trưởng LNST (%)", "P/E", "RSI", "Giá hiện tại", "⚠️ Cần kiểm tra"]
            show = top[[c for c in cols if c in top.columns]].rename(columns=TEN)
            styled = show.style.format(precision=2)
            ten_rsi = TEN["RSI"]
            if ten_rsi in show.columns:
                styled = styled.map(mau_rsi, subset=[ten_rsi])
            st.dataframe(styled, use_container_width=True, hide_index=True,
                         height=bang_cao(show))
            st.caption("**Nên mua bao nhiêu (%)** = gợi ý chia vốn. ⚠️ = tăng trưởng cao bất thường, "
                       "nên tự kiểm tra lại báo cáo tài chính trước khi tin con số.")
        with cB:
            fig = px.pie(top, values="Tỷ trọng (%)", names="Mã CK", hole=0.45,
                         title="Nên chia vốn thế nào")
            st.plotly_chart(fig, use_container_width=True)

    # ---- PHỄU LỌC + CHI TIẾT (thu gọn trong expander) ----
    with st.expander("🔍 Xem hệ thống đã lọc thế nào (phễu 4 vòng)"):
        counts, labels = [], []
        if df_b1 is not None: counts.append(len(df_b1)); labels.append(f"Vòng 1 - DN tốt ({len(df_b1)})")
        if df_b3 is not None: counts.append(len(df_b3)); labels.append(f"Vòng 2 - Xu hướng lên ({len(df_b3)})")
        if df_b4 is not None: counts.append(len(df_b4)); labels.append(f"Vòng 3 - Được chấm điểm ({len(df_b4)})")
        if not df.empty: counts.append(len(top)); labels.append(f"Vòng 4 - Gợi ý cuối ({len(top)})")
        if counts:
            fig = go.Figure(go.Funnel(y=labels, x=counts, textinfo="value"))
            fig.update_layout(height=300, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        status = [{"File": f, "Trạng thái": "✅" if os.path.exists(f) else "❌",
                   "Cập nhật": mtime_str(f)} for f in FILES.values()]
        st.dataframe(pd.DataFrame(status), use_container_width=True, hide_index=True)

    with st.expander("📋 Vì sao các mã khác bị loại"):
        if exclusions:
            for reason, codes in exclusions.items():
                st.markdown(f"- **{reason}**: {', '.join(codes)}")
        else:
            st.write("Không mã nào bị loại.")

    with st.expander("📑 Bảng chi tiết từng vòng (cho người muốn xem sâu)"):
        for label, d in [("Vòng 1 - Doanh nghiệp tốt", df_b1),
                         ("Vòng 2 - Xu hướng giá lên", df_b3),
                         ("Vòng 3 - Chấm điểm", df_b4)]:
            if d is not None:
                st.markdown(f"**{label}** ({len(d)} mã)")
                dd = d.drop(columns=[c for c in ("Tăng_trưởng_YoY_thật", "ROE_TTM_thật") if c in d.columns])
                dd = dd.rename(columns=TEN)
                st.dataframe(dd.style.format(precision=2), use_container_width=True,
                             height=bang_cao(dd, 300))


# ============================================================
# TAB 2 — VÀNG
# ============================================================
def nhan_dinh_vang(snap, hist):
    """Nhận định TỰ ĐỘNG theo quy tắc minh bạch (rule-based), không phải lời
    khuyên tài chính. Mỗi quy tắc in rõ căn cứ số liệu để người xem tự thẩm định."""
    ket_luan, can_cu = [], []
    prem_sjc = snap.get("premium_sjc_pct")
    prem_nhan = snap.get("premium_nhan_pct")
    world = snap.get("gia_the_gioi_usd_oz")

    # Quy tắc 1: chênh lệch (premium) so với giá thế giới quy đổi
    if pd.notna(prem_sjc):
        if prem_sjc > 12:
            ket_luan.append("🔴 HẠN CHẾ mua vàng miếng SJC lúc này")
            can_cu.append(f"Giá miếng SJC cao hơn thế giới quy đổi **{prem_sjc:.1f}%** — nếu chênh lệch "
                          "co lại (chính sách tăng cung), giá miếng có thể giảm nhanh hơn giá thế giới.")
        else:
            can_cu.append(f"Chênh lệch SJC/thế giới ở mức {prem_sjc:.1f}% — không quá căng.")
    if pd.notna(prem_nhan):
        if prem_nhan < 8:
            ket_luan.append("🟢 Nhẫn trơn 9999 là lựa chọn hợp lý hơn miếng để TÍCH LŨY")
            can_cu.append(f"Nhẫn chỉ cao hơn thế giới {prem_nhan:.1f}% — rủi ro co chênh lệch thấp hơn miếng.")
        elif pd.notna(prem_sjc) and prem_nhan < prem_sjc:
            ket_luan.append("🟡 Nếu vẫn muốn tích lũy, ưu tiên NHẪN hơn MIẾNG")
            can_cu.append(f"Premium nhẫn ({prem_nhan:.1f}%) thấp hơn miếng ({prem_sjc:.1f}%).")

    # Quy tắc 2: xu hướng giá thế giới theo lịch sử đã lưu
    if hist is not None and len(hist) >= 10 and pd.notna(world):
        h = hist.dropna(subset=["gia_the_gioi_usd_oz"])
        if len(h) >= 10:
            ma10 = h["gia_the_gioi_usd_oz"].tail(10).mean()
            if world < ma10 * 0.98:
                ket_luan.append("🟡 Xu hướng thế giới đang YẾU — nếu mua, chia nhỏ nhiều đợt (DCA), không dồn 1 lần")
                can_cu.append(f"Giá hiện tại {world:,.0f} USD thấp hơn ~2% so trung bình 10 phiên ({ma10:,.0f} USD).")
            elif world > ma10 * 1.02:
                can_cu.append(f"Giá thế giới đang cao hơn trung bình 10 phiên ({ma10:,.0f} USD) — tránh mua đuổi.")
    else:
        can_cu.append("Chưa đủ lịch sử (cần ≥10 ngày dữ liệu) để đánh giá xu hướng — nhận định "
                      "xu hướng sẽ tự xuất hiện khi hệ thống tích lũy đủ dữ liệu.")

    if not ket_luan:
        ket_luan.append("🟡 Chưa đủ tín hiệu rõ ràng — nếu mục tiêu là tích lũy dài hạn, "
                        "DCA đều đặn khối lượng nhỏ vẫn là cách ít rủi ro thời điểm nhất")
    return ket_luan, can_cu


def tab_vang():
    snap_df = load_csv(GOLD_SNAP)
    hist = load_csv(GOLD_HIST)

    if snap_df is None or snap_df.empty:
        st.info("Chưa có dữ liệu vàng. Hệ thống tự động (B6-gold_tracker) sẽ tạo file "
                "'Bao_cao_vang.csv' sau lần chạy Actions đầu tiên có bước B6.")
        return
    snap = snap_df.iloc[0]

    st.caption(f"Cập nhật: {snap.get('cap_nhat_utc', '—')} UTC")
    c1, c2, c3, c4 = st.columns(4)
    if pd.notna(snap.get("gia_the_gioi_usd_oz")):
        c1.metric("🌍 Thế giới (USD/oz)", f"{snap['gia_the_gioi_usd_oz']:,.0f}")
    if pd.notna(snap.get("quy_doi_vnd_luong")):
        c2.metric("Quy đổi (đ/lượng)", f"{snap['quy_doi_vnd_luong']:,.0f}",
                  help="Giá thế giới × 1,20565 oz/lượng × tỷ giá USD/VND, chưa gồm thuế phí.")
    if pd.notna(snap.get("sjc_ban")):
        delta = f"+{snap['premium_sjc_pct']:.1f}% vs thế giới" if pd.notna(snap.get("premium_sjc_pct")) else None
        c3.metric("Miếng SJC (bán ra)", f"{snap['sjc_ban']:,.0f}", delta, delta_color="inverse")
    if pd.notna(snap.get("nhan_ban")):
        delta = f"+{snap['premium_nhan_pct']:.1f}% vs thế giới" if pd.notna(snap.get("premium_nhan_pct")) else None
        c4.metric("Nhẫn 9999 (bán ra)", f"{snap['nhan_ban']:,.0f}", delta, delta_color="inverse")

    # Biểu đồ lịch sử
    if hist is not None and len(hist) >= 2:
        st.subheader("Diễn biến giá")
        h = hist.copy()
        h["ngay"] = pd.to_datetime(h["ngay"])
        fig = go.Figure()
        if h["gia_the_gioi_usd_oz"].notna().any():
            fig.add_trace(go.Scatter(x=h["ngay"], y=h["quy_doi_vnd_luong"],
                                     name="Thế giới quy đổi", line=dict(dash="dot")))
        for col, name in [("sjc_ban", "Miếng SJC"), ("nhan_ban", "Nhẫn 9999")]:
            if col in h.columns and h[col].notna().any():
                fig.add_trace(go.Scatter(x=h["ngay"], y=h[col], name=name))
        fig.update_layout(height=350, yaxis_title="đồng/lượng", margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True)

    # Nhận định tự động
    st.subheader("🤖 Nhận định tự động (theo quy tắc, không phải lời khuyên tài chính)")
    ket_luan, can_cu = nhan_dinh_vang(snap, hist)
    for k in ket_luan:
        st.markdown(f"### {k}")
    with st.expander("Căn cứ số liệu của nhận định trên"):
        for c in can_cu:
            st.markdown(f"- {c}")
    st.warning("⚠️ Nhận định trên được máy tính sinh tự động từ các quy tắc chênh lệch giá và xu hướng "
               "— chỉ mang tính tham khảo, KHÔNG phải khuyến nghị đầu tư. Giá vàng chịu ảnh hưởng của "
               "nhiều yếu tố (Fed, tỷ giá, chính sách trong nước) mà quy tắc đơn giản không nắm bắt hết. "
               "Quyết định cuối cùng thuộc về bạn.")


# ============================================================
# BỐ CỤC CHÍNH — tự làm mới mỗi 10 phút
# ============================================================
st.title("📊 Chứng khoán & Vàng")


@st.fragment(run_every=600)
def noi_dung_chinh():
    tab_ck, tab_gold = st.tabs(["📈 Chứng khoán", "🥇 Vàng"])
    with tab_ck:
        tab_chung_khoan()
    with tab_gold:
        tab_vang()


noi_dung_chinh()
