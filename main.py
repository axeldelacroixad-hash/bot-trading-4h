import time
import pandas as pd
import numpy as np
import yfinance as yf

# ==============================================================================
# 1. LISTE COMPLETE DES 26 ACTIFS (MAPPING YFINANCE / TRADINGVIEW)
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
# 2. PARAMÈTRES ET CONFIGURATION DE LA STRATÉGIE
# ==============================================================================
TIMEFRAME = "4h"
RSI_LEN = 13
BAND_LEN = 34
BAND_MULT = 1.6185
PRICE_LEN = 2
SIGNAL_LEN = 7
SMA_LEN = 50

SWING_LOOKBACK = 10     # Fenêtre de recherche Swing Low/High pour le SL
TP1_RATIO = 1.0         # Ratio pour le premier objectif (sécurisation partielle)
TP2_RATIO = 2.0         # Ratio pour le deuxième objectif final

# ==============================================================================
# 3. CALCULS TECHNIQUES (RSI WILDER + TDI EXACT)
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
# 4. ANALYSE STRICTE DES CONDITIONS ET CALCUL DU DOUBLE TP
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

        long_signal = cross_up and (price_curr > signal_curr) and (close_curr > sma50_curr)
        short_signal = cross_down and (price_curr < signal_curr) and (close_curr < sma50_curr)

        # Calcul SL et DOUBLE TP
        if long_signal:
            swing_low = float(df["Low"].iloc[-(SWING_LOOKBACK + 2):-2].min())
            risk = close_curr - swing_low
            if risk > 0:
                return {
                    "symbol": tv_name,
                    "action": "LONG 🟢",
                    "price": close_curr,
                    "sl": swing_low,
                    "tp1": close_curr + (risk * TP1_RATIO),
                    "tp2": close_curr + (risk * TP2_RATIO),
                    "risk_pts": risk
                }

        elif short_signal:
            swing_high = float(df["High"].iloc[-(SWING_LOOKBACK + 2):-2].max())
            risk = swing_high - close_curr
            if risk > 0:
                return {
                    "symbol": tv_name,
                    "action": "SHORT 🔴",
                    "price": close_curr,
                    "sl": swing_high,
                    "tp1": close_curr - (risk * TP1_RATIO),
                    "tp2": close_curr - (risk * TP2_RATIO),
                    "risk_pts": risk
                }

    except Exception as e:
        print(f"Erreur sur {tv_name} ({yf_ticker}): {e}")

    return None

# ==============================================================================
# 5. BOUCLE DE SCAN
# ==============================================================================
def run_scan():
    print("==================================================================")
    print(f"🚀 SCAN BOT 4H (Double TP) - {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("==================================================================")
    
    signals_found = 0
    for tv_name, yf_ticker in ASSETS.items():
        res = analyze_asset(tv_name, yf_ticker)
        if res:
            signals_found += 1
            print(f"\n🎯 [OPPORTUNITÉ DÉTECTÉE] {res['symbol']}")
            print(f"   ► Ordre      : {res['action']}")
            print(f"   ► Prix Entrée: {res['price']:.5f}")
            print(f"   ► Stop Loss  : {res['sl']:.5f}")
            print(f"   ► TP 1 (50%) : {res['tp1']:.5f} (Ratio 1:1)")
            print(f"   ► TP 2 (50%) : {res['tp2']:.5f} (Ratio 1:2)")
        else:
            print(f"⏳ {tv_name} : RAS", end=" | ")
            
    if signals_found == 0:
        print("\n\nAucun signal validé sur l'ensemble des 26 actifs pour ce cycle.")

if __name__ == "__main__":
    run_scan()
