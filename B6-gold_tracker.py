"""B6 - Thu thập dữ liệu VÀNG (thế giới + trong nước) cho dashboard.

Chạy trong GitHub Actions cùng lịch với B2/B3+B4. Ghi 2 file:
- Bao_cao_vang.csv   : ảnh chụp (snapshot) mới nhất
- lich_su_vang.csv   : lịch sử theo ngày (append, khử trùng lặp theo ngày)

Thiết kế chịu lỗi TỪNG PHẦN: mỗi nguồn (thế giới / tỷ giá / SJC / nhẫn BTMC)
được fetch độc lập trong try/except riêng - nguồn nào lỗi thì để trống (NaN),
các nguồn còn lại vẫn được ghi ra, KHÔNG làm sập cả job Actions.
"""
import os, sys, warnings
from datetime import datetime, timezone
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

warnings.filterwarnings("ignore")

SNAPSHOT_FILE = "Bao_cao_vang.csv"
HISTORY_FILE = "lich_su_vang.csv"
OZ_PER_LUONG = 1.20565  # 1 lượng = 37,5g = 1,20565 troy oz


def fetch_world_gold_usd_oz():
    """Giá vàng thế giới (USD/oz) qua yfinance - hợp đồng tương lai GC=F."""
    try:
        import yfinance as yf
        h = yf.Ticker("GC=F").history(period="5d")
        if h is not None and not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception as e:
        print(f"⚠️ Lỗi lấy giá vàng thế giới: {e}")
    return None


def fetch_usdvnd():
    """Tỷ giá USD/VND qua yfinance."""
    try:
        import yfinance as yf
        h = yf.Ticker("USDVND=X").history(period="5d")
        if h is not None and not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception as e:
        print(f"⚠️ Lỗi lấy tỷ giá USD/VND: {e}")
    return None


def _find_num(row, keywords):
    """Tìm giá trị số đầu tiên trong row có tên cột chứa 1 trong các keywords."""
    for col in row.index:
        cl = str(col).lower()
        if any(k in cl for k in keywords):
            try:
                v = float(str(row[col]).replace(",", "").replace(".", "")
                          if str(row[col]).count(".") > 1 else str(row[col]).replace(",", ""))
                if v > 0:
                    return v
            except (ValueError, TypeError):
                continue
    return None


def fetch_sjc():
    """Giá vàng miếng SJC (mua, bán) qua vnstock. Trả về (mua, bán) đồng/lượng."""
    try:
        from vnstock.explorer.misc.gold_price import sjc_gold_price
        df = sjc_gold_price()
        if df is not None and not df.empty:
            row = df.iloc[0]
            mua = _find_num(row, ["buy", "mua"])
            ban = _find_num(row, ["sell", "bán", "ban"])
            # Chuẩn hóa đơn vị về đồng/lượng nếu nguồn trả nghìn đồng
            if mua and mua < 1_000_000: mua *= 1000
            if ban and ban < 1_000_000: ban *= 1000
            return mua, ban
    except Exception as e:
        print(f"⚠️ Lỗi lấy giá SJC: {e}")
    return None, None


def fetch_nhan_btmc():
    """Giá nhẫn tròn trơn (BTMC) qua vnstock. Trả về (mua, bán) đồng/lượng."""
    try:
        from vnstock.explorer.misc.gold_price import btmc_goldprice
        df = btmc_goldprice()
        if df is not None and not df.empty:
            # Tìm dòng sản phẩm nhẫn tròn trơn
            name_col = None
            for c in df.columns:
                if any(k in str(c).lower() for k in ["name", "tên", "ten", "product"]):
                    name_col = c
                    break
            rows = df
            if name_col is not None:
                mask = df[name_col].astype(str).str.contains("nhẫn|nhan|tròn|tron", case=False, na=False)
                if mask.any():
                    rows = df[mask]
            row = rows.iloc[0]
            mua = _find_num(row, ["buy", "mua"])
            ban = _find_num(row, ["sell", "bán", "ban"])
            if mua and mua < 1_000_000: mua *= 1000
            if ban and ban < 1_000_000: ban *= 1000
            return mua, ban
    except Exception as e:
        print(f"⚠️ Lỗi lấy giá nhẫn BTMC: {e}")
    return None, None


def main():
    print("=== [B6] THU THẬP DỮ LIỆU VÀNG ===")
    now = datetime.now(timezone.utc)

    world = fetch_world_gold_usd_oz()
    usdvnd = fetch_usdvnd()
    sjc_mua, sjc_ban = fetch_sjc()
    nhan_mua, nhan_ban = fetch_nhan_btmc()

    quy_doi = None
    if world and usdvnd:
        quy_doi = world * OZ_PER_LUONG * usdvnd  # đồng/lượng, chưa gồm thuế phí

    def premium(gia_ban):
        if gia_ban and quy_doi:
            return round((gia_ban - quy_doi) / quy_doi * 100, 2)
        return None

    record = {
        "ngay": now.strftime("%Y-%m-%d"),
        "cap_nhat_utc": now.strftime("%Y-%m-%d %H:%M"),
        "gia_the_gioi_usd_oz": round(world, 2) if world else None,
        "ty_gia_usdvnd": round(usdvnd, 0) if usdvnd else None,
        "quy_doi_vnd_luong": round(quy_doi, 0) if quy_doi else None,
        "sjc_mua": sjc_mua, "sjc_ban": sjc_ban,
        "nhan_mua": nhan_mua, "nhan_ban": nhan_ban,
        "premium_sjc_pct": premium(sjc_ban),
        "premium_nhan_pct": premium(nhan_ban),
    }

    snap = pd.DataFrame([record])
    snap.to_csv(SNAPSHOT_FILE, index=False, encoding="utf-8-sig")
    print(f"✅ Đã ghi snapshot: {SNAPSHOT_FILE}")
    print(snap.to_string(index=False))

    # Append lịch sử, khử trùng lặp theo ngày (giữ bản mới nhất trong ngày)
    if os.path.exists(HISTORY_FILE):
        hist = pd.read_csv(HISTORY_FILE)
        hist = pd.concat([hist, snap], ignore_index=True)
        hist = hist.drop_duplicates(subset=["ngay"], keep="last")
    else:
        hist = snap
    hist.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
    print(f"✅ Đã cập nhật lịch sử: {HISTORY_FILE} ({len(hist)} ngày)")

    # Cảnh báo minh bạch nguồn nào lỗi
    missing = [k for k, v in record.items() if v is None and k not in ("ngay", "cap_nhat_utc")]
    if missing:
        print(f"⚠️ Các trường KHÔNG lấy được hôm nay (nguồn lỗi/thay đổi cấu trúc): {', '.join(missing)}")


if __name__ == "__main__":
    main()
