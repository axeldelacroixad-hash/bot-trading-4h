import os
import time
import datetime
import threading
import requests
import pandas as pd
import yfinance as yf
from flask import Flask
import zoneinfo

# ==========================================
# 0. SERVEUR FLASK ANTI-SOMMEIL (KEEP-ALIVE)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading 4H (Radar 17 actifs) est en ligne et actif !"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# ==========================================
# CONFIGURATION TELEGRAM (En dur pour test local)
# ==========================================
TELEGRAM_BOT_TOKEN = "METS_TON_TOKEN_ICI"
TELEGRAM_CHAT_ID = "METS_TON_CHAT_ID_ICI"

CAPITAL = 10000.0
RISK_AMOUNT = CAPITAL * 0.01  # 1% de risque = 100 €

PARIS_TZ = zoneinfo.ZoneInfo("Europe/Paris")

# Heures de déclenchement (décalées à XX:02 pour s'assurer que la bougie 4H est bien clôturée)
TARGET_HOURS = [0, 4, 8, 12, 16, 20]
TARGET_MINUTE = 2

# ==========================================
# PANIER D'ACTIFS (17 Actifs fixes)
# ==========================================
ASSETS = {
    'CAC40': {'name': 'CAC 40 (France)', 'ticker': '^FCHI', 'desc': 'Les 40 plus grandes entreprises de France'},
    'EU50': {'name': 'Euro Stoxx 50', 'ticker': '^STOXX50E', 'desc': 'Indice vedette de la zone euro'},
    'US100': {'name': 'Nasdaq 100', 'ticker': '^NDX', 'desc': 'Indice technologique américain de référence'},
    'US30': {'name': 'Dow Jones', 'ticker': '^DJI', 'desc': 'Les 30 plus grandes valeurs industrielles US'},
    'DE40': {'name': 'DAX 40 (Allemagne)', 'ticker': '^GDAXI', 'desc': 'Les 40 plus grandes entreprises allemandes'},
    'UK100': {'name': 'FTSE 100 (UK)', 'ticker': '^FTSE', 'desc': 'Indice boursier de Londres'},
    'JP225': {'name': 'Nikkei 225 (Japon)', 'ticker': '^N225', 'desc': 'Principal indice boursier de Tokyo'},
    'HK50': {'name': 'Hang Seng (Hong Kong)', 'ticker': '^HSI', 'desc': 'Indice de la bourse de Hong Kong'},
    'ASX200': {'name': 'ASX 200 (Australie)', 'ticker': '^AXJO', 'desc': 'Indice boursier australien'},
    'SPX': {'name': 'S&P 500 (US)', 'ticker': '^GSPC', 'desc': 'Les 500 plus grandes entreprises US'},
    'GOLD': {'name': 'Or (Gold)', 'ticker': 'GC=F', 'desc': 'Valeur refuge et matière première précieuse'},
    'SILVER': {'name': 'Argent (Silver)', 'ticker': 'SI=F', 'desc': 'Métal précieux industriel et monétaire'},
    'OIL': {'name': 'Pétrole WTI', 'ticker': 'CL=F', 'desc': 'Matière première énergétique'},
    'EURUSD': {'name': 'EUR/USD', 'ticker': 'EURUSD=X', 'desc': 'Paire de devises majeure'},
    'GBPUSD': {'name': 'GBP/USD', 'ticker': 'GBPUSD=X', 'desc': 'Paire livre sterling / dollar'},
    'USDJPY': {'name': 'USD/JPY', 'ticker': 'USDJPY=X', 'desc': 'Paire dollar / yen japonais'},
    'AUDUSD': {'name': 'AUD/USD', 'ticker': 'AUDUSD=X', 'desc': 'Paire dollar australien / dollar US'}
}

# ==========================================
# FONCTION D'ENVOI TELEGRAM
# ==========================================
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erreur : Tokens Telegram non trouvés.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur d'envoi Telegram : {e}")

# ==========================================
# CŒUR DU SCANNER 4H
# ==========================================
def scan_live_market():
    now_paris = datetime.datetime.now(PARIS_TZ)
    now_str = now_paris.strftime("%d/%m/%Y - %H:%M")
    total_checked = 0
    signals_found = 0
    
    opportunities = []
    
    print(f"\n--- DÉBUT DU SCAN LIVE ({now_str}) ---")
    
    for symbol, info in ASSETS.items():
        df = yf.download(info['ticker'], period="5d", interval="1h", progress=False)
        
        if df.empty or len(df) < 50:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        total_checked += 1

        # Indicateurs : SMA 50 et TDI (RSI 13, Red 3, Yellow 21)
        df['SMA50'] = df['Close'].rolling(window=50).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=13).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=13).mean()
        df['RSI'] = 100 - (100 / (1 + (gain / loss)))
        
        df['TDI_Red'] = df['RSI'].rolling(window=3).mean()
        df['TDI_Yellow'] = df['RSI'].rolling(window=21).mean()
        
        # ATR pour le Stop Loss
        high_low = df['High'] - df['Low']
        high_close = abs(df['High'] - df['Close'].shift())
        low_close = abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(window=14).mean()
        
        last = df.iloc[-2]
        prev = df.iloc[-3]
        
        price = last['Close']
        atr = last['ATR']
        
        if pd.isna(atr) or atr == 0:
            continue

        # --- CONDITION LONG (ACHAT) ---
        cross_up = (prev['TDI_Red'] <= prev['TDI_Yellow']) and (last['TDI_Red'] > last['TDI_Yellow'])
        near_sma_long = price >= (last['SMA50'] * 0.99)
        
        if cross_up and near_sma_long:
            signals_found += 1
            sl_distance = atr * 1.5
            sl_price = price - sl_distance
            position_size = (RISK_AMOUNT / sl_distance) * price
            
            msg = (
                f"🟢 *{now_str}* | *{symbol}* | {info['name']}\n"
                f"• Prix actuel : {price:.2f}\n"
                f"• SL ATR (max) : {sl_price:.2f}\n"
                f"• Position (1%) : {position_size:.2f} €"
            )
            opportunities.append(msg)

        # --- CONDITION SHORT (VENTE) ---
        cross_down = (prev['TDI_Red'] >= prev['TDI_Yellow']) and (last['TDI_Red'] < last['TDI_Yellow'])
        near_sma_short = price <= (last['SMA50'] * 1.01)
        
        if cross_down and near_sma_short:
            signals_found += 1
            sl_distance = atr * 1.5
            sl_price = price + sl_distance
            position_size = (RISK_AMOUNT / sl_distance) * price
            
            msg = (
                f"🔴 *{now_str}* | *{symbol}* | {info['name']}\n"
                f"• Prix actuel : {price:.2f}\n"
                f"• SL ATR (max) : {sl_price:.2f}\n"
                f"• Position (1%) : {position_size:.2f} €"
            )
            opportunities.append(msg)

    # Envoi des résultats sur Telegram
    if signals_found > 0:
        for opp in opportunities:
            send_telegram(opp)
    else:
        control_message = f"`[{now_str}] Scan 4H : {total_checked} actifs contrôlés - Rien pour le moment.`"
        send_telegram(control_message)
        print(f"[{now_str}] Scan 4H : {total_checked} actifs contrôlés - Rien pour le moment.")

# ==========================================
# GESTION DES HORAIRES (PLANIFICATION EXACTE)
# ==========================================
def get_seconds_until_next_scan():
    now = datetime.datetime.now(PARIS_TZ)
    for h in TARGET_HOURS:
        target = now.replace(hour=h, minute=TARGET_MINUTE, second=0, microsecond=0)
        if target > now:
            return (target - now).total_seconds()
            
    tomorrow = now + datetime.timedelta(days=1)
    target = tomorrow.replace(hour=TARGET_HOURS[0], minute=TARGET_MINUTE, second=0, microsecond=0)
    return (target - now).total_seconds()

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    print("Démarrage du bot de trading 4H (Radar 17 actifs) avec planification horaire...")
    
    # Premier scan immédiat pour tester
    scan_live_market()
    
    while True:
        try:
            sleep_seconds = get_seconds_until_next_scan()
            now_p = datetime.datetime.now(PARIS_TZ)
            next_scan_dt = now_p + datetime.timedelta(seconds=sleep_seconds)
            print(f"Prochain scan prévu à {next_scan_dt.strftime('%H:%M:%S')} (dans {int(sleep_seconds // 60)} minutes).\n")
            time.sleep(sleep_seconds)
            
            now_p = datetime.datetime.now(PARIS_TZ)
            print(f"[{now_p.strftime('%Y-%m-%d %H:%M:%S')}] Lancement du scan...")
            scan_live_market()
            
        except Exception as e:
            print(f"Erreur globale : {e}")
            time.sleep(300)
