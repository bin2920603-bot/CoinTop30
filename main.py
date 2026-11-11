import os, io, time, requests
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec

BARS = [("1D", "1D"), ("4H", "4H"), ("1H", "1H"), ("15m", "15m")]
COUNT = 30
SHOW = 120
TOKEN = os.environ["TG_TOKEN"]
OKX = "https://www.okx.com"

def num(v):
    try:
        return float(v)
    except Exception:
        return 0.0

def find_chat():
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                     params={"limit": 100}, timeout=20).json()
    if not r.get("ok"):
        print("[텔레그램 getUpdates 실패]", r.get("error_code"), r.get("description"))
    seen = {}
    for u in r.get("result", []):
        for k in ("message", "my_chat_member", "channel_post", "edited_message"):
            c = u.get(k, {}).get("chat")
            if c:
                seen[str(c["id"])] = (c.get("type"), c.get("title") or c.get("first_name"))
    print("[봇이 아는 방]", seen)
    for u in reversed(r.get("result", [])):
        for k in ("message", "my_chat_member", "channel_post"):
            c = u.get(k, {}).get("chat")
            if c and c.get("type") in ("group", "supergroup"):
                print("[찾은 방]", c["id"], c.get("title"))
                return str(c["id"])
    raise SystemExit("방을 못 찾았어요. 방에 /start@tajeom_top30_bot 을 다시 보내주세요")

CHAT = os.environ.get("TG_CHAT") or find_chat()

POOL = 100  # 24h 거래대금 상위 100개 중에서 급증 코인을 고름

def top_coins():
    data = requests.get(OKX + "/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=20).json()["data"]
    rows = []
    for t in data:
        if t["instId"].endswith("-USDT-SWAP"):
            v = num(t.get("volCcy24h")) * num(t.get("last"))
            if v > 0:
                rows.append((v, t["instId"]))
    rows.sort(reverse=True)
    out = []
    for v, inst in rows[:COUNT]:
        try:
            d = requests.get(OKX + "/api/v5/market/candles",
                             params={"instId": inst, "bar": "1H", "limit": 26}, timeout=20).json()["data"]
            vols = [num(x[5]) for x in d]  # 최신이 앞
            last, prev = vols[1], vols[2:26]  # 방금 끝난 1시간봉 vs 그 전 24시간 평균
            avg = sum(prev) / len(prev) if prev else 0
            if avg > 0:
                out.append((last / avg, inst, v))
        except Exception:
            pass
        time.sleep(0.12)
    out.sort(key=lambda x: -x[2])
    return out[:COUNT]

def candles(inst, bar):
    for _ in range(3):
        try:
            d = requests.get(OKX + "/api/v5/market/candles",
                             params={"instId": inst, "bar": bar, "limit": 300}, timeout=20).json()["data"]
            d = d[::-1]
            a = np.array([[num(x[1]), num(x[2]), num(x[3]), num(x[4]), num(x[5]), num(x[6]), num(x[0])] for x in d])
            return a  # o h l c vol volCcy ts(밀리초)
        except Exception:
            time.sleep(1)
    return None

def ema(x, n):
    out = np.zeros(len(x)); k = 2 / (n + 1); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out

def rsi(c, n=14):
    out = np.full(len(c), 50.0)
    if len(c) <= n:
        return out
    d = np.diff(c)
    g = np.where(d > 0, d, 0); l = np.where(d < 0, -d, 0)
    ag = g[:n].mean(); al = l[:n].mean()
    for i in range(n, len(c)):
        if i > n:
            ag = (ag * (n - 1) + g[i - 1]) / n
            al = (al * (n - 1) + l[i - 1]) / n
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

LINES = [("EMA7", 7, "#e91e8c"), ("EMA10", 10, "#29b6f6"), ("EMA20", 20, "#e0a800"),
         ("EMA50", 50, "#2e9e44"), ("EMA120", 120, "#8a8a8a"), ("EMA200", 200, "#e53935")]
VW_COLOR = "#000000"

def vwap100(a):
    tp = (a[:, 1] + a[:, 2] + a[:, 3]) / 3
    w = a[:, 5]
    out = np.full(len(a), np.nan)
    for i in range(99, len(a)):
        sw = w[i - 99:i + 1].sum()
        if sw > 0:
            out[i] = (tp[i - 99:i + 1] * w[i - 99:i + 1]).sum() / sw
    return out

# ---------------- 추세선 (노란색) ----------------
TREND_EXT = 20        # 추세선을 오른쪽으로 몇 봉 더 늘려 그릴지
TREND_K = 2           # 좌우 몇 봉보다 높아야(낮아야) 고점(저점)으로 볼지
TREND_TOL = 0.03      # 꼬리가 선을 넘어도 봐주는 여유 (차트 높이의 3%)
TREND_BAD = 1         # 선을 넘은 봉이 이 개수 이하면 인정
TREND_MIN_GAP = 8     # 선을 긋는 두 점 사이 최소 봉 수
TREND_COLOR = "#FFC107"

def find_swings(vals, k, high=True):
    out = []
    for i in range(k, len(vals) - k):
        window = vals[i - k:i + k + 1]
        if (high and vals[i] == max(window)) or ((not high) and vals[i] == min(window)):
            out.append(i)
    return out

def find_trendline(a, kind):
    n = len(a)
    highs = list(a[:, 1]); lows = list(a[:, 2])
    tol = TREND_TOL * (max(highs) - min(lows))
    if kind == "down":
        vals = highs
        swings = find_swings(vals, TREND_K, True)
    else:
        vals = lows
        swings = find_swings(vals, TREND_K, False)
    best = None
    for b in swings[-4:]:
        for s0 in swings:
            if b - s0 < TREND_MIN_GAP:
                break
            if kind == "down" and vals[s0] <= vals[b]:
                continue
            if kind == "up" and vals[s0] >= vals[b]:
                continue
            slope = (vals[b] - vals[s0]) / (b - s0)
            bad = 0
            for x in range(s0, n - 1):
                line = vals[s0] + slope * (x - s0)
                if kind == "down" and vals[x] > line + tol:
                    bad += 1
                if kind == "up" and vals[x] < line - tol:
                    bad += 1
            if bad > TREND_BAD:
                continue
            span = b - s0
            if best is None or span > best[0]:
                best = (span, s0, vals[s0], n - 1, vals[s0] + slope * (n - 1 - s0))
    return best[1:] if best else None

def draw_trendlines(ax, a):
    n = len(a)
    for kind in ("down", "up"):
        t = find_trendline(a, kind)
        if t:
            x0, y0, x1, y1 = t
            slope = (y1 - y0) / (x1 - x0) if x1 != x0 else 0
            x_end = n - 1 + TREND_EXT
            ax.plot([x0, x_end], [y0, y0 + slope * (x_end - x0)], color=TREND_COLOR, linewidth=3.0)


# ---------------- 지지·저항 박스 + 과매도/과매수 표시 (일봉 알림 차트와 같은 방식) ----------------
Z_PIVOT = 5            # 앞뒤 5봉보다 높/낮으면 고점/저점
Z_NEAR = 0.06          # 차트 가격 높이의 6% 안에 모이는 고/저점은 같은 박스
Z_RSI_LOW, Z_RSI_HIGH = 30, 70   # 이 값 이하 파란 ▲(과매도) / 이상 빨간 ▼(과매수)

def _pivots(a):
    hi, lo = [], []
    for i in range(Z_PIVOT, len(a) - Z_PIVOT):
        if a[i, 1] >= a[i - Z_PIVOT:i + Z_PIVOT + 1, 1].max():
            hi.append(a[i, 1])
        if a[i, 2] <= a[i - Z_PIVOT:i + Z_PIVOT + 1, 2].min():
            lo.append(a[i, 2])
    return hi, lo

def _zones(pts, price, above, tol):
    """비슷한 가격의 고/저점을 묶어 박스로 만듦. 현재가 위(저항)/아래(지지) 가까운 2개만"""
    groups = []
    for p in sorted(pts):
        if groups and p <= groups[-1][0] + tol:
            groups[-1][1].append(p)
            groups[-1][0] = p
        else:
            groups.append([p, [p]])
    zs = [(min(g[1]), max(g[1])) for g in groups]
    if above:
        zs = sorted([z for z in zs if z[0] > price], key=lambda z: z[0])
    else:
        zs = sorted([z for z in zs if z[1] < price], key=lambda z: -z[1])
    return zs[:2]

def _extras(ax, a):
    price = a[-1, 3]
    top, bot = a[:, 1].max(), a[:, 2].min()
    rng = top - bot
    if rng <= 0:
        return
    hi, lo = _pivots(a)
    pad = rng * 0.012
    for zl, zh in _zones(lo, price, False, rng * Z_NEAR):    # 지지: 초록 박스
        ax.axhspan(zl - pad, zh + pad, color="#2e7d32", alpha=0.18, zorder=0)
    for zl, zh in _zones(hi, price, True, rng * Z_NEAR):     # 저항: 빨강 박스
        ax.axhspan(zl - pad, zh + pad, color="#c62828", alpha=0.18, zorder=0)
    y0, y1 = ax.get_ylim()
    gap = (y1 - y0) * 0.025
    rs = rsi(a[:, 3])
    for i in range(len(a)):
        if rs[i] <= Z_RSI_LOW:
            ax.scatter(i, a[i, 2] - gap, marker="^", s=28, color="#0d47a1", zorder=5)
        elif rs[i] >= Z_RSI_HIGH:
            ax.scatter(i, a[i, 1] + gap, marker="v", s=28, color="#d50000", zorder=5)

_orig_trend = draw_trendlines

def draw_trendlines(ax, a):
    """원래 노란 추세선을 그린 뒤, 지지·저항 박스와 ▲▼를 얹음 (실패해도 차트는 그대로)"""
    _orig_trend(ax, a)
    try:
        _extras(ax, a)
    except Exception as e:
        print("[박스 오류]", e)

def fmtp(v):
    if v >= 100:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:.4f}"
    return f"{v:.7f}"

def draw_day_marks(axp, others, a, title):
    """오늘 시가·고가·저가·현재가(연한 회색 점선+작은 글자) + 1시간봉·15분봉에는 매일 01시(한국시간) 일봉 마감 세로선.
    글자는 영어로 (이 알림은 한글 글꼴이 없어서)"""
    grey, txt = "#90a4ae", "#607d8b"
    H = 3600000
    ts = a[:, 6]
    last = int(ts[-1])
    start = (last + 8 * H) // (24 * H) * (24 * H) - 8 * H
    idx = np.where(ts >= start)[0]
    if len(idx):
        t = a[idx[0]:]
        vals = {"Open": float(t[0, 0]), "High": float(t[:, 1].max()),
                "Low": float(t[:, 2].min()), "Last": float(a[-1, 3])}
        items = sorted(vals.items(), key=lambda kv: -kv[1])
        y0, y1 = axp.get_ylim()
        gap = (y1 - y0) * 0.07
        pos = []
        for _, v in items:
            axp.axhline(v, color=grey, lw=0.9, ls="--", alpha=0.8)
            pos.append(v if not pos else min(v, pos[-1] - gap))
        n = len(a)
        for (name, v), y in zip(items, pos):
            axp.annotate(f"{name} {fmtp(v)}", xy=(n + 1, v), xytext=(n + 2, y), xycoords="data", textcoords="data",
                         fontsize=6.5, color=txt, va="center", ha="left", fontweight="bold", annotation_clip=False,
                         arrowprops=dict(arrowstyle="-", color=grey, lw=0.6, shrinkA=0, shrinkB=0))
    if title in ("1H", "15m"):
        for i in range(1, len(a)):
            hour = int(ts[i] // H + 9) % 24
            minute = int(ts[i] // 60000) % 60
            if hour == 1 and minute == 0:
                for ax in [axp] + others:
                    ax.axvline(i - 0.5, color=grey, lw=1.0, ls=(0, (2, 2)), alpha=0.9)
                if i >= 14:
                    axp.text(i - 0.5, 1.0, "01:00 close", transform=axp.get_xaxis_transform(), fontsize=7,
                             color=txt, ha="center", va="bottom", fontweight="bold")

def panel(fig, spec, a, title):
    gs = GridSpecFromSubplotSpec(4, 1, subplot_spec=spec, height_ratios=[4, 1, 1.3, 1.3], hspace=0.08)
    axp = fig.add_subplot(gs[0]); axv = fig.add_subplot(gs[1], sharex=axp)
    axr = fig.add_subplot(gs[2], sharex=axp); axm = fig.add_subplot(gs[3], sharex=axp)
    if a is None or len(a) < 30:
        axp.set_title(title + " (데이터 없음)", fontsize=11); return
    c = a[:, 3]
    r = rsi(c)
    ma = {nm: ema(c, n) for nm, n, _ in LINES}
    vw = vwap100(a)
    m = ema(c, 12) - ema(c, 26); sg = ema(m, 9); hist = m - sg
    ma = {k: v[-SHOW:] for k, v in ma.items()}; vw = vw[-SHOW:]
    a = a[-SHOW:]; r = r[-SHOW:]; m = m[-SHOW:]; sg = sg[-SHOW:]; hist = hist[-SHOW:]
    x = np.arange(len(a))
    col = ["#d32f2f" if a[i, 3] >= a[i, 0] else "#1565c0" for i in x]
    axp.vlines(x, a[:, 2], a[:, 1], colors=col, linewidth=0.8)
    axp.bar(x, a[:, 3] - a[:, 0], bottom=a[:, 0], color=col, width=0.7)
    for nm, n, color in LINES:
        axp.plot(x, ma[nm], color=color, lw=1.1)
    axp.plot(x, vw, color=VW_COLOR, lw=1.4)
    lo, hi = a[:, 2].min(), a[:, 1].max()
    pad = (hi - lo) * 0.05
    draw_trendlines(axp, a)
    axp.set_ylim(lo - pad, hi + pad)   # 가격 범위만 보여줌(너무 먼 선은 화면 밖)
    axp.set_xlim(-1, len(a) + TREND_EXT)
    draw_day_marks(axp, [axv, axr, axm], a, title)
    axp.set_title(title, fontsize=11, loc="left")
    axv.bar(x, a[:, 4], color=col, width=0.7)
    axr.plot(x, r, color="#6a1b9a", linewidth=1)
    axr.axhline(70, color="gray", linewidth=0.6, linestyle="--"); axr.axhline(30, color="gray", linewidth=0.6, linestyle="--")
    axr.set_ylim(0, 100); axr.set_yticks([30, 70])
    axm.bar(x, hist, color=["#d32f2f" if h >= 0 else "#1565c0" for h in hist], width=0.7)
    axm.plot(x, m, color="black", linewidth=0.8); axm.plot(x, sg, color="orange", linewidth=0.8)
    for ax in (axp, axv, axr):
        plt.setp(ax.get_xticklabels(), visible=False)
    axm.set_xticks([])
    for ax, lab in ((axv, "VOL"), (axr, "RSI"), (axm, "MACD")):
        ax.set_ylabel(lab, fontsize=7)
        ax.tick_params(labelsize=7)
    axp.tick_params(labelsize=8); axv.set_yticks([])
    for ax in (axp, axv, axr, axm):
        ax.grid(alpha=0.25)

def make_chart(inst, rank, vol, ratio, data=None):
    fig = plt.figure(figsize=(14, 15), dpi=75)
    outer = GridSpec(2, 2, figure=fig, wspace=0.12, hspace=0.12, top=0.94, bottom=0.03, left=0.05, right=0.99)
    name = inst.replace("-USDT-SWAP", "")
    fig.suptitle(f"#{rank} {name}   1h volume x{ratio:.1f}   24h ${vol/1e6:.0f}M", fontsize=16, x=0.05, ha="left")
    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], color=c, lw=2) for _, _, c in LINES] + [Line2D([0], [0], color=VW_COLOR, lw=2)]
    fig.legend(handles, [nm for nm, _, _ in LINES] + ["VWAP100"], loc="upper right",
               ncol=7, fontsize=9, frameon=False, bbox_to_anchor=(0.99, 0.985))
    for i, (bar, label) in enumerate(BARS):
        a = data[bar] if data else candles(inst, bar)
        panel(fig, outer[i // 2, i % 2], a, label)
        if not data:
            time.sleep(0.15)
    buf = io.BytesIO()
    fig.savefig(buf, format="png"); plt.close(fig); buf.seek(0)
    return buf

def send(buf, caption):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                      data={"chat_id": CHAT, "caption": caption},
                      files={"photo": ("c.png", buf)}, timeout=60)
    if not r.ok:
        print("전송 실패", r.status_code, r.text[:200])

def main():
    for rank, (ratio, inst, v) in enumerate(top_coins(), 1):
        try:
            buf = make_chart(inst, rank, v, ratio)
            send(buf, f"#{rank} {inst.replace('-USDT-SWAP','')}  거래대금 x{ratio:.1f}")
        except Exception as e:
            print(inst, "실패", e)
        time.sleep(1.2)

if __name__ == "__main__":
    main()
