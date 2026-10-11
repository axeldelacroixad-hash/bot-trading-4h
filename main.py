import os
import time
from datetime import datetime
import pytz
import pandas as pd
import yfinance as yf
from flask import Flask
import threading

app = Flask(__name__)

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CAPITAL = 10000.0  # Capital en €
RISK_PCT = 0.01    # Risque de 1% par trade
RISK_AMOUNT = CAPITAL * RISK_PCT

PARIS_TZ = pytz.timezone('Europe/Paris')

# Liste des 17 actifs avec leurs infos de région et secteur
ASSETS = {
    "EURUSD=X": {"name": "EUR/USD", "country": "Zone Euro / États-Unis", "sector": "Forex (Devises)"},
    "GBPUSD=X": {"name": "GBP/USD", "country": "Royaume-Uni / États-Unis", "sector": "Forex (Devises)"},
    "USDJPY=X": {"name": "USD/JPY", "country": "États-Unis / Japon", "sector": "Forex (Devises)"},
    "AUDUSD=X": {"name": "AUD/USD", "country": "Australie / États-Unis", "sector": "Forex (Devises)"},
    "USDCAD=X": {"name": "USD/CAD", "country": "États-Unis / Canada", "sector": "Forex (Devises)"},
    "EURJPY=X": {"name": "EUR/JPY", "country": "Zone Euro / Japon", "sector": "Forex (Devises)"},
    "GBPJPY=X": {"name": "GBP/JPY", "country": "Royaume-Uni / Japon", "sector": "Forex (Devises)"},
    "GC=X": {"name": "Or (Gold)", "country": "Mondial", "sector": "Matières Premières (Metaux)"},
    "CL=X": {"name": "Pétrole WTI", "country": "États-Unis / Mondial", "sector": "Matières Premières (Énergie)"},
    "BTC-USD": {"name": "Bitcoin", "country": "Mondial", "sector": "Cryptomonnaie"},
    "ETH-USD": {"name": "Ethereum", "country": "Mondial", "sector": "Cryptomonnaie"},
    "^FCHI": {"name": "CAC 40", "country": "France", "sector": "Indices boursiers"},
    "^GDAXI": {"name": "DAX 40", "country": "Allemagne", "sector": "Indices boursiers"},
    "^FTSE": {"name": "FTSE 100", "country": "Royaume-Uni", "sector": "Indices boursiers"},
    "^SPX": {"name": "S&P 500", "country": "États-Unis", "sector": "Indices boursiers"},
    "^NDX": {"name": "Nasdaq 100", "country": "États-Unis", "sector": "Indices boursiers"},
    "^N225": {"name": "Nikkei 225", "country": "Japon", "sector": "Indices boursiers"}
}

def send_telegram_message(message):
    import requests
    if not TOKEN or not CHAT_ID:
        print("Erreur : Token ou Chat ID Telegram manquant.")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Erreur d'envoi Telegram : {e}")

def add_tdi_indicators(df):
    # Calcul du RSI (Période 13)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=13).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=13).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    # Ligne Verte (Price Line - Période 2)
    df['TDI_Green'] = rsi.rolling(window=2).mean()
    
    # Ligne Rouge (Signal Line - Période 7)
    df['TDI_Red'] = rsi.rolling(window=7).mean()
    
    # Ligne Jaune (Middle Band / Baseline - Période 34)
    df['TDI_Yellow'] = rsi.rolling(window=34).mean()
    
    # SMA 50 pour le filtre de prix
    df['SMA50'] = df['Close'].rolling(window=50).mean()
    
    # ATR (14) pour le Stop Loss
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['ATR'] = true_range.rolling(window=14).mean()
    
    return df

def scan_markets():
    print("--- DÉBUT DU SCAN DES MARCHÉS (4H) ---")
    opportunities = []
    now_str = datetime.now(PARIS_TZ).strftime("%d/%m/%Y-%H:%M")
    
    for symbol, info in ASSETS.items():
        try:
            # Récupération des données 4H
            df = yf.download(symbol, period="60d", interval="4h", progress=False)
            if df.empty or len(df) < 50:
                continue
            
            # Nettoyage des index multi-niveaux si présents dans yfinance
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            df = add_tdi_indicators(df)
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            price = float(last['Close'])
            atr = float(last['ATR'])
            
            if pd.isna(atr) or atr == 0:
                continue

            # --- CONDITION LONG (ACHAT) ---
            cross_up = (prev['TDI_Green'] <= prev['TDI_Red']) and (last['TDI_Green'] > last['TDI_Red'])
            trend_long = last['TDI_Red'] >= last['TDI_Yellow']
            near_sma_long = price >= (last['SMA50'] * 0.99)
            
            if cross_up and trend_long and near_sma_long:
                sl_distance = atr * 1.5
                sl_price = price - sl_distance  # SL en dessous pour un LONG
                position_size = (RISK_AMOUNT / sl_distance) * price
                
                msg = (
                    f"🟢 *{now_str}* | *{symbol}* | **{info['name']}**\n"
                    f"🌍 **Région :** {info['country']}\n"
                    f"🏢 **Secteur :** {info['sector']}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"• Signal : **LONG (Achat)**\n"
                    f"• Prix actuel : {price:.3f}\n"
                    f"• Stop Loss : {sl_price:.3f}\n"
                    f"• Position (1%) : {position_size:.2f} €"
                )
                opportunities.append(msg)

            # --- CONDITION SHORT (VENTE) ---
            cross_down = (prev['TDI_Green'] >= prev['TDI_Red']) and (last['TDI_Green'] < last['TDI_Red'])
            trend_short = last['TDI_Red'] <= last['TDI_Yellow']
            near_sma_short = price <= (last['SMA50'] * 1.01)
            
            if cross_down and trend_short and near_sma_short:
                sl_distance = atr * 1.5
                sl_price = price + sl_distance  # SL au-dessus pour un SHORT
                position_size = (RISK_AMOUNT / sl_distance) * price
                
                msg = (
                    f"🔴 *{now_str}* | *{symbol}* | **{info['name']}**\n"
                    f"🌍 **Région :** {info['country']}\n"
                    f"🏢 **Secteur :** {info['sector']}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"• Signal : **SHORT (Vente)**\n"
                    f"• Prix actuel : {price:.3f}\n"
                    f"• Stop Loss : {sl_price:.3f}\n"
                    f"• Position (1%) : {position_size:.2f} €"
                )
                opportunities.append(msg)
                
        except Exception as e:
            print(f"Erreur sur {symbol}: {e}")
            
    # Envoi des alertes trouvées
    if opportunities:
        for alert in opportunities:
            send_telegram_message(alert)
            time.sleep(1)
    else:
        print("Aucun signal détecté lors de ce scan.")
    print("--- FIN DU SCAN ---")

def run_bot_loop():
    while True:
        try:
            scan_markets()
        except Exception as e:
            print(f"Erreur dans la boucle du bot : {e}")
        # Attend 4 heures avant le prochain scan
        time.sleep(4 * 3600)

@app.route('/')
def home():
    return "Le bot de trading swing 4H est en ligne et actif !"

@app.route('/test-scan')
def test_scan():
    scan_markets()
    return "Scan manuel exécuté avec succès ! Vérifie ton Telegram."

if __name__ == '__main__':
    # Lancement du thread de fond pour le scan des marchés
    t = threading.Thread(target=run_bot_loop, daemon=True)
    t.start()
    
    # Lancement de l'application Flask pour Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
