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
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            df = add_tdi_indicators(df)
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            price = float(last['Close'])
            
            # Recherche du dernier creux ou sommet sur les 5 dernières bougies pour le SL
            recent_low = df['Low'].iloc[-5:].min()
            recent_high = df['High'].iloc[-5:].max()

            # --- CONDITION LONG (ACHAT) : La ligne Rouge croise la Jaune vers le haut, Verte au-dessus ---
            red_cross_up = (prev['TDI_Red'] <= prev['TDI_Yellow']) and (last['TDI_Red'] > last['TDI_Yellow'])
            green_above = last['TDI_Green'] >= last['TDI_Red']
            near_sma_long = price >= (last['SMA50'] * 0.99)
            
            if red_cross_up and green_above and near_sma_long:
                sl_price = recent_low * 0.999  # SL juste sous le dernier creux
                sl_distance = price - sl_price
                
                if sl_distance <= 0:
                    continue
                
                # Calcul de la position pour 1% de risque
                position_size = (RISK_AMOUNT / sl_distance) * price
                
                # Plafond strict sans effet de levier (max capital = 10 000 €)
                if position_size > CAPITAL:
                    position_size = CAPITAL
                
                msg = (
                    f"🟢 *{now_str}* | *{symbol}* | **{info['name']}**\n"
                    f"🌍 **Région :** {info['country']}\n"
                    f"🏢 **Secteur :** {info['sector']}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"• Signal : **LONG (Achat)**\n"
                    f"• Prix actuel : {price:.3f}\n"
                    f"• Stop Loss (Dernier Creux) : {sl_price:.3f}\n"
                    f"• Montant engagé : {position_size:.2f} € (Sans levier)"
                )
                opportunities.append(msg)

            # --- CONDITION SHORT (VENTE) : La ligne Rouge croise la Jaune vers le bas, Verte en dessous ---
            red_cross_down = (prev['TDI_Red'] >= prev['TDI_Yellow']) and (last['TDI_Red'] < last['TDI_Yellow'])
            green_below = last['TDI_Green'] <= last['TDI_Red']
            near_sma_short = price <= (last['SMA50'] * 1.01)
            
            if red_cross_down and green_below and near_sma_short:
                sl_price = recent_high * 1.001  # SL juste au-dessus du dernier sommet
                sl_distance = sl_price - price
                
                if sl_distance <= 0:
                    continue
                
                position_size = (RISK_AMOUNT / sl_distance) * price
                
                # Plafond strict sans effet de levier
                if position_size > CAPITAL:
                    position_size = CAPITAL
                
                msg = (
                    f"🔴 *{now_str}* | *{symbol}* | **{info['name']}**\n"
                    f"🌍 **Région :** {info['country']}\n"
                    f"🏢 **Secteur :** {info['sector']}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"• Signal : **SHORT (Vente)**\n"
                    f"• Prix actuel : {price:.3f}\n"
                    f"• Stop Loss (Dernier Sommet) : {sl_price:.3f}\n"
                    f"• Montant engagé : {position_size:.2f} € (Sans levier)"
                )
                opportunities.append(msg)
                
        except Exception as e:
            print(f"Erreur sur {symbol}: {e}")
            
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
        time.sleep(4 * 3600)

@app.route('/')
def home():
    return "Le bot de trading swing 4H est en ligne et actif !"

@app.route('/test-scan')
def test_scan():
    scan_markets()
    return "Scan manuel exécuté avec succès !"

if __name__ == '__main__':
    t = threading.Thread(target=run_bot_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
