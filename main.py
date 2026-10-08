import os
import time
import datetime
import threading
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from flask import Flask

# ==========================================
# 0. SERVEUR FLASK ANTI-SOMMEIL (KEEP-ALIVE)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading 4H est en ligne et actif !"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# ==========================================
# CONFIGURATION TELEGRAM & PARAMÈTRES
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

CAPITAL = 10000.0       # Capital de départ (€)
RISK_PCT = 0.01        # 1 % de risque par trade
RR_RATIO = 2.5         # Ratio Risk/Reward 1:2.5

# Fuseau horaire Français
import zoneinfo
PARIS_TZ = zoneinfo.ZoneInfo("Europe/Paris")

# ==========================================
# 1. BASE FIXE MINIMALE
# ==========================================
FIXED_BASE = [
    "^GSPC", "^IXIC", "^DJI", "^FCHI", "^GDAXI", "^N225", "^FTSE",
    "GC=F", "SI=F", "CL=F",
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD"
]

# ==========================================
# 2. ENDPOINTS JSON DIRECTS (SCREENER DYNAMIQUE)
# ==========================================
def fetch_yahoo_json_screener(scr_id, count=200):
    tickers = []
    url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    params = {"scrIds": scr_id, "count": count}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("finance", {}).get("result", [])
            if results and "quotes" in results[0]:
                tickers = [q["symbol"] for q in results[0]["quotes"] if "symbol" in q]
    except Exception as e:
        print(f"Erreur API Screener ({scr_id}): {e}")
    return tickers

def get_dynamic_universe():
    dynamic_set = set()
    screeners = [
        "most_actives", "day_gainers", "growth_technology_stocks",
        "top_mutual_funds", "undervalued_growth_stocks", "most_shorted_stocks",
        "aggressive_small_caps", "small_cap_gainers", "day_losers"
    ]
    for scr_id in screeners:
        found = fetch_yahoo_json_screener(scr_id, count=200)
        dynamic_set.update(found)
        time.sleep(0.1)
        
    print(f"🔍 Tickers dynamiques trouvés en direct : {len(dynamic_set)}")
    return list(dynamic_set)

def build_universe():
    global_pool = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "INTC", "CRM", "ORCL", "ADBE", "AVGO",
        "TXN", "QCOM", "NOW", "AMAT", "MU", "PANW", "LRCX", "PLTR", "UBER", "ABNB", "COIN", "PYPL", "NFLX",
        "CRWD", "DDOG", "NET", "SNOW", "ZM", "DOCU", "IBM", "CSCO", "ACN", "HPQ", "DELL", "SMCI", "ARM", "MSTR",
        "JNJ", "PFE", "ABBV", "LLY", "MRK", "TMO", "DHR", "ABT", "BMY", "AMGN", "GILD", "CVS", "CI", "ELV",
        "BRK-B", "JPM", "V", "MA", "BAC", "GS", "MS", "C", "WFC", "BLK", "SCHW", "AXP", "SPGI", "CME",
        "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "NKE", "SBUX", "MCD", "WMT", "COST", "TGT",
        "MC.PA", "OR.PA", "TTE.PA", "SAN.PA", "AIR.PA", "RMS.PA", "SAF.PA", "BNP.PA", "GLE.PA", "DG.PA", "VIE.PA",
        "ASML.AS", "SAP.DE", "SIE.DE", "ALV.DE", "BAYN.DE", "DBK.DE", "BMW.DE", "MBG.DE", "VOW3.DE",
        "NESN.SW", "NOVN.SW", "UBSG.SW", "SHEL.L", "AZN.L", "BP.L", "HSBA.L", "ULVR.L", "IBE.MC", "ITX.MC",
        "SPY", "QQQ", "CW8.PA", "IWDA.AS", "SMH", "SOXX", "BOTZ", "ARKK", "CSPX.AS", "MEUD.PA", "IWM", "EEM",
        "7203.T", "6758.T", "9984.T", "6861.T", "7751.T", "9983.T", "TSM", "BABA", "BIDU", "JD", "PDD", "NIO"
    ]
    
    dynamic_tickers = get_dynamic_universe()
    full_list = FIXED_BASE + dynamic_tickers + global_pool
    
    cleaned = []
    for t in full_list:
        if "=X" in t and t not in ["GC=F", "SI=F"]:
            continue
        if t.endswith(".BA") or t.endswith(".MX"):
            continue
        if len(t) == 5 and t.endswith("X"):
            continue
        if len(t) <= 10 and not t.startswith("0P"):
            cleaned.append(t)
        
    return list(set(cleaned))

# ==========================================
# 3. CALCUL DU TDI & SCAN
# ==========================================
def calculate_tdi(df, rsi_period=14, fast_ma=2, slow_ma=7):
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/rsi_period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/rsi_period, adjust=False).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    fast_line = rsi.rolling(window=fast_ma).mean()
    slow_line = rsi.rolling(window=slow_ma).mean()
    sma50 = df['Close'].rolling(window=50).mean()
    
    df['TDI_Fast'] = fast_line
    df['TDI_Slow'] = slow_line
    df['SMA50'] = sma50
    return df

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erreur: Token ou Chat ID Telegram manquant dans Replit Secrets.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur envoi Telegram: {e}")

def run_scan():
    universe = build_universe()
    
    # Heure locale de Paris
    now_paris = datetime.datetime.now(PARIS_TZ)
    now_str = now_paris.strftime("%d/%m/%Y %H:%M")
    
    print(f"📊 Lancement de l'analyse sur {len(universe)} actifs uniques...")
    
    opportunities = []
    scanned_count = 0
    
    for ticker in universe:
        try:
            df = yf.download(ticker, period="1mo", interval="1h", progress=False)
            if df.empty or len(df) < 50:
                continue
            
            df_4h = df.resample('4h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()
            
            if len(df_4h) < 50:
                continue
                
            df_4h = calculate_tdi(df_4h)
            scanned_count += 1
            
            row_prev = df_4h.iloc[-2]
            row_prev2 = df_4h.iloc[-3]
            
            close_price = float(row_prev['Close'])
            sma50 = float(row_prev['SMA50'])
            fast_curr = float(row_prev['TDI_Fast'])
            slow_curr = float(row_prev['TDI_Slow'])
            fast_prev = float(row_prev2['TDI_Fast'])
            slow_prev = float(row_prev2['TDI_Slow'])
            
            is_buy = (fast_prev <= slow_prev) and (fast_curr > slow_curr) and (close_price > sma50)
            is_sell = (fast_prev >= slow_prev) and (fast_curr < slow_curr) and (close_price < sma50)
            
            if is_buy or is_sell:
                info = yf.Ticker(ticker).info
                long_name = info.get('longName') or info.get('shortName') or ticker
                sector = info.get('sector', 'ETF / Indices')
                summary = info.get('longBusinessSummary', '')
                
                fund_text = f"{sector}."
                if summary:
                    fund_text += " " + summary[:90] + "..."
                
                high_val = float(row_prev['High'])
                low_val = float(row_prev['Low'])
                
                if is_buy:
                    sl = low_val
                    risk_per_unit = close_price - sl
                    if risk_per_unit <= 0: continue
                    tp = close_price + (risk_per_unit * RR_RATIO)
                    position_size = int((CAPITAL * RISK_PCT) / risk_per_unit)
                    emoji = "🟢"
                else:
                    sl = high_val
                    risk_per_unit = sl - close_price
                    if risk_per_unit <= 0: continue
                    tp = close_price - (risk_per_unit * RR_RATIO)
                    position_size = int((CAPITAL * RISK_PCT) / risk_per_unit)
                    emoji = "🔴"
                
                if position_size > 0:
                    opp_text = (
                        f"{emoji} *{ticker}* — {long_name}\n"
                        f"💡 _{fund_text}_\n"
                        f"🎯 *SL :* {sl:.2f} | *TP :* {tp:.2f} | *Taille :* {position_size} unités"
                    )
                    opportunities.append(opp_text)
                    
        except Exception:
            continue

    report_header = (
        f"📊 *Rapport 4H — {now_str}*\n"
        f"• *Scannés :* {scanned_count}/{len(universe)}\n"
        f"• *Opportunités :* {len(opportunities)}"
    )
    
    if len(opportunities) == 0:
        send_telegram_message(report_header)
    else:
        full_msg = report_header + "\n\n" + "\n\n".join(opportunities)
        send_telegram_message(full_msg)

if __name__ == "__main__":
    # Lancement du serveur Web Flask en arrière-plan
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    print("Démarrage du bot de trading 4H avec Anti-Sommeil...")
    while True:
        try:
            now_p = datetime.datetime.now(PARIS_TZ)
            print(f"[{now_p.strftime('%Y-%m-%d %H:%M:%S')}] Lancement du scan...")
            run_scan()
            print("Scan terminé. Attente de 4 heures...")
            time.sleep(4 * 3600)
        except Exception as e:
            print(f"Erreur globale : {e}")
            time.sleep(300)
