"""
Dashboard tổng hợp toàn pipeline sàng lọc cổ phiếu B1 → B2/B3 → B4 → B5.

Đọc các file CSV trung gian do từng bước sinh ra:
- B1:    Bao_cao_FA_AI.csv     (lọc cơ bản FA toàn thị trường)
- B2/B3: Bao_cao_B3.csv        (lọc kỹ thuật trend/thanh khoản/biến động)
- B4:    Bao_cao_B4_Final.csv  (chấm điểm TA tổng hợp)
- B5:    tính trực tiếp trong dashboard (bộ lọc rủi ro + phân bổ tỷ trọng)

Chạy: streamlit run dashboard_pipeline.py
Thiếu file nào, tab tương ứng sẽ báo rõ — không làm sập toàn dashboard.
"""
import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Pipeline Sàng Lọc Cổ Phiếu B1→B5", layout="wide")

FILES = {
    "B1": "Bao_cao_FA_AI.csv",
    "B3": "Bao_cao_B3.csv",
    "B4": "Bao_cao_B4_Final.csv",
}

# Ngưỡng mặc định của B5 (đồng bộ với B5-portfolio_execution.py)
B5_DEFAULTS = dict(de_max=0.5, pe_max=15, roe_min=15, growth_min=20,
                   price_min=10000, rsi_max=65, growth_flag=100, max_weight=0.45)


def load_csv(path):
    """Đọc CSV có cache, nhưng khóa cache gồm cả mtime file - nếu nội dung file
    đổi (do GitHub Actions commit CSV mới), cache tự vô hiệu mà KHÔNG cần
    reboot app theo cách thủ công, miễn là container đã pull code/data mới."""
    if not os.path.exists(path):
        return None
    return _load_csv_cached(path, os.path.getmtime(path))


@st.cache_data
def _load_csv_cached(path, _mtime):
    return pd.read_csv(path)


def file_mtime(path):
    if not os.path.exists(path):
        return "—"
    from datetime import datetime
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d/%m/%Y %H:%M")


df_b1 = load_csv(FILES["B1"])
df_b3 = load_csv(FILES["B3"])
df_b4 = load_csv(FILES["B4"])

st.title("🔬 Dashboard Pipeline Sàng Lọc Cổ Phiếu B1 → B5")

# ============================================================
# HELPER: CHẾ ĐỘ HIỂN THỊ CHO NGƯỜI KHÔNG CHUYÊN
# ============================================================
# Bật/tắt ở sidebar: khi bật (mặc định), dashboard chỉ hiện cột cốt lõi,
# đổi tên cột sang ngôn ngữ dễ hiểu và tô màu trực quan.
che_do_don_gian = st.sidebar.toggle(
    "👶 Chế độ dễ hiểu (cho người không chuyên)", value=True,
    help="Bật: ẩn bớt chỉ số kỹ thuật, đổi tên cột dễ hiểu, tô màu trực quan. "
         "Tắt: hiện đầy đủ mọi chỉ số cho người chuyên.")

# Tên cột kỹ thuật -> tên thân thiện (kèm gợi ý ngắn ngay trong tên)
TEN_THAN_THIEN = {
    "Mã CK": "Mã CP",
    "ROE Năm (%)": "Sinh lời vốn (ROE %)",
    "Tăng trưởng LNST (%)": "Tăng trưởng lợi nhuận (%)",
    "P/E": "Độ đắt/rẻ (P/E)",
    "D/E": "Mức vay nợ (D/E)",
    "RSI": "Nóng/nguội (RSI)",
    "Giá hiện tại": "Giá hiện tại (đ)",
    "Chiết khấu từ đỉnh (%)": "Giảm so với đỉnh (%)",
    "Điểm sức mạnh": "Điểm tổng",
    "Total_Score": "Điểm tổng",
    "Tỷ trọng (%)": "Nên mua bao nhiêu (%)",
    "Tỷ_trọng_đề_xuất_%": "Nên mua bao nhiêu (%)",
    "Xu hướng DI": "Xu hướng",
}

# Cột chỉ giữ khi ở chế độ chuyên (ẩn trong chế độ dễ hiểu)
COT_KY_THUAT = ["ADX", "D/E", "Xu hướng DI", "Giá_rescale_x1000", "ATR", "+DI", "-DI",
                "Quality_Score", "Value_Score", "Technical_Score", "RSI_Distance",
                "Tăng_trưởng_YoY_thật", "ROE_TTM_thật", "Cảnh_báo_growth_QoQ",
                "Cảnh_báo_ROE_x4", "Cảnh_báo_thanh_khoản(proxy)"]

# Cột cốt lõi (thứ tự ưu tiên) khi ở chế độ dễ hiểu
COT_COT_LOI = ["Mã CK", "Total_Score", "Điểm sức mạnh", "Tỷ trọng (%)", "Tỷ_trọng_đề_xuất_%",
               "ROE Năm (%)", "Tăng trưởng LNST (%)", "P/E", "RSI",
               "Giá hiện tại", "Chiết khấu từ đỉnh (%)"]


def chuan_bi_bang(df, don_gian):
    """Trả về (dataframe hiển thị, styler). Ẩn cột kỹ thuật + đổi tên nếu chế độ dễ hiểu."""
    d = df.copy()
    # Luôn bỏ cột YoY kỹ thuật khỏi hiển thị (theo yêu cầu người dùng)
    for bo in ["Tăng_trưởng_YoY_thật", "ROE_TTM_thật"]:
        if bo in d.columns:
            d = d.drop(columns=bo)

    if don_gian:
        giu = [c for c in COT_COT_LOI if c in d.columns]
        # thêm các cột còn lại không thuộc nhóm kỹ thuật (để không mất dữ liệu quan trọng)
        giu += [c for c in d.columns if c not in giu and c not in COT_KY_THUAT]
        d = d[[c for c in giu if c in d.columns]]
        d = d.rename(columns={k: v for k, v in TEN_THAN_THIEN.items() if k in d.columns})

    return d


def to_mau_bang(styler, df_goc):
    """Tô màu trực quan: xanh = tốt, đỏ = cần chú ý. Dựa trên cột gốc trước khi đổi tên."""
    def mau_rsi(v):
        try:
            v = float(v)
        except (ValueError, TypeError):
            return ""
        if v > 70:
            return "background-color: #ffd6d6"   # quá nóng (quá mua) - đỏ nhạt
        if v < 35:
            return "background-color: #fff3cd"   # nguội - vàng nhạt
        return "background-color: #d6f5d6"       # vùng đẹp - xanh nhạt

    def mau_giam_dinh(v):
        try:
            v = float(v)
        except (ValueError, TypeError):
            return ""
        return "background-color: #d6f5d6" if v >= 10 else ""  # giảm sâu so đỉnh = cơ hội

    for ten in ["Nóng/nguội (RSI)", "RSI"]:
        if ten in styler.columns:
            styler = styler.map(mau_rsi, subset=[ten])
    for ten in ["Giảm so với đỉnh (%)", "Chiết khấu từ đỉnh (%)"]:
        if ten in styler.columns:
            styler = styler.map(mau_giam_dinh, subset=[ten])
    return styler


tab_overview, tab_b1, tab_b3, tab_b4, tab_b5 = st.tabs(
    ["📈 Tổng quan", "1️⃣ Lọc doanh nghiệp tốt", "2️⃣ Lọc xu hướng giá",
     "3️⃣ Chấm điểm & xếp hạng", "4️⃣ Gợi ý danh mục mua"])

# ============================================================
# TAB TỔNG QUAN: PHỄU LỌC (FUNNEL)
# ============================================================
with tab_overview:
    if che_do_don_gian:
        st.info("**Cách đọc dashboard này:** Pipeline lọc cổ phiếu qua 4 bước như một cái phễu — "
                "từ hàng nghìn mã trên sàn, lọc dần còn vài mã tốt nhất để cân nhắc mua.\n\n"
                "• **Bước 1** — Giữ lại doanh nghiệp làm ăn tốt (lãi cao, ít nợ, giá hợp lý)\n"
                "• **Bước 2** — Giữ mã đang trong xu hướng giá lên, thanh khoản tốt\n"
                "• **Bước 3** — Chấm điểm & xếp hạng các mã còn lại\n"
                "• **Bước 4** — Gợi ý danh mục nên mua + tỷ trọng từng mã\n\n"
                "🟢 Ô xanh = tín hiệu tốt  •  🟡 Ô vàng = bình thường/lưu ý  •  🔴 Ô đỏ = cần thận trọng")

    st.subheader("Phễu sàng lọc qua từng bước")

    counts, labels = [], []
    if df_b1 is not None:
        counts.append(len(df_b1)); labels.append(f"B1 - Đạt lọc FA ({len(df_b1)})")
    if df_b3 is not None:
        counts.append(len(df_b3)); labels.append(f"B2/B3 - Đạt lọc TA ({len(df_b3)})")
    if df_b4 is not None:
        counts.append(len(df_b4)); labels.append(f"B4 - Được chấm điểm ({len(df_b4)})")

    if counts:
        fig = go.Figure(go.Funnel(y=labels, x=counts, textinfo="value+percent initial"))
        fig.update_layout(height=350, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Chưa có file CSV nào. Hãy chạy pipeline B1 → B4 trước, sau đó đặt các file "
                   "CSV cùng thư mục với dashboard này.")

    st.subheader("Trạng thái dữ liệu")
    status_rows = []
    for step, fname in FILES.items():
        df = {"B1": df_b1, "B3": df_b3, "B4": df_b4}[step]
        status_rows.append({
            "Bước": step,
            "File": fname,
            "Trạng thái": "✅ Có" if df is not None else "❌ Thiếu",
            "Số mã": len(df) if df is not None else "—",
            "Cập nhật lần cuối": file_mtime(fname),
        })
    st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)
    st.caption("🤖 Dữ liệu được tự động cập nhật qua GitHub Actions theo lịch (B2/B3 + B4 các tối "
               "thứ 2–6, B1 tối Chủ nhật) — không cần chạy tay hay upload CSV thủ công. "
               "Cột 'Cập nhật lần cuối' cho biết lần Actions chạy gần nhất; nếu cũ hơn phiên giao "
               "dịch gần nhất, kiểm tra tab Actions trên GitHub xem job có lỗi không.")

# ============================================================
# TAB B1: LỌC FA
# ============================================================
with tab_b1:
    st.subheader("Bước 1 — Lọc ra doanh nghiệp làm ăn tốt")
    if df_b1 is None:
        st.info(f"Chưa có file '{FILES['B1']}'. Chạy B1-filter_fa để tạo.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Số mã đạt lọc FA", len(df_b1))
        c2.metric("ROE trung bình", f"{df_b1['ROE Năm (%)'].mean():.1f}%")
        c3.metric("P/E trung bình", f"{pd.to_numeric(df_b1['P/E'], errors='coerce').mean():.1f}")

        d_b1 = chuan_bi_bang(df_b1, che_do_don_gian)
        if che_do_don_gian:
            st.dataframe(to_mau_bang(d_b1.style, df_b1), use_container_width=True, height=350)
        else:
            st.dataframe(d_b1, use_container_width=True, height=350)

        fig = px.histogram(df_b1, x="ROE Năm (%)", nbins=20, title="Phân bố ROE các mã đạt lọc")
        st.plotly_chart(fig, use_container_width=True)

# ============================================================
# TAB B2/B3: LỌC KỸ THUẬT
# ============================================================
with tab_b3:
    st.subheader("Bước 2 — Lọc mã đang trong xu hướng giá lên")
    if df_b3 is None:
        st.info(f"Chưa có file '{FILES['B3']}'. Chạy B2_B3-trend_health để tạo.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Số mã vượt lọc", len(df_b3))
        if df_b1 is not None and len(df_b1) > 0:
            rate = len(df_b3) / len(df_b1) * 100
            c2.metric("Tỷ lệ vượt so với bước 1", f"{rate:.0f}%")
        d_b3 = chuan_bi_bang(df_b3, che_do_don_gian)
        if che_do_don_gian:
            st.dataframe(to_mau_bang(d_b3.style, df_b3), use_container_width=True, height=350)
        else:
            st.dataframe(d_b3, use_container_width=True, height=350)
        st.caption("Các mã ở đây đều đang có giá nằm trên đường trung bình dài hạn (xu hướng lên), "
                   "thanh khoản đủ tốt và biến động không quá mạnh.")

# ============================================================
# TAB B4: CHẤM ĐIỂM TA
# ============================================================
with tab_b4:
    st.subheader("Bước 3 — Chấm điểm & xếp hạng các mã còn lại")
    if df_b4 is None:
        st.info(f"Chưa có file '{FILES['B4']}'. Chạy B4-ranking_prestige để tạo.")
    else:
        sort_col = "Điểm sức mạnh" if "Điểm sức mạnh" in df_b4.columns else df_b4.columns[-1]
        df_view = df_b4.sort_values(by=sort_col, ascending=False)

        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(df_view.head(15), x=sort_col, y="Mã CK", orientation="h",
                         color="Chiết khấu từ đỉnh (%)" if "Chiết khấu từ đỉnh (%)" in df_view.columns else None,
                         color_continuous_scale="Blues", title="Top 15 mã điểm cao nhất")
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig2 = px.scatter(df_view, x="RSI", y="Chiết khấu từ đỉnh (%)",
                              size=df_view["ADX"].clip(lower=1), hover_name="Mã CK",
                              color=sort_col, color_continuous_scale="Viridis",
                              title="Bản đồ: mức nóng/nguội vs mức giảm so đỉnh")
            fig2.add_vline(x=65, line_dash="dash", line_color="red",
                           annotation_text="Ngưỡng quá nóng")
            st.plotly_chart(fig2, use_container_width=True)

        d_b4 = chuan_bi_bang(df_view, che_do_don_gian)
        if che_do_don_gian:
            st.dataframe(to_mau_bang(d_b4.style, df_view), use_container_width=True, height=300)
        else:
            st.dataframe(d_b4, use_container_width=True, height=300)
        st.caption("Điểm cao chưa chắc đã được chọn mua — bước 4 còn loại thêm các mã rủi ro "
                   "(nợ bất thường, tăng trưởng ảo...). Xem tab tiếp theo để có danh sách cuối cùng.")

# ============================================================
# TAB B5: BỘ LỌC RỦI RO + DANH MỤC (tính trực tiếp)
# ============================================================
with tab_b5:
    st.subheader("Bước 4 — Gợi ý danh mục nên mua & tỷ trọng")
    if df_b4 is None:
        st.info("Cần dữ liệu bước 3 để tạo gợi ý danh mục.")
    else:
        st.sidebar.header("⚙️ Ngưỡng lọc (chỉnh trực tiếp)")
        de_max = st.sidebar.slider("Mức vay nợ tối đa (D/E)", 0.0, 2.0, B5_DEFAULTS["de_max"], 0.05)
        pe_max = st.sidebar.slider("Độ đắt tối đa (P/E)", 5, 30, B5_DEFAULTS["pe_max"])
        roe_min = st.sidebar.slider("Sinh lời vốn tối thiểu (ROE %)", 0, 40, B5_DEFAULTS["roe_min"])
        growth_min = st.sidebar.slider("Tăng trưởng lợi nhuận tối thiểu (%)", 0, 200, B5_DEFAULTS["growth_min"])
        rsi_max = st.sidebar.slider("Độ nóng tối đa (RSI)", 30, 90, B5_DEFAULTS["rsi_max"])
        price_min = st.sidebar.number_input("Giá tối thiểu (đ)", value=B5_DEFAULTS["price_min"], step=1000)
        max_weight = st.sidebar.slider("Trần tỷ trọng mỗi mã", 0.2, 1.0, B5_DEFAULTS["max_weight"], 0.05)

        df = df_b4.copy()

        # Audit loại trừ — tái hiện logic B5 kèm lý do minh bạch
        exclusions = {}
        def exclude(mask, reason):
            removed = df[mask]["Mã CK"].tolist()
            if removed:
                exclusions[reason] = removed
            return df[~mask]

        df = exclude(df["D/E"].isna(), "Không có số liệu nợ (thường là ngân hàng — cần cách đánh giá riêng)")
        df = exclude(df["D/E"] < 0, "Nợ âm bất thường (có thể lỗi dữ liệu — cần kiểm tra lại)")
        df = exclude(df["D/E"] > de_max, f"Vay nợ quá cao (D/E > {de_max})")
        df = exclude((df["P/E"] <= 0) | (df["P/E"] > pe_max), f"Giá quá đắt (P/E ngoài khoảng 0–{pe_max})")
        df = exclude(df["ROE Năm (%)"] < roe_min, f"Sinh lời vốn thấp (ROE < {roe_min}%)")
        df = exclude(df["Tăng trưởng LNST (%)"] < growth_min, f"Tăng trưởng thấp (< {growth_min}%)")
        df = exclude(df["Giá hiện tại"] < price_min, f"Giá quá thấp (< {price_min:,.0f}đ)")
        df = exclude(df["RSI"] > rsi_max, f"Giá đang quá nóng (RSI > {rsi_max})")

        if df.empty:
            st.warning("Không mã nào đạt chuẩn với ngưỡng hiện tại — nên ưu tiên giữ tiền mặt, chờ cơ hội tốt hơn.")
        else:
            # Scoring giống B5: 40% Value + 40% Quality + 20% Technical
            df["Quality_Score"] = df["ROE Năm (%)"].rank(pct=True) * 100
            df["Value_Score"] = df["P/E"].rank(pct=True, ascending=False) * 100
            rsi_comp = abs(df["RSI"] - 40).rank(pct=True, ascending=False) * 100
            if "Chiết khấu từ đỉnh (%)" in df.columns:
                disc_comp = df["Chiết khấu từ đỉnh (%)"].rank(pct=True) * 100
                df["Technical_Score"] = rsi_comp * 0.5 + disc_comp * 0.5
            else:
                df["Technical_Score"] = rsi_comp
            df["Total_Score"] = df["Value_Score"]*0.4 + df["Quality_Score"]*0.4 + df["Technical_Score"]*0.2

            top = df.sort_values("Total_Score", ascending=False).head(5).copy()
            raw_w = top["Total_Score"] / top["Total_Score"].sum()
            capped = raw_w.clip(upper=max_weight)
            top["Tỷ trọng (%)"] = (capped / capped.sum() * 100).round(1)
            top["⚠️ Cần kiểm tra"] = top["Tăng trưởng LNST (%)"] > B5_DEFAULTS["growth_flag"]

            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown("**🏆 Danh mục gợi ý mua**")
                if che_do_don_gian:
                    cols = ["Mã CK", "Total_Score", "Tỷ trọng (%)", "ROE Năm (%)",
                            "Tăng trưởng LNST (%)", "P/E", "RSI", "Giá hiện tại", "⚠️ Cần kiểm tra"]
                    show = top[[c for c in cols if c in top.columns]].round(1)
                    show = show.rename(columns={k: v for k, v in TEN_THAN_THIEN.items() if k in show.columns})
                    st.dataframe(to_mau_bang(show.style, top).format(precision=1),
                                 use_container_width=True, hide_index=True)
                else:
                    cols = ["Mã CK", "Total_Score", "P/E", "D/E", "ROE Năm (%)",
                            "Tăng trưởng LNST (%)", "RSI", "Giá hiện tại", "Tỷ trọng (%)",
                            "⚠️ Cần kiểm tra"]
                    st.dataframe(top[cols].round(1), use_container_width=True, hide_index=True)
                if che_do_don_gian:
                    st.caption("**Nên mua bao nhiêu (%)** = gợi ý tỷ trọng vốn cho mỗi mã. "
                               "🟢 xanh = tín hiệu tốt, 🔴 đỏ = đang nóng nên thận trọng, "
                               "⚠️ = số tăng trưởng cao bất thường, nên kiểm tra lại báo cáo tài chính.")
            with c2:
                fig = px.pie(top, values="Tỷ trọng (%)", names="Mã CK", hole=0.45,
                             title="Nên chia vốn thế nào")
                st.plotly_chart(fig, use_container_width=True)

        with st.expander("📋 Vì sao các mã khác bị loại (bấm để xem)"):
            if exclusions:
                for reason, codes in exclusions.items():
                    st.markdown(f"- **{reason}**: {', '.join(codes)}")
            else:
                st.write("Không mã nào bị loại.")

st.divider()
st.info("Dashboard này trực quan hóa kết quả pipeline sàng lọc — KHÔNG phải khuyến nghị đầu tư. "
        "Mã bị gắn cờ tăng trưởng bất thường cần đối chiếu BCTC gốc trước khi tin số liệu. "
        "Luôn kiểm tra ngày cập nhật dữ liệu ở tab Tổng quan.")
