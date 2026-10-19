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

CAPITAL_TOTAL = 10000.0  # Capital de référence en €
RISK_PERCENT = 1.0        # 1% de risque par trade (100 €)

# Fuseau horaire des alertes (heure française)
TZ = timezone(timedelta(hours=1))  # CET ; passe à +2 en été si besoin

# Fichier de persistance de l'anti-doublon (survit aux redémarrages)
STATE_FILE = os.environ.get("STATE_FILE", "bot_state.json")
SCAN_OFFSET_MIN = 2   # minutes après la clôture 4H (laisse Yahoo publier)
MAX_RETRIES = 3       # retries sur erreur yfinance

LAST_SCAN_INFO = {}


def now_local():
    return datetime.now(TZ)


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
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
    "NDX": {"yf": "^NDX", "name": "Nasdaq 100", "reg": "États-Unis", "sec": "Indices Boursiers"},
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

# ==============================================================================
# 2. PARAMÈTRES TECHNIQUES
# ==============================================================================
TIMEFRAME = "4h"
RSI_LEN, BAND_LEN, BAND_MULT = 13, 34, 1.6185
PRICE_LEN, SIGNAL_LEN, SMA_LEN = 2, 7, 50
SWING_LOOKBACK = 10
TP1_RATIO, TP2_RATIO = 1.0, 2.0  # TP1 = 1R, TP2 = 2R

# Anti-doublon persistant : {tv_name: timestamp bougie signalée}
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


def download_data(symbol, period="6mo"):
    """Téléchargement avec retry simple (rate limiting Yahoo)."""
    for attempt in range(MAX_RETRIES):
        try:
            df = yf.download(symbol, period=period, interval=TIMEFRAME,
                             progress=False, auto_adjust=False)
            if not df.empty:
                return df
        except Exception as e:
            print(f"Tentative {attempt + 1}/{MAX_RETRIES} échouée sur {symbol} : {e}")
        time.sleep(2 * (attempt + 1))
    return None


# ==============================================================================
# 3. ANALYSE & CALCUL DE TAILLE DE POSITION
# ==============================================================================
def analyze_asset(tv_name, info):
    try:
        df = download_data(info["yf"])
        if df is None or len(df) < (SMA_LEN + SWING_LOOKBACK + 5):
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = calculate_tdi_and_sma(df)

        # --- IMPORTANT : on ignore la dernière bougie (potentiellement
        # en cours) et on travaille sur les bougies CLÔTURÉES ---
        closed = df.iloc[:-1]
        if len(closed) < (SMA_LEN + SWING_LOOKBACK + 5):
            return None

        curr = closed.iloc[-1]
        prev = closed.iloc[-2]

        candle_time = pd.Timestamp(closed.index[-1]).isoformat()
        if last_signaled_candle.get(tv_name) == candle_time:
            return None  # Anti-doublon (persisté entre redémarrages)

        close_curr = float(curr["Close"])

        cross_up = (float(prev["TDI_Signal"]) <= float(prev["TDI_Basis"])) and (
            float(curr["TDI_Signal"]) > float(curr["TDI_Basis"]))
        cross_down = (float(prev["TDI_Signal"]) >= float(prev["TDI_Basis"])) and (
            float(curr["TDI_Signal"]) < float(curr["TDI_Basis"]))

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
            # Swing sur les bougies clôturées, SANS la bougie du signal
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
                    "date": now_local().strftime("%d/%m/%Y %H:%M"),
                    "candle": pd.Timestamp(closed.index[-1]).strftime("%d/%m %H:%M UTC"),
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


# ==============================================================================
# 4. SCHEDULING ALIGNÉ SUR LES BOUGIES 4H
# ==============================================================================
def seconds_until_next_4h_close():
    """Temps jusqu'à la prochaine clôture de bougie 4H (UTC) + offset."""
    now = datetime.now(timezone.utc)
    next_close = (now.replace(minute=0, second=0, microsecond=0)
                  + timedelta(hours=4))
    # Arrondi au multiple de 4h de l'heure courante
    next_close = now.replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=4 - (now.hour % 4))
    delta = (next_close - now).total_seconds() + SCAN_OFFSET_MIN * 60
    return max(delta, 30)  # sécurité : minimum 30 s


def run_bot_loop():
    # Attend la prochaine clôture 4H avant le premier scan
    # (évite d'analyser une bougie à moitié formée au démarrage)
    first_wait = seconds_until_next_4h_close()
    print(f"Démarrage bot. Premier scan dans {first_wait / 60:.1f} min.")
    time.sleep(first_wait)

    while True:
        now_str = now_local().strftime("%d/%m/%Y %H:%M")
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
                    f"• Bougie clôturée : {res['candle']}\n"
                    f"• Prix d'entrée : {res['price']:.3f}\n"
                    f"• Stop Loss : {res['sl']:.3f}\n"
                    f"• Take Profit 1 ({TP1_RATIO:.0f}R, fermer 50%) : {res['tp1']:.3f}\n"
                    f"• Take Profit 2 ({TP2_RATIO:.0f}R, fermer 50%) : {res['tp2']:.3f}\n"
                    f"• Taille indicative* : {res['units']:.3f} unités\n"
                    f"• Risque max : {res['risk_amount']:.2f} € ({res['risk_pct']:.0f}%)\n"
                    f"• Capital de référence : {res['capital']:.2f} €\n"
                    "\n*Taille indicative : vérifie la conversion de devise "
                    "pour les paires non quotées en EUR."
                )
                send_telegram_message(msg, tv_symbol=res["tv_symbol"])
                print(f"🎯 Signal envoyé pour {res['symbol']}")

            time.sleep(1)

        LAST_SCAN_INFO["time"] = now_str
        LAST_SCAN_INFO["signals"] = signals_found

        if signals_found == 0:
            msg_status = (
                f"⚪ {now_str} | Scan 4H terminé : "
                f"Aucun signal valide sur les {len(ASSETS)} actifs."
            )
            send_telegram_message(msg_status)
            print("Aucun signal détecté.")

        # Attente jusqu'à la PROCHAINE clôture 4H (pas un sleep fixe)
        time.sleep(seconds_until_next_4h_close())


# ==============================================================================
# 5. LANCEMENT
# ==============================================================================
# Lancé au niveau module (et non dans __main__) pour que le bot tourne
# aussi sous Gunicorn (ex: gunicorn app:app).
# ⚠️ Utilise IMPÉRATIVEMENT un seul worker (--workers 1) sinon
# tu recevras les alertes en double.
_bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
_bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
