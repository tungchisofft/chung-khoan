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

@st.cache_data
def load_csv(path):
    if not os.path.exists(path):
        return None
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
# TAB LAYOUT
# ============================================================
tab_overview, tab_b1, tab_b3, tab_b4, tab_b5 = st.tabs(
    ["📈 Tổng quan Pipeline", "1️⃣ B1 - Lọc FA", "2️⃣ B2/B3 - Lọc TA",
     "3️⃣ B4 - Chấm điểm", "4️⃣ B5 - Danh mục"])

# ============================================================
# TAB TỔNG QUAN: PHỄU LỌC (FUNNEL)
# ============================================================
with tab_overview:
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
    st.caption("⚠️ Kiểm tra cột 'Cập nhật lần cuối' — nếu dữ liệu cũ hơn phiên giao dịch gần nhất, "
               "kết quả bên dưới KHÔNG phản ánh giá/RSI hiện tại. Chạy lại pipeline trước khi ra quyết định.")

# ============================================================
# TAB B1: LỌC FA
# ============================================================
with tab_b1:
    st.subheader("B1 — Kết quả lọc cơ bản (FA) toàn thị trường")
    if df_b1 is None:
        st.info(f"Chưa có file '{FILES['B1']}'. Chạy B1-filter_fa để tạo.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Số mã đạt lọc FA", len(df_b1))
        c2.metric("ROE trung bình", f"{df_b1['ROE Năm (%)'].mean():.1f}%")
        c3.metric("P/E trung bình", f"{pd.to_numeric(df_b1['P/E'], errors='coerce').mean():.1f}")

        # Cột đánh dấu YoY (chỉ có ở bản B1 đã sửa lỗi)
        if "Tăng_trưởng_YoY_thật" in df_b1.columns:
            n_qoq = (~df_b1["Tăng_trưởng_YoY_thật"].astype(str).str.lower().eq("true")).sum()
            if n_qoq > 0:
                st.warning(f"⚠️ {n_qoq} mã có tăng trưởng tính theo QoQ (fallback, không đủ 5 quý) "
                           "— con số tăng trưởng của các mã này cần thận trọng hơn.")
        else:
            st.warning("⚠️ File B1 này được tạo bởi bản CŨ (trước khi sửa lỗi QoQ→YoY). "
                       "Tăng trưởng LNST có thể bị méo bởi so sánh quý liền trước. Nên chạy lại B1 bản mới.")

        st.dataframe(df_b1, use_container_width=True, height=350)

        fig = px.histogram(df_b1, x="ROE Năm (%)", nbins=20, title="Phân bố ROE các mã đạt lọc")
        st.plotly_chart(fig, use_container_width=True)

# ============================================================
# TAB B2/B3: LỌC KỸ THUẬT
# ============================================================
with tab_b3:
    st.subheader("B2/B3 — Kết quả lọc kỹ thuật (Trend / Thanh khoản / Biến động)")
    if df_b3 is None:
        st.info(f"Chưa có file '{FILES['B3']}'. Chạy B2_B3-trend_health để tạo.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Số mã vượt lọc TA", len(df_b3))
        if df_b1 is not None and len(df_b1) > 0:
            rate = len(df_b3) / len(df_b1) * 100
            c2.metric("Tỷ lệ vượt so với B1", f"{rate:.0f}%")
        st.dataframe(df_b3, use_container_width=True, height=350)
        st.caption("Các mã trong bảng đã thỏa: Giá > MA200, thanh khoản và biến động trong ngưỡng "
                   "kịch bản thị trường (BULL/NEUTRAL/BEAR) tại thời điểm chạy B2/B3.")

# ============================================================
# TAB B4: CHẤM ĐIỂM TA
# ============================================================
with tab_b4:
    st.subheader("B4 — Chấm điểm kỹ thuật tổng hợp (ADX / RSI / Chiết khấu đỉnh)")
    if df_b4 is None:
        st.info(f"Chưa có file '{FILES['B4']}'. Chạy B4-ranking_prestige để tạo.")
    else:
        sort_col = "Điểm sức mạnh" if "Điểm sức mạnh" in df_b4.columns else df_b4.columns[-1]
        df_view = df_b4.sort_values(by=sort_col, ascending=False)

        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(df_view.head(15), x=sort_col, y="Mã CK", orientation="h",
                         color="Chiết khấu từ đỉnh (%)" if "Chiết khấu từ đỉnh (%)" in df_view.columns else None,
                         color_continuous_scale="Blues", title="Top 15 theo Điểm sức mạnh")
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig2 = px.scatter(df_view, x="RSI", y="Chiết khấu từ đỉnh (%)",
                              size=df_view["ADX"].clip(lower=1), hover_name="Mã CK",
                              color=sort_col, color_continuous_scale="Viridis",
                              title="Bản đồ vị thế: RSI vs Chiết khấu từ đỉnh")
            fig2.add_vline(x=65, line_dash="dash", line_color="red",
                           annotation_text="Ngưỡng quá mua B5")
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(df_view, use_container_width=True, height=300)
        st.caption("Điểm ở đây là điểm TA thuần của B4. Mã điểm cao vẫn có thể bị B5 loại "
                   "vì lý do cơ bản (D/E âm, tăng trưởng méo...). Xem tab B5 để có kết quả cuối.")

# ============================================================
# TAB B5: BỘ LỌC RỦI RO + DANH MỤC (tính trực tiếp)
# ============================================================
with tab_b5:
    st.subheader("B5 — Bộ lọc rủi ro tuyệt đối & Danh mục đề xuất")
    if df_b4 is None:
        st.info("Cần file B4 để chạy logic B5.")
    else:
        st.sidebar.header("⚙️ Ngưỡng B5 (chỉnh trực tiếp)")
        de_max = st.sidebar.slider("D/E tối đa", 0.0, 2.0, B5_DEFAULTS["de_max"], 0.05)
        pe_max = st.sidebar.slider("P/E tối đa", 5, 30, B5_DEFAULTS["pe_max"])
        roe_min = st.sidebar.slider("ROE tối thiểu (%)", 0, 40, B5_DEFAULTS["roe_min"])
        growth_min = st.sidebar.slider("Tăng trưởng tối thiểu (%)", 0, 200, B5_DEFAULTS["growth_min"])
        rsi_max = st.sidebar.slider("RSI tối đa", 30, 90, B5_DEFAULTS["rsi_max"])
        price_min = st.sidebar.number_input("Giá tối thiểu (đ)", value=B5_DEFAULTS["price_min"], step=1000)
        max_weight = st.sidebar.slider("Trần tỷ trọng/mã", 0.2, 1.0, B5_DEFAULTS["max_weight"], 0.05)

        df = df_b4.copy()

        # Audit loại trừ — tái hiện logic B5 kèm lý do minh bạch
        exclusions = {}
        def exclude(mask, reason):
            removed = df[mask]["Mã CK"].tolist()
            if removed:
                exclusions[reason] = removed
            return df[~mask]

        df = exclude(df["D/E"].isna(), "D/E rỗng (khả năng ngân hàng — cần mô hình riêng)")
        df = exclude(df["D/E"] < 0, "D/E âm (vốn chủ âm thực HOẶC lỗi dữ liệu — đối chiếu BCTC)")
        df = exclude(df["D/E"] > de_max, f"D/E > {de_max}")
        df = exclude((df["P/E"] <= 0) | (df["P/E"] > pe_max), f"P/E ngoài (0, {pe_max}]")
        df = exclude(df["ROE Năm (%)"] < roe_min, f"ROE < {roe_min}%")
        df = exclude(df["Tăng trưởng LNST (%)"] < growth_min, f"Tăng trưởng < {growth_min}%")
        df = exclude(df["Giá hiện tại"] < price_min, f"Giá < {price_min:,.0f}đ")
        df = exclude(df["RSI"] > rsi_max, f"RSI > {rsi_max} (quá mua)")

        if df.empty:
            st.warning("Không mã nào đạt chuẩn với ngưỡng hiện tại — hệ thống ưu tiên bảo vệ vốn.")
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
            top["⚠️ Tăng trưởng bất thường"] = top["Tăng trưởng LNST (%)"] > B5_DEFAULTS["growth_flag"]

            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown("**🏆 Danh mục đề xuất (conviction-weighted)**")
                cols = ["Mã CK", "Total_Score", "P/E", "D/E", "ROE Năm (%)",
                        "Tăng trưởng LNST (%)", "RSI", "Giá hiện tại", "Tỷ trọng (%)",
                        "⚠️ Tăng trưởng bất thường"]
                st.dataframe(top[cols].round(1), use_container_width=True, hide_index=True)
            with c2:
                fig = px.pie(top, values="Tỷ trọng (%)", names="Mã CK", hole=0.45,
                             title="Phân bổ tỷ trọng đề xuất")
                st.plotly_chart(fig, use_container_width=True)

        with st.expander("📋 Nhật ký loại trừ (audit log) — vì sao từng mã bị loại"):
            if exclusions:
                for reason, codes in exclusions.items():
                    st.markdown(f"- **{reason}**: {', '.join(codes)}")
            else:
                st.write("Không mã nào bị loại.")

st.divider()
st.info("Dashboard này trực quan hóa kết quả pipeline sàng lọc — KHÔNG phải khuyến nghị đầu tư. "
        "Mã bị gắn cờ tăng trưởng bất thường cần đối chiếu BCTC gốc trước khi tin số liệu. "
        "Luôn kiểm tra ngày cập nhật dữ liệu ở tab Tổng quan.")
