import json
import threading
import time
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
SYMBOL, INTERVAL, START_BALANCE = "BTCUSDT", "5m", 100.0
state = {
    "last_update": None, "price": None, "rsi": None, "ema_fast": None,
    "ema_slow": None, "shariat_action": "ОЖИДАНИЕ", "spot_action": "ОЖИДАНИЕ",
    "shariat_value": START_BALANCE, "spot_value": START_BALANCE,
    "message": "Ожидание первого обновления Binance",
    "accounts": {
        "shariat_label_only": {"cash": START_BALANCE, "btc": 0.0, "last_signal": ""},
        "spot": {"cash": START_BALANCE, "btc": 0.0, "last_signal": ""},
    }
}
lock = threading.Lock()

def candles():
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit=100"
    req = Request(url, headers={"User-Agent": "TURAN-Paper-Dashboard/1.0"})
    with urlopen(req, timeout=15) as response:
        rows = json.loads(response.read().decode("utf-8"))
    return [float(row[4]) for row in rows[:-1]]

def ema(values, period):
    result = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result

def rsi(values, period=14):
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    recent = changes[-period:]
    gains = sum(max(x, 0) for x in recent) / period
    losses = sum(max(-x, 0) for x in recent) / period
    if losses == 0:
        return 100.0 if gains else 50.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)

def buy(account, price):
    amount = account["cash"] * 0.99
    account["btc"] += amount / price
    account["cash"] -= amount

def sell(account, price):
    account["cash"] += account["btc"] * price
    account["btc"] = 0.0

def total(account, price):
    return account["cash"] + account["btc"] * price

def update():
    closes = candles()
    price = closes[-1]
    fast, slow, rsi_value = ema(closes[-30:], 9), ema(closes[-60:], 21), rsi(closes)
    with lock:
        a = state["accounts"]["shariat_label_only"]
        if fast > slow and a["last_signal"] != "BUY":
            buy(a, price); a["last_signal"] = "BUY"; state["shariat_action"] = "ПОКУПКА (виртуально)"
        elif fast < slow and a["last_signal"] != "SELL":
            sell(a, price); a["last_signal"] = "SELL"; state["shariat_action"] = "ПРОДАЖА (виртуально)"
        else:
            state["shariat_action"] = "ОЖИДАНИЕ"
        b = state["accounts"]["spot"]
        if rsi_value < 30 and b["last_signal"] != "BUY":
            buy(b, price); b["last_signal"] = "BUY"; state["spot_action"] = "ПОКУПКА (виртуально)"
        elif rsi_value > 55 and b["last_signal"] != "SELL":
            sell(b, price); b["last_signal"] = "SELL"; state["spot_action"] = "ПРОДАЖА (виртуально)"
        else:
            state["spot_action"] = "ОЖИДАНИЕ"
        state.update({
            "last_update": datetime.now(timezone.utc).isoformat(), "price": price,
            "rsi": rsi_value, "ema_fast": fast, "ema_slow": slow,
            "shariat_value": total(a, price), "spot_value": total(b, price),
            "message": "Данные Binance обновлены"
        })

def worker():
    while True:
        try:
            update()
        except Exception as exc:
            with lock:
                state["message"] = f"Ошибка получения данных: {type(exc).__name__}: {exc}"
        time.sleep(60)

PAGE = """<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TURAN AI</title><style>
body{font-family:system-ui;background:#101318;color:#f3f4f6;margin:0;padding:22px}
main{max-width:760px;margin:auto}.card{background:#1b222c;border:1px solid #354052;border-radius:14px;padding:18px;margin:14px 0}
.muted{color:#aab4c3}.big{font-size:28px;font-weight:700}.warn{color:#ffd27a;font-weight:700}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:520px){.grid{grid-template-columns:1fr}}
</style><main><h1>TURAN AI</h1><p class="warn">PAPER ONLY — реальные сделки отключены</p>
<div class="card"><div class="muted">BTC/USDT · публичные данные Binance</div><div class="big">{{price}}</div>
<p>{{message}}</p><p class="muted">Обновлено: {{updated}}</p></div>
<div class="grid"><div class="card"><h2>«Шариат» — название тестового алгоритма</h2>
<p>Сигнал: <b>{{sa}}</b></p><p>Виртуальный баланс: <b>{{sv}} USDT</b></p></div>
<div class="card"><h2>Обычный Spot</h2><p>Сигнал: <b>{{ba}}</b></p><p>Виртуальный баланс: <b>{{bv}} USDT</b></p></div></div>
<div class="card"><p>RSI: {{rsi}} · EMA 9: {{ef}} · EMA 21: {{es}}</p>
<p class="muted">Учебная симуляция. Нет подключения к аккаунту Binance, API-ключей или реальных ордеров.
Название «Шариат» не является религиозной сертификацией или фетвой.</p></div>
<p><a style="color:#9fc5ff" href="/api/status">JSON-статус</a> · <a style="color:#9fc5ff" href="/health">Проверка сервиса</a></p>
</main></html>"""

@app.get("/")
def home():
    with lock:
        s = dict(state)
    return render_template_string(PAGE,
        price=(f'{s["price"]:,.2f} USDT' if s["price"] is not None else "Загрузка…"),
        message=s["message"], updated=s["last_update"] or "ещё нет",
        sa=s["shariat_action"], ba=s["spot_action"],
        sv=f'{s["shariat_value"]:.2f}', bv=f'{s["spot_value"]:.2f}',
        rsi=f'{s["rsi"]:.1f}' if s["rsi"] is not None else "—",
        ef=f'{s["ema_fast"]:.2f}' if s["ema_fast"] is not None else "—",
        es=f'{s["ema_slow"]:.2f}' if s["ema_slow"] is not None else "—")

@app.get("/health")
def health():
    return jsonify({"ok": True, "mode": "paper-only"})

@app.get("/api/status")
def api_status():
    with lock:
        return jsonify(state)

threading.Thread(target=worker, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
