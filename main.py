import os
import time
import requests
import numpy as np
import pandas as pd
import yfinance as yf

# ==========================================
# 1. CONFIGURATION & PARAMÈTRES GÉNÉRAUX
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_TOKEN_TELEGRAM_ICI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "TON_CHAT_ID_ICI")

CAPITAL_EUR = 10000.0  # Capital de départ en EUR
RISK_PERCENT = 0.01    # 1% de risque par trade (100 €)

ASSETS = {
    # Forex
    "EURUSD=X": {"name": "EUR/USD", "tv_symbol": "FX:EURUSD", "base_ccy": "USD"},
    "GBPUSD=X": {"name": "GBP/USD", "tv_symbol": "FX:GBPUSD", "base_ccy": "USD"},
    "USDJPY=X": {"name": "USD/JPY", "tv_symbol": "FX:USDJPY", "base_ccy": "JPY"},
    "GBPJPY=X": {"name": "GBP/JPY", "tv_symbol": "FX:GBPJPY", "base_ccy": "JPY"},
    "AUDUSD=X": {"name": "AUD/USD", "tv_symbol": "FX:AUDUSD", "base_ccy": "USD"},
    "USDCAD=X": {"name": "USD/CAD", "tv_symbol": "FX:USDCAD", "base_ccy": "CAD"},
    "USDCHF=X": {"name": "USD/CHF", "tv_symbol": "FX:USDCHF", "base_ccy": "CHF"},
    "EURGBP=X": {"name": "EUR/GBP", "tv_symbol": "FX:EURGBP", "base_ccy": "GBP"},
    "EURJPY=X": {"name": "EUR/JPY", "tv_symbol": "FX:EURJPY", "base_ccy": "JPY"},
    
    # Indices
    "^GSPC":    {"name": "S&P 500", "tv_symbol": "SPX", "base_ccy": "USD"},
    "^NDX":     {"name": "Nasdaq 100", "tv_symbol": "NDX", "base_ccy": "USD"},
    "^DJI":     {"name": "Dow Jones 30", "tv_symbol": "DJI", "base_ccy": "USD"},
    "^GDAXI":   {"name": "DAX 40", "tv_symbol": "XETR:DAX", "base_ccy": "EUR"},
    "^FCHI":    {"name": "CAC 40", "tv_symbol": "TVC:PX1", "base_ccy": "EUR"},
    "^FTSE":    {"name": "FTSE 100", "tv_symbol": "TVC:UKX", "base_ccy": "GBP"},
    "^AXJO":    {"name": "S&P/ASX 200", "tv_symbol": "ASX:XJO", "base_ccy": "AUD"},

    # Commodities
    "GC=F":     {"name": "Gold (Or)", "tv_symbol": "OANDA:XAUUSD", "base_ccy": "USD"},
    "CL=F":     {"name": "WTI Crude Oil", "tv_symbol": "TVC:USOIL", "base_ccy": "USD"},

    # Cryptomonnaies
    "BTC-USD":  {"name": "Bitcoin", "tv_symbol": "BINANCE:BTCUSDT", "base_ccy": "USD"},
    "ETH-USD":  {"name": "Ethereum", "tv_symbol": "BINANCE:ETHUSDT", "base_ccy": "USD"},
    "SOL-USD":  {"name": "Solana", "tv_symbol": "BINANCE:SOLUSDT", "base_ccy": "USD"},

    # Actions Tech
    "AAPL":     {"name": "Apple", "tv_symbol": "NASDAQ:AAPL", "base_ccy": "USD"},
    "NVDA":     {"name": "Nvidia", "tv_symbol": "NASDAQ:NVDA", "base_ccy": "USD"},
    "TSLA":     {"name": "Tesla", "tv_symbol": "NASDAQ:TSLA", "base_ccy": "USD"},
    "MSFT":     {"name": "Microsoft", "tv_symbol": "NASDAQ:MSFT", "base_ccy": "USD"},
    "AMZN":     {"name": "Amazon", "tv_symbol": "NASDAQ:AMZN", "base_ccy": "USD"}
}


# ==========================================
# 2. INDICATEURS & RECHERCHE DE PIVOTS
# ==========================================
def calculate_tdi(df: pd.DataFrame, rsi_period=13, band_period=34, fast_sma=2, slow_sma=7) -> pd.DataFrame:
    """Calcule l'indicateur Traders Dynamic Index (TDI)."""
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))

    mb = rsi.rolling(window=band_period).mean()

    df['TDI_Green'] = rsi.rolling(window=fast_sma).mean()
    df['TDI_Red'] = rsi.rolling(window=slow_sma).mean()
    df['TDI_Yellow'] = mb

    return df


def find_recent_swing_low(df: pd.DataFrame, max_lookback: int = 15) -> float:
    """Pour LONG : cherche le vrai creux Swing Low le plus proche."""
    if len(df) < max_lookback + 2:
        return float(df['Low'].tail(max_lookback).min())

    for i in range(len(df) - 2, len(df) - max_lookback, -1):
        low_current = df['Low'].iloc[i]
        low_prev = df['Low'].iloc[i - 1]
        low_next = df['Low'].iloc[i + 1]

        if low_current < low_prev and low_current < low_next:
            return float(low_current)

    return float(df['Low'].iloc[-max_lookback:].min())


def find_recent_swing_high(df: pd.DataFrame, max_lookback: int = 15) -> float:
    """Pour SHORT : cherche le vrai sommet Swing High le plus proche."""
    if len(df) < max_lookback + 2:
        return float(df['High'].tail(max_lookback).max())

    for i in range(len(df) - 2, len(df) - max_lookback, -1):
        high_current = df['High'].iloc[i]
        high_prev = df['High'].iloc[i - 1]
        high_next = df['High'].iloc[i + 1]

        if high_current > high_prev and high_current > high_next:
            return float(high_current)

    return float(df['High'].iloc[-max_lookback:].max())


# ==========================================
# 3. NOTIFICATION TELEGRAM
# ==========================================
def send_telegram_alert(message: str):
    """Envoie une notification formatée via Telegram."""
    if TELEGRAM_TOKEN == "TON_TOKEN_TELEGRAM_ICI":
        print("[MOCK TELEGRAM]\n" + message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur d'envoi Telegram : {e}")


# ==========================================
# 4. ANALYSE DU SIGNAL SUR UN ACTIF
# ==========================================
def analyze_asset(symbol: str, meta: dict):
    """Télécharge les données 4H et vérifie les signaux LONG et SHORT."""
    try:
        df = yf.download(symbol, period="60d", interval="4h", progress=False)
        df = df.dropna()

        if df.empty or len(df) < 60:
            return

        df['SMA50'] = df['Close'].rolling(window=50).mean()
        df = calculate_tdi(df)

        # On analyse la dernière bougie clôturée (-2) et la précédente (-3)
        last = df.iloc[-2]
        prev = df.iloc[-3]

        entry_price = float(last['Close'])
        tv_url = f"https://www.tradingview.com/chart/?symbol={meta['tv_symbol']}"
        risk_amount_eur = CAPITAL_EUR * RISK_PERCENT

        # ----------------------------------------------------
        # CONDITION 1 : SIGNAL LONG (ACHAT)
        # ----------------------------------------------------
        long_above_sma = last['Close'] > last['SMA50']
        long_green_red = last['TDI_Green'] >= last['TDI_Red']
        long_cross = (prev['TDI_Red'] <= prev['TDI_Yellow']) and (last['TDI_Red'] > last['TDI_Yellow'])

        if long_above_sma and long_green_red and long_cross:
            swing_low = find_recent_swing_low(df, max_lookback=15)
            sl_price = swing_low * 0.995  # Marge -0.5% sous le creux
            sl_distance = entry_price - sl_price

            if sl_distance > 0:
                tp1_price = entry_price + (sl_distance * 2.0)
                tp2_price = entry_price + (sl_distance * 4.0)
                position_units = risk_amount_eur / sl_distance

                msg = (
                    f"🟢 *SIGNAL DE TRADING 4H (LONG)* 🟢\n\n"
                    f"📊 *Actif* : {meta['name']} (`{symbol}`)\n"
                    f"💵 *Prix d'entrée (Clôture)* : `{entry_price:.4f}`\n"
                    f"🛑 *Stop Loss* : `{sl_price:.4f}` (Creux Swing : {swing_low:.4f})\n\n"
                    f"🎯 *Take Profit 1 (2:1)* : `{tp1_price:.4f}` (Fermer 50%)\n"
                    f"🎯 *Take Profit 2 (4:1)* : `{tp2_price:.4f}` (Fermer 50%)\n\n"
                    f"📐 *Risque engagé* : {risk_amount_eur:.2f} € (1%)\n"
                    f"📦 *Taille indicative* : `{position_units:.2f}` unités\n\n"
                    f"🔗 [Ouvrir le graphique TradingView]({tv_url})"
                )
                send_telegram_alert(msg)
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Signal LONG envoyé pour {meta['name']}")
                return

        # ----------------------------------------------------
        # CONDITION 2 : SIGNAL SHORT (VENTE)
        # ----------------------------------------------------
        short_below_sma = last['Close'] < last['SMA50']
        short_green_red = last['TDI_Green'] <= last['TDI_Red']
        short_cross = (prev['TDI_Red'] >= prev['TDI_Yellow']) and (last['TDI_Red'] < last['TDI_Yellow'])

        if short_below_sma and short_green_red and short_cross:
            swing_high = find_recent_swing_high(df, max_lookback=15)
            sl_price = swing_high * 1.005  # Marge +0.5% au-dessus du sommet
            sl_distance = sl_price - entry_price

            if sl_distance > 0:
                tp1_price = entry_price - (sl_distance * 2.0)
                tp2_price = entry_price - (sl_distance * 4.0)
                position_units = risk_amount_eur / sl_distance

                msg = (
                    f"🔴 *SIGNAL DE TRADING 4H (SHORT)* 🔴\n\n"
                    f"📊 *Actif* : {meta['name']} (`{symbol}`)\n"
                    f"💵 *Prix d'entrée (Clôture)* : `{entry_price:.4f}`\n"
                    f"🛑 *Stop Loss* : `{sl_price:.4f}` (Sommet Swing : {swing_high:.4f})\n\n"
                    f"🎯 *Take Profit 1 (2:1)* : `{tp1_price:.4f}` (Fermer 50%)\n"
                    f"🎯 *Take Profit 2 (4:1)* : `{tp2_price:.4f}` (Fermer 50%)\n\n"
                    f"📐 *Risque engagé* : {risk_amount_eur:.2f} € (1%)\n"
                    f"📦 *Taille indicative* : `{position_units:.2f}` unités\n\n"
                    f"🔗 [Ouvrir le graphique TradingView]({tv_url})"
                )
                send_telegram_alert(msg)
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Signal SHORT envoyé pour {meta['name']}")
                return

    except Exception as e:
        print(f"Erreur d'analyse sur {symbol} : {e}")


# ==========================================
# 5. BOUCLE PRINCIPALE
# ==========================================
def run_bot():
    """Lance le scan automatique des actifs."""
    print("🤖 Bot 4H (LONG & SHORT) démarré. Scan en cours...")
    
    while True:
        print(f"\n--- Début du scan : {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
        for symbol, meta in ASSETS.items():
            analyze_asset(symbol, meta)
            time.sleep(1)
        
        print("--- Scan terminé. Prochain cycle dans 4 heures ---")
        time.sleep(14400)


if __name__ == "__main__":
    run_bot()
