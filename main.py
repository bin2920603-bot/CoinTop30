import os, io, time, requests
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec

BARS = [("1D", "1D"), ("4H", "4H"), ("1H", "1H"), ("15m", "15m")]
COUNT = 30
SHOW = 80
TOKEN = os.environ["TG_TOKEN"]
OKX = "https://www.okx.com"

def num(v):
    try:
        return float(v)
    except Exception:
        return 0.0

def find_chat():
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=20).json()
    for u in reversed(r.get("result", [])):
        for k in ("message", "my_chat_member", "channel_post"):
            c = u.get(k, {}).get("chat")
            if c and c.get("type") in ("group", "supergroup"):
                return str(c["id"])
    raise SystemExit("방을 못 찾았어요. 방에 /start@tajeom_top30_bot 을 다시 보내주세요")

CHAT = os.environ.get("TG_CHAT") or find_chat()

def top_coins():
    data = requests.get(OKX + "/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=20).json()["data"]
    rows = []
    for t in data:
        if t["instId"].endswith("-USDT-SWAP"):
            v = num(t.get("volCcy24h")) * num(t.get("last"))
            if v > 0:
                rows.append((v, t["instId"]))
    rows.sort(reverse=True)
    return rows[:COUNT]

def candles(inst, bar):
    for _ in range(3):
        try:
            d = requests.get(OKX + "/api/v5/market/candles",
                             params={"instId": inst, "bar": bar, "limit": 200}, timeout=20).json()["data"]
            d = d[::-1]
            a = np.array([[num(x[1]), num(x[2]), num(x[3]), num(x[4]), num(x[5])] for x in d])
            return a  # o h l c vol
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

def panel(fig, spec, a, title):
    gs = GridSpecFromSubplotSpec(4, 1, subplot_spec=spec, height_ratios=[4, 1, 1.3, 1.3], hspace=0.08)
    axp = fig.add_subplot(gs[0]); axv = fig.add_subplot(gs[1], sharex=axp)
    axr = fig.add_subplot(gs[2], sharex=axp); axm = fig.add_subplot(gs[3], sharex=axp)
    if a is None or len(a) < 30:
        axp.set_title(title + " (no data)", fontsize=11); return
    c = a[:, 3]
    r = rsi(c)
    m = ema(c, 12) - ema(c, 26); sg = ema(m, 9); hist = m - sg
    a = a[-SHOW:]; r = r[-SHOW:]; m = m[-SHOW:]; sg = sg[-SHOW:]; hist = hist[-SHOW:]
    x = np.arange(len(a))
    col = ["#d32f2f" if a[i, 3] >= a[i, 0] else "#1565c0" for i in x]
    axp.vlines(x, a[:, 2], a[:, 1], colors=col, linewidth=0.8)
    axp.bar(x, a[:, 3] - a[:, 0], bottom=a[:, 0], color=col, width=0.7)
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

def make_chart(inst, rank, vol, data=None):
    fig = plt.figure(figsize=(14, 15), dpi=75)
    outer = GridSpec(2, 2, figure=fig, wspace=0.12, hspace=0.12, top=0.94, bottom=0.03, left=0.05, right=0.99)
    name = inst.replace("-USDT-SWAP", "")
    fig.suptitle(f"#{rank} {name}   24h ${vol/1e6:.0f}M", fontsize=16, x=0.05, ha="left")
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
        print("전송 실패", r.text)

def main():
    for rank, (v, inst) in enumerate(top_coins(), 1):
        try:
            buf = make_chart(inst, rank, v)
            send(buf, f"#{rank} {inst.replace('-USDT-SWAP','')}")
        except Exception as e:
            print(inst, "실패", e)
        time.sleep(1.2)

if __name__ == "__main__":
    main()
