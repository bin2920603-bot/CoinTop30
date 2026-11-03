import os, io, time, requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BARS = ["15m"]  # "1m" "5m" "15m" 중 바꿔 쓰기
COUNT = 30
TOKEN = os.environ["TG_TOKEN"]
OKX = "https://www.okx.com"


def num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def find_chat():
    r = requests.get(
        f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=20
    ).json()
    for u in reversed(r.get("result", [])):
        for k in ("message", "my_chat_member", "channel_post"):
            c = u.get(k, {}).get("chat")
            if c and c.get("type") in ("group", "supergroup"):
                return str(c["id"])
    raise SystemExit("방을 못 찾았어요. 방에 /start@tajeom_top30_bot 을 다시 보내주세요")


CHAT = os.environ.get("TG_CHAT") or find_chat()


def top_coins():
    data = requests.get(OKX + "/api/v5/market/tickers",
                        params={"instType": "SWAP"}, timeout=20).json()["data"]
    rows = []
    for t in data:
        if t["instId"].endswith("-USDT-SWAP"):
            v = num(t.get("volCcy24h")) * num(t.get("last"))
            if v > 0:
                rows.append((v, t["instId"]))
    rows.sort(reverse=True)
    return rows[:COUNT]


def candles(inst, bar):
    d = requests.get(OKX + "/api/v5/market/candles",
                     params={"instId": inst, "bar": bar, "limit": "100"},
                     timeout=20).json()["data"]
    return d[::-1]


def make_chart(rank, inst, vol24, bar):
    d = candles(inst, bar)
    fig, (a1, a2) = plt.subplots(
        2, 1, figsize=(8, 6), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]})
    for i, x in enumerate(d):
        o, h, l, c = (num(v) for v in x[1:5])
        col = "#d62728" if c >= o else "#1f77b4"
        a1.plot([i, i], [l, h], color=col, lw=1)
        a1.bar(i, abs(c - o), bottom=min(o, c), color=col, width=0.7)
        a2.bar(i, num(x[7]), color=col, width=0.7)
    name = inst.replace("-USDT-SWAP", "")
    a1.set_title(f"#{rank} {name}  {bar}  24h ${vol24/1e6:,.0f}M")
    a1.grid(alpha=0.2)
    a2.grid(alpha=0.2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf, name


def send(buf, caption):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
        data={"chat_id": CHAT, "caption": caption},
        files={"photo": buf}, timeout=30)


def main():
    coins = top_coins()
    for bar in BARS:
        for rank, (vol, inst) in enumerate(coins, 1):
            try:
                buf, name = make_chart(rank, inst, vol, bar)
                send(buf, f"#{rank} {name} {bar}")
            except Exception as e:
                print(inst, bar, "실패:", e)
            time.sleep(1.2)


main()
