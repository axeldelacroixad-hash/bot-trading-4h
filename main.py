import os
import threading
import time
from flask import Flask
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# Initialisation du serveur web pour Render
app = Flask(__name__)


@app.route("/")
def home():
  return "Bot Trading 4H TDI est actif et opérationnel !", 200


# ==============================================================================
# 1. CONFIGURATION TELEGRAM (Récupérée de ton ancien bot)
# ==============================================================================
# Sur Render, tu peux stocker ton Token et ton Chat ID dans les "Environment Variables"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "TON_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "TON_CHAT_ID")


def send_telegram_message(message):
  """Fonction pour envoyer l'alerte sur ton téléphone via Telegram"""
  if TELEGRAM_BOT_TOKEN == "TON_BOT_TOKEN":
    print("⚠️ Token Telegram non configuré.")
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
  try:
    response = requests.post(url, json=payload)
    if response.status_code != 200:
      print(f"Erreur d'envoi Telegram : {response.text}")
  except Exception as e:
    print(f"Erreur connexion Telegram : {e}")


# ==============================================================================
# 2. LISTE COMPLETE DES 26 ACTIFS
# ==============================================================================
ASSETS = {
    # Forex
    "FX:EURUSD": "EURUSD=X",
    "FX:GBPUSD": "GBPUSD=X",
    "FX:USDJPY": "USDJPY=X",
    "FX:GBPJPY": "GBPJPY=X",
    "FX:AUDUSD": "AUDUSD=X",
    "FX:USDCAD": "USDCAD=X",
    "FX:USDCHF": "USDCHF=X",
    "FX:EURGBP": "EURGBP=X",
    "FX:EURJPY": "EURJPY=X",
    # Indices
    "SPX": "^GSPC",
    "NDX": "^IXIC",
    "DJI": "^DJI",
    "XETR:DAX": "^GDAXI",
    "TVC:PX1": "^FCHI",
    "TVC:UKX": "^FTSE",
    "ASX:XJO": "^AXJO",
    # Commodities
    "OANDA:XAUUSD": "GC=F",
    "TVC:USOIL": "CL=F",
    # Crypto
    "BINANCE:BTCUSDT": "BTC-USD",
    "BINANCE:ETHUSDT": "ETH-USD",
    "BINANCE:SOLUSDT": "SOL-USD",
    # Tech Equities
    "NASDAQ:AAPL": "AAPL",
    "NASDAQ:NVDA": "NVDA",
    "NASDAQ:TSLA": "TSLA",
    "NASDAQ:MSFT": "MSFT",
    "NASDAQ:AMZN": "AMZN",
}

# ==============================================================================
# 3. PARAMÈTRES DE LA STRATÉGIE
# ==============================================================================
TIMEFRAME = "4h"
RSI_LEN = 13
BAND_LEN = 34
BAND_MULT = 1.6185
PRICE_LEN = 2
SIGNAL_LEN = 7
SMA_LEN = 50

SWING_LOOKBACK = 10
TP1_RATIO = 1.0  # Premier objectif (50%)
TP2_RATIO = 2.0  # Deuxième objectif final (50%)


# ==============================================================================
# 4. CALCULS TECHNIQUES (RSI WILDER + TDI + SMA 50)
# ==============================================================================
def rma(x, n):
  a = 1 / n
  return x.ewm(alpha=a, adjust=False).mean()


def calculate_rsi_wilder(close_series, length=13):
  delta = close_series.diff()
  gain = delta.clip(lower=0)
  loss = -delta.clip(upper=0)
  avg_gain = rma(gain, length)
  avg_loss = rma(loss, length)
  rs = avg_gain / avg_loss
  return 100 - (100 / (1 + rs))


def calculate_tdi_and_sma(df):
  df["RSI"] = calculate_rsi_wilder(df["Close"], RSI_LEN)
  df["TDI_Basis"] = df["RSI"].rolling(window=BAND_LEN).mean()
  dev = df["RSI"].rolling(window=BAND_LEN).std() * BAND_MULT
  df["TDI_Up"] = df["TDI_Basis"] + dev
  df["TDI_Dn"] = df["TDI_Basis"] - dev
  df["TDI_Price"] = df["RSI"].rolling(window=PRICE_LEN).mean()
  df["TDI_Signal"] = df["RSI"].rolling(window=SIGNAL_LEN).mean()
  df["SMA_50"] = df["Close"].rolling(window=SMA_LEN).mean()
  return df


# ==============================================================================
# 5. ANALYSE ET DOUBLE TP
# ==============================================================================
def analyze_asset(tv_name, yf_ticker):
  try:
    df = yf.download(yf_ticker, period="60d", interval=TIMEFRAME, progress=False)
    if len(df) < (SMA_LEN + SWING_LOOKBACK + 5):
      return None

    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.get_level_values(0)

    df = calculate_tdi_and_sma(df)

    prev = df.iloc[-3]
    curr = df.iloc[-2]

    close_curr = float(curr["Close"])
    signal_curr = float(curr["TDI_Signal"])
    basis_curr = float(curr["TDI_Basis"])
    price_curr = float(curr["TDI_Price"])
    sma50_curr = float(curr["SMA_50"])

    signal_prev = float(prev["TDI_Signal"])
    basis_prev = float(prev["TDI_Basis"])

    cross_up = (signal_prev <= basis_prev) and (signal_curr > basis_curr)
    cross_down = (signal_prev >= basis_prev) and (signal_curr < basis_curr)

    long_signal = (
        cross_up and (price_curr > signal_curr) and (close_curr > sma50_curr)
    )
    short_signal = (
        cross_down and (price_curr < signal_curr) and (close_curr < sma50_curr)
    )

    if long_signal:
      swing_low = float(df["Low"].iloc[-(SWING_LOOKBACK + 2) : -2].min())
      risk = close_curr - swing_low
      if risk > 0:
        return {
            "symbol": tv_name,
            "action": "LONG 🟢",
            "price": close_curr,
            "sl": swing_low,
            "tp1": close_curr + (risk * TP1_RATIO),
            "tp2": close_curr + (risk * TP2_RATIO),
        }

    elif short_signal:
      swing_high = float(df["High"].iloc[-(SWING_LOOKBACK + 2) : -2].max())
      risk = swing_high - close_curr
      if risk > 0:
        return {
            "symbol": tv_name,
            "action": "SHORT 🔴",
            "price": close_curr,
            "sl": swing_high,
            "tp1": close_curr - (risk * TP1_RATIO),
            "tp2": close_curr - (risk * TP2_RATIO),
        }

  except Exception as e:
    print(f"Erreur sur {tv_name}: {e}")

  return None


# ==============================================================================
# 6. BOUCLE DU BOT AVEC NOTIFICATION TELEGRAM
# ==============================================================================
def run_bot_loop():
  while True:
    print(
        f"\n--- Scan 4H démarré le {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')} ---"
    )

    for tv_name, yf_ticker in ASSETS.items():
      res = analyze_asset(tv_name, yf_ticker)
      if res:
        msg = (
            f"🚨 *NOUVEAU SIGNAL TRADING (4H)* 🚨\n\n"
            f"🔹 Actif : `{res['symbol']}`\n"
            f"🔹 Ordre : *{res['action']}*\n"
            f"🔹 Entrée : `{res['price']:.5f}`\n"
            f"🔹 Stop Loss : `{res['sl']:.5f}`\n"
            f"🔹 TP 1 (50%) : `{res['tp1']:.5f}` (1:1)\n"
            f"🔹 TP 2 (50%) : `{res['tp2']:.5f}` (1:2)"
        )
        # Envoi sur Telegram
        send_telegram_message(msg)
        print(f"🎯 Signal envoyé pour {res['symbol']}")

      time.sleep(1)  # Petite pause pour éviter le blocage yfinance (Rate Limit)

    print("\n💤 Fin du scan. Prochaine vérification dans 1 heure.")
    time.sleep(3600)


# ==============================================================================
# 7. LANCEMENT
# ==============================================================================
if __name__ == "__main__":
  # Lancement du bot en arrière-plan
  bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
  bot_thread.start()

  # Lancement du serveur web Flask pour Render
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)
