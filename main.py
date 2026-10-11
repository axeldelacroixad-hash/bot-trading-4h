import os
import time
from datetime import datetime
import pytz
import pandas as pd
import yfinance as yf
from flask import Flask
import threading
import requests

app = Flask(__name__)

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CAPITAL = 10000.0  # Capital en €
RISK_PCT = 0.01    # Risque de 1% par trade
RISK_AMOUNT = CAPITAL * RISK_PCT
RISQUE_DU_TRADE = 2

PARIS_TZ = pytz.timezone('Europe/Paris')

# Liste complète des actifs (Forex, Matières premières, Cryptos, Indices généraux et Tech mondiale)
ASSETS = {
    # --- Forex & Actifs de base ---
    "EURUSD=X": {"name": "EUR/USD", "country": "Zone Euro / États-Unis", "sector": "Forex (Devises)"},
    "GBPUSD=X": {"name": "GBP/USD", "country": "Royaume-Uni / États-Unis", "sector": "Forex (Devises)"},
    "USDJPY=X": {"name": "USD/JPY", "country": "États-Unis / Japon", "sector": "Forex (Devises)"},
    "AUDUSD=X": {"name": "AUD/USD", "country": "Australie / États-Unis", "sector": "Forex (Devises)"},
    "USDCAD=X": {"name": "USD/CAD", "country": "États-Unis / Canada", "sector": "Forex (Devises)"},
    "EURJPY=X": {"name": "EUR/JPY", "country": "Zone Euro / Japon", "sector": "Forex (Devises)"},
    "GBPJPY=X": {"name": "GBP/JPY", "country": "Royaume-Uni / Japon", "sector": "Forex (Devises)"},
    "GLD": {"name": "Or (ETF Gold)", "country": "Mondial", "sector": "Matières Premières (Metaux)"},
    "USO": {"name": "Pétrole (ETF USO)", "country": "États-Unis / Mondial", "sector": "Matières Premières (Énergie)"},
    "BTC-USD": {"name": "Bitcoin", "country": "Mondial", "sector": "Cryptomonnaie"},
    "ETH-USD": {"name": "Ethereum", "country": "Mondial", "sector": "Cryptomonnaie"},
    
    # --- Indices boursiers initiaux ---
    "^FCHI": {"name": "CAC 40", "country": "France", "sector": "Indices boursiers"},
    "^GDAXI": {"name": "DAX 40", "country": "Allemagne", "sector": "Indices boursiers"},
    "^FTSE": {"name": "FTSE 100", "country": "Royaume-Uni", "sector": "Indices boursiers"},
    "^SPX": {"name": "S&P 500", "country": "États-Unis", "sector": "Indices boursiers"},
    "^NDX": {"name": "Nasdaq 100", "country": "États-Unis", "sector": "Indices boursiers"},
    "^N225": {"name": "Nikkei 225", "country": "Japon", "sector": "Indices boursiers"},

    # --- Nouveaux indices boursiers internationaux ---
    "^DJI": {"name": "Dow Jones Industrial", "country": "États-Unis", "sector": "Indices boursiers"},
    "^RUT": {"name": "Russell 2000 (Small Caps)", "country": "États-Unis", "sector": "Indices boursiers"},
    "^STOXX50E": {"name": "Euro Stoxx 50", "country": "Zone Euro", "sector": "Indices boursiers"},
    "^AXJO": {"name": "S&P/ASX 200", "country": "Australie", "sector": "Indices boursiers"},
    "^HSI": {"name": "Hang Seng Index", "country": "Hong Kong / Asie", "sector": "Indices boursiers"},

    # --- Nouveaux indices & secteurs Technologiques géographiques ---
    "^TWII": {"name": "Taiwan Weighted (Tech/Puces)", "country": "Taïwan", "sector": "Technologie & Semi-conducteurs"},
    "^KS11": {"name": "KOSPI (Tech & Électronique)", "country": "Corée du Sud", "sector": "Technologie & Électronique"},
    "^SOX": {"name": "Philadelphia Semiconductor", "country": "États-Unis", "sector": "Technologie (Semi-conducteurs)"},
    "XLK": {"name": "Technology Select Sector (ETF)", "country": "États-Unis", "sector": "Technologie (Software/Hardware)"},
    "^SX8P": {"name": "STOXX Europe Tech", "country": "Europe", "sector": "Technologie (Europe)"}
}

def send_telegram_message(message):
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
    # Calcul du RSI avec la méthode de lissage de Wilder (RMA / EWM) pour correspondre à TradingView (Période 13)
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Lissage de Wilder (alpha = 1 / période)
    avg_gain = gain.ewm(alpha=1/13, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/13, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    # Ligne Verte (Price Line - Période 2)
    df['TDI_Green'] = rsi.rolling(window=2).mean()
    
    # Ligne Rouge (Signal Line - Période 7)
    df['TDI_Red'] = rsi.rolling(window=7).mean()
    
    # Ligne Jaune (Middle Band / Baseline - Période 34)
    df['TDI_Yellow'] = rsi.rolling(window=34).mean()
    
    # SMA 50 pour le filtre de tendance sur le prix
    df['SMA50'] = df['Close'].rolling(window=50).mean()
    
    return df

def scan_markets():
    print("--- DÉBUT DU SCAN DES MARCHÉS (4H) ---")
    opportunities = []
    now_str = datetime.now(PARIS_TZ).strftime("%d/%m/%Y-%H:%M")
    
    for symbol, info in ASSETS.items():
        try:
            # Téléchargement des données 4H
            df = yf.download(symbol, period="60d", interval="4h", progress=False)
            time.sleep(1.5)  # Pause pour éviter le rate-limit de Yahoo
            
            if df.empty or len(df) < 50:
                print(f"Pas assez de données ou échec pour {symbol}")
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

            # --- CONDITION LONG (ACHAT) ---
            red_cross_up = (prev['TDI_Red'] <= prev['TDI_Yellow']) and (last['TDI_Red'] > last['TDI_Yellow'])
            green_above = last['TDI_Green'] >= last['TDI_Red']
            strict_sma_long = price > last['SMA50']
            
            if red_cross_up and green_above and strict_sma_long:
                sl_price = recent_low * 0.995
                sl_distance = price - sl_price
                
                if sl_distance <= 0:
                    continue
                
                position_size = (RISK_AMOUNT / sl_distance) * price
                nb_unite = RISK_AMOUNT / sl_distance
                take_profit = price + (sl_distance * RISQUE_DU_TRADE)
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
                    f"• Prix TP : {take_profit:.3f}\n"
                    f"• Nb d'unités : *{nb_unite:.3f}*\n"
                    f"• Total Trade € : {position_size:.3f}\n"
                )
                opportunities.append(msg)

# --- CONDITION SHORT (VENTE) ---
            red_cross_down = (prev['TDI_Red'] >= prev['TDI_Yellow']) and (last['TDI_Red'] < last['TDI_Yellow'])
            green_below = last['TDI_Green'] <= last['TDI_Red']
            strict_sma_short = price < last['SMA50']
            
            if red_cross_down and green_below and strict_sma_short:
                sl_price = recent_high * 1.001
                sl_distance = sl_price - price
                
                if sl_distance <= 0:
                    continue
                
                position_size = (RISK_AMOUNT / sl_distance) * price
                nb_unite = RISK_AMOUNT / sl_distance
                take_profit = price - (sl_distance * RISQUE_DU_TRADE)
                
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
                    f"• Prix TP : {take_profit:.3f}\n"
                    f"• Nb d'unités : *{nb_unite:.3f}*\n"
                    f"• Total Trade € : {position_size:.3f}\n"
                )
                opportunities.append(msg)
                
        except Exception as e:
            print(f"Erreur sur {symbol}: {e}")
            
    if opportunities:
        for alert in opportunities:
            send_telegram_message(alert)
            time.sleep(1)
    else:
        send_telegram_message(f"⚪ *{now_str}* | Scan 4H terminé : Aucun signal valide sur les 27 actifs.")
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

@app.route('/test-calc/<symbol>')
def test_calculation(symbol):
    try:
        df = yf.download(symbol.upper(), period="30d", interval="4h", progress=False)
        if df.empty:
            return f"Erreur : Impossible de récupérer les données pour {symbol}"
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = add_tdi_indicators(df)
        
        # Affichage des 3 dernières bougies sous forme de tableau HTML
        last_rows = df.tail(3)[['Close', 'SMA50', 'TDI_Green', 'TDI_Red', 'TDI_Yellow']].to_html(classes='table table-striped')
        
        html_output = f"""
        <h2>Résultats du calcul TDI pour : {symbol.upper()}</h2>
        <p>Voici les dernières valeurs calculées par le bot (à comparer avec ton TradingView) :</p>
        {last_rows}
        <br><a href="/">Retour à l'accueil</a>
        """
        return html_output
    except Exception as e:
        return f"Erreur lors du calcul : {str(e)}"

if __name__ == '__main__':
    t = threading.Thread(target=run_bot_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
