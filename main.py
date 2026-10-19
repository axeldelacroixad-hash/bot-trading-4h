import os
import json
import time
import threading
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import yfinance as yf
from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot Trading 4H TDI est actif !", 200


@app.route("/health")
def health():
    return {"status": "ok", "last_scan": LAST_SCAN_INFO.get("time")}, 200


# ==============================================================================
# 1. CONFIGURATION TELEGRAM & MÉTADONNÉES
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "TON_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "TON_CHAT_ID")

CAPITAL_TOTAL = 10000.0  
RISK_PERCENT = 1.0        

TZ = timezone(timedelta(hours=1))  
STATE_FILE = "bot_state.json"
MAX_RETRIES = 3

LAST_SCAN_INFO = {}


def now_local():
    return datetime.now(TZ)


def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"Erreur sauvegarde état : {e}")


def send_telegram_message(message, tv_symbol=None):
    if TELEGRAM_BOT_TOKEN == "TON_BOT_TOKEN" or not TELEGRAM_CHAT_ID:
        print("[MOCK TELEGRAM]\n" + message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}

    if tv_symbol:
        payload["reply_markup"] = {
            "inline_keyboard": [[{
                "text": "📊 Ouvrir sur TradingView",
                "url": f"https://www.tradingview.com/chart/?symbol={tv_symbol}",
            }]]
        }

    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code != 200:
            print(f"Erreur Telegram : {response.text}")
    except Exception as e:
        print(f"Erreur connexion Telegram : {e}")


ASSETS = {
    "FX:EURUSD": {"yf": "EURUSD=X", "name": "EUR/USD", "reg": "Europe / US", "sec": "Forex (Devises)"},
    "FX:GBPUSD": {"yf": "GBPUSD=X", "name": "GBP/USD", "reg": "Royaume-Uni / US", "sec": "Forex (Devises)"},
    "FX:USDJPY": {"yf": "USDJPY=X", "name": "USD/JPY", "reg": "US / Japon", "sec": "Forex (Devises)"},
    "FX:GBPJPY": {"yf": "GBPJPY=X", "name": "GBP/JPY", "reg": "Royaume-Uni / Japon", "sec": "Forex (Devises)"},
    "FX:AUDUSD": {"yf": "AUDUSD=X", "name": "AUD/USD", "reg": "Australie / US", "sec": "Forex (Devises)"},
    "FX:USDCAD": {"yf": "USDCAD=X", "name": "USD/CAD", "reg": "US / Canada", "sec": "Forex (Devises)"},
    "FX:USDCHF": {"yf": "USDCHF=X", "name": "USD/CHF", "reg": "US / Suisse", "sec": "Forex (Devises)"},
    "FX:EURGBP": {"yf": "EURGBP=X", "name": "EUR/GBP", "reg": "Europe / Royaume-Uni", "sec": "Forex (Devises)"},
    "FX:EURJPY": {"yf": "EURJPY=X", "name": "EUR/JPY", "reg": "Europe / Japon", "sec": "Forex (Devises)"},
    "SPX": {"yf": "^GSPC", "name": "S&P 500", "reg": "États-Unis", "sec": "Indices Boursiers"},
    "NDX": {"yf": "^IXIC", "name": "Nasdaq 100", "reg": "États-Unis", "sec": "Indices Boursiers"},
    "DJI": {"yf": "^DJI", "name": "Dow Jones", "reg": "États-Unis", "sec": "Indices Boursiers"},
    "XETR:DAX": {"yf": "^GDAXI", "name": "DAX 40", "reg": "Allemagne", "sec": "Indices Boursiers"},
    "TVC:PX1": {"yf": "^FCHI", "name": "CAC 40", "reg": "France", "sec": "Indices Boursiers"},
    "TVC:UKX": {"yf": "^FTSE", "name": "FTSE 100", "reg": "Royaume-Uni", "sec": "Indices Boursiers"},
    "ASX:XJO": {"yf": "^AXJO", "name": "ASX 200", "reg": "Australie", "sec": "Indices Boursiers"},
    "OANDA:XAUUSD": {"yf": "GC=F", "name": "Gold (Or)", "reg": "International", "sec": "Matières Premières"},
    "TVC:USOIL": {"yf": "CL=F", "name": "Crude Oil", "reg": "International", "sec": "Matières Premières"},
    "BINANCE:BTCUSDT": {"yf": "BTC-USD", "name": "Bitcoin", "reg": "Crypto", "sec": "Cryptomonnaies"},
    "BINANCE:ETHUSDT": {"yf": "ETH-USD", "name": "Ethereum", "reg": "Crypto", "sec": "Cryptomonnaies"},
    "BINANCE:SOLUSDT": {"yf": "SOL-USD", "name": "Solana", "reg": "Crypto", "sec": "Cryptomonnaies"},
    "NASDAQ:AAPL": {"yf": "AAPL", "name": "Apple", "reg": "États-Unis", "sec": "Actions Tech US"},
    "NASDAQ:NVDA": {"yf": "NVDA", "name": "Nvidia", "reg": "États-Unis", "sec": "Actions Tech US"},
    "NASDAQ:TSLA": {"yf": "TSLA", "name": "Tesla", "reg": "États-Unis", "sec": "Actions Tech US"},
    "NASDAQ:MSFT": {"yf": "MSFT", "name": "Microsoft", "reg": "États-Unis", "sec": "Actions Tech US"},
    "NASDAQ:AMZN": {"yf": "AMZN", "name": "Amazon", "reg": "États-Unis", "sec": "Actions Tech US"},
}

TIMEFRAME = "4h"
RSI_LEN, BAND_LEN, BAND_MULT = 13, 34, 1.6185
PRICE_LEN, SIGNAL_LEN, SMA_LEN = 2, 7, 50
SWING_LOOKBACK = 10
TP1_RATIO, TP2_RATIO = 1.0, 2.0  

last_signaled_candle = load_state()


def rma(x, n):
    return x.ewm(alpha=1 / n, adjust=False).mean()


def calculate_tdi_and_sma(df):
    delta = df["Close"].diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    rs = rma(gain, RSI_LEN) / rma(loss, RSI_LEN)
    df["RSI"] = 100 - (100 / (1 + rs))

    df["TDI_Basis"] = df["RSI"].rolling(window=BAND_LEN).mean()
    dev = df["RSI"].rolling(window=BAND_LEN).std() * BAND_MULT
    df["TDI_Up"] = df["TDI_Basis"] + dev
    df["TDI_Dn"] = df["TDI_Basis"] - dev
    df["TDI_Price"] = df["RSI"].rolling(window=PRICE_LEN).mean()
    df["TDI_Signal"] = df["RSI"].rolling(window=SIGNAL_LEN).mean()
    df["SMA_50"] = df["Close"].rolling(window=SMA_LEN).mean()
    return df


def download_data(symbol):
    for attempt in range(MAX_RETRIES):
        try:
            df = yf.download(symbol, period="60d", interval=TIMEFRAME, progress=False, auto_adjust=False)
            if not df.empty:
                return df
        except Exception as e:
            print(f"Tentative {attempt + 1} échouée sur {symbol} : {e}")
        time.sleep(1)
    return None


def analyze_asset(tv_name, info):
    try:
        df = download_data(info["yf"])
        if df is None or len(df) < (SMA_LEN + SWING_LOOKBACK + 5):
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = calculate_tdi_and_sma(df)
        closed = df.iloc[:-1]
        if len(closed) < (SMA_LEN + SWING_LOOKBACK + 5):
            return None

        curr = closed.iloc[-1]
        prev = closed.iloc[-2]

        candle_time = pd.Timestamp(closed.index[-1]).isoformat()
        if last_signaled_candle.get(tv_name) == candle_time:
            return None  

        close_curr = float(curr["Close"])

        cross_up = (float(prev["TDI_Signal"]) <= float(prev["TDI_Basis"])) and (
            float(curr["TDI_Signal"]) > float(curr["TDI_Basis"])
        )
        cross_down = (float(prev["TDI_Signal"]) >= float(prev["TDI_Basis"])) and (
            float(curr["TDI_Signal"]) < float(curr["TDI_Basis"])
        )

        long_signal = (
            cross_up
            and (float(curr["TDI_Price"]) > float(curr["TDI_Signal"]))
            and (close_curr > float(curr["SMA_50"]))
        )
        short_signal = (
            cross_down
            and (float(curr["TDI_Price"]) < float(curr["TDI_Signal"]))
            and (close_curr < float(curr["SMA_50"]))
        )

        if long_signal or short_signal:
            window = closed.iloc[-(SWING_LOOKBACK + 2):-1]
            if long_signal:
                sl = float(window["Low"].min())
                action, emoji = "LONG (Achat)", "🟢"
                risk_per_unit = close_curr - sl
                tp1 = close_curr + (risk_per_unit * TP1_RATIO)
                tp2 = close_curr + (risk_per_unit * TP2_RATIO)
            else:
                sl = float(window["High"].max())
                action, emoji = "SHORT (Vente)", "🔴"
                risk_per_unit = sl - close_curr
                tp1 = close_curr - (risk_per_unit * TP1_RATIO)
                tp2 = close_curr - (risk_per_unit * TP2_RATIO)

            if risk_per_unit > 0:
                risk_amount = CAPITAL_TOTAL * (RISK_PERCENT / 100.0)
                units = risk_amount / risk_per_unit

                last_signaled_candle[tv_name] = candle_time
                save_state(last_signaled_candle)

                return {
                    "date": now_local().strftime("%d/%m/%Y-%H:%M"),
                    "symbol": info["yf"],
                    "name": info["name"],
                    "reg": info["reg"],
                    "sec": info["sec"],
                    "action": action,
                    "emoji": emoji,
                    "price": close_curr,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "units": units,
                    "risk_amount": risk_amount,
                    "risk_pct": RISK_PERCENT,
                    "capital": CAPITAL_TOTAL,
                    "tv_symbol": tv_name,
                }
    except Exception as e:
        print(f"Erreur sur {tv_name} : {e}")

    return None


def run_bot_loop():
    print("🤖 Bot démarré avec succès. Lancement du premier scan immédiat...")
    
    while True:
        now_str = now_local().strftime("%d/%m/%Y-%H:%M")
        print(f"\n--- Scan 4H exécuté le {now_str} ---")

        signals_found = 0
        for tv_name, info in ASSETS.items():
            res = analyze_asset(tv_name, info)
            if res:
                signals_found += 1
                msg = (
                    f"{res['emoji']} {res['date']} | {res['symbol']} | {res['name']}\n"
                    f"🌍 Région : {res['reg']}\n"
                    f"🏢 Secteur : {res['sec']}\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    f"• Signal : {res['action']}\n"
                    f"• Prix actuel : {res['price']:.3f}\n"
                    f"• Stop Loss : {res['sl']:.3f}\n"
                    f"• Take Profit 1 (50%) : {res['tp1']:.3f}\n"
                    f"• Take Profit 2 (50%) : {res['tp2']:.3f}\n"
                    f"• Nb d'unités total : {res['units']:.3f}\n"
                    f"• Risque : {res['risk_amount']:.2f} € ({res['risk_pct']:.0f}%)\n"
                    f"• Montant Total : {res['capital']:.2f} €"
                )
                send_telegram_message(msg, tv_symbol=res["tv_symbol"])
                print(f"🎯 Signal envoyé pour {res['symbol']}")

            time.sleep(1)

        LAST_SCAN_INFO["time"] = now_str
        LAST_SCAN_INFO["signals"] = signals_found

        if signals_found == 0:
            msg_status = f"⚪ {now_str} | Scan 4H terminé : Aucun signal valide sur les {len(ASSETS)} actifs."
            send_telegram_message(msg_status)
            print("Aucun signal détecté sur ce cycle.")

        # Pause fixe de 4 heures pour relancer proprement le scan au prochain cycle 4H
        print("\n💤 Fin du scan. Prochaine vérification dans 4 heures.")
        time.sleep(4 * 3600)


_bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
_bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
