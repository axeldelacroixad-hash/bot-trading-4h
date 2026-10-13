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

# Liste nettoyée des 26 actifs (sans ^SX8P)
ASSETS = {
    # --- Forex & Actifs de base ---
    "EURUSD=X": {"name": "EUR/USD", "country": "Zone Euro / États-Unis", "sector": "Forex (Devises)", "tv": "FX:EURUSD"},
    "GBPUSD=X": {"name": "GBP/USD", "country": "Royaume-Uni / États-Unis", "sector": "Forex (Devises)", "tv": "FX:GBPUSD"},
    "USDJPY=X": {"name": "USD/JPY", "country": "États-Unis / Japon", "sector": "Forex (Devises)", "tv": "FX:USDJPY"},
    "AUDUSD=X": {"name": "AUD/USD", "country": "Australie / États-Unis", "sector": "Forex (Devises)", "tv": "FX:AUDUSD"},
    "USDCAD=X": {"name": "USD/CAD", "country": "États-Unis / Canada", "sector": "Forex (Devises)", "tv": "FX:USDCAD"},
    "EURJPY=X": {"name": "EUR/JPY", "country": "Zone Euro / Japon", "sector": "Forex (Devises)", "tv": "FX:EURJPY"},
    "GBPJPY=X": {"name": "GBP/JPY", "country": "Royaume-Uni / Japon", "sector": "Forex (Devises)", "tv": "FX:GBPJPY"},
    "GLD": {"name": "Or (ETF Gold)", "country": "Mondial", "sector": "Matières Premières (Metaux)", "tv": "AMEX:GLD"},
    "USO": {"name": "Pétrole (ETF USO)", "country": "États-Unis / Mondial", "sector": "Matières Premières (Énergie)", "tv": "AMEX:USO"},
    "BTC-USD": {"name": "Bitcoin", "country": "Mondial", "sector": "Cryptomonnaie", "tv": "BINANCE:BTCUSDT"},
    "ETH-USD": {"name": "Ethereum", "country": "Mondial", "sector": "Cryptomonnaie", "tv": "BINANCE:ETHUSDT"},
    
    # --- Indices boursiers ---
    "^FCHI": {"name": "CAC 40", "country": "France", "sector": "Indices boursiers", "tv": "EURONEXT:PX1"},
    "^GDAXI": {"name": "DAX 40", "country": "Allemagne", "sector": "Indices boursiers", "tv": "XAYR:GER40"},
    "^FTSE": {"name": "FTSE 100", "country": "Royaume-Uni", "sector": "Indices boursiers", "tv": "TVC:UKX"},
    "^SPX": {"name": "S&P 500", "country": "États-Unis", "sector": "Indices boursiers", "tv": "SP:SPX"},
    "^NDX": {"name": "Nasdaq 100", "country": "États-Unis", "sector": "Indices boursiers", "tv": "NASDAQ:NDX"},
    "^N225": {"name": "Nikkei 225", "country": "Japon", "sector": "Indices boursiers", "tv": "TVC:NI225"},
    "^DJI": {"name": "Dow Jones Industrial", "country": "États-Unis", "sector": "Indices boursiers", "tv": "DJ:DJI"},
    "^RUT": {"name": "Russell 2000", "country": "États-Unis", "sector": "Indices boursiers", "tv": "TVC:RUT"},
    "^STOXX50E": {"name": "Euro Stoxx 50", "country": "Zone Euro", "sector": "Indices boursiers", "tv": "STOXX:SX5E"},
    "^AXJO": {"name": "S&P/ASX 200", "country": "Australie", "sector": "Indices boursiers", "tv": "ASX:XJO"},
    "^HSI": {"name": "Hang Seng Index", "country": "Hong Kong / Asie", "sector": "Indices boursiers", "tv": "HSI:HSI"},

    # --- Secteurs Technologiques ---
    "^TWII": {"name": "Taiwan Weighted", "country": "Taïwan", "sector": "Technologie & Semi-conducteurs", "tv": "TWSE:TAIEX"},
    "^KS11": {"name": "KOSPI", "country": "Corée du Sud", "sector": "Technologie & Électronique", "tv": "KRX:KOSPI"},
    "^SOX": {"name": "Philadelphia Semiconductor", "country": "États-Unis", "sector": "Technologie (Semi-conducteurs)", "tv": "NASDAQ:SOX"},
    "XLK": {"name": "Technology Select Sector", "country": "États-Unis", "sector": "Technologie (Software/Hardware)", "tv": "AMEX:XLK"}
}

def send_telegram_message(message, reply_markup=None):
    if not TOKEN or not CHAT_ID:
        print("Erreur : Token ou Chat ID Telegram manquant.")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Erreur d'envoi Telegram : {e}")

def add_tdi_indicators(df):
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.ewm(alpha=1/13, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/13, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    df['TDI_Green'] = rsi.rolling(window=2).mean()
    df['TDI_Red'] = rsi.rolling(window=7).mean()
    df['TDI_Yellow'] = rsi.rolling(window=34).mean()
    df['SMA50'] = df['Close'].rolling(window=50).mean()
    
    return df

def scan_markets():
    print("--- DÉBUT DU SCAN DES MARCHÉS (4H) ---")
    opportunities = []
    now_str = datetime.now(PARIS_TZ).strftime("%d/%m/%Y-%H:%M")
    
    for symbol, info in ASSETS.items():
        try:
            df = yf.download(symbol, period="60d", interval="4h", progress=False)
            time.sleep(1.5)
            
            if df.empty or len(df) < 50:
                print(f"Pas assez de données ou échec pour {symbol}")
                continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            df = add_tdi_indicators(df)
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            price = float(last['Close'])
            
            recent_low = df['Low'].iloc[-5:].min()
            recent_high = df['High'].iloc[-5:].max()

            # Bounding box / boutons Telegram pour TradingView
            tv_symbol = info.get("tv", symbol)
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📊 Ouvrir sur TradingView", "url": f"https://www.tradingview.com/chart/?symbol={tv_symbol}"}
                    ]
                ]
            }

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
                )
                opportunities.append((msg, keyboard))

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
                )
                opportunities.append((msg, keyboard))
                
        except Exception as e:
            print(f"Erreur sur {symbol}: {e}")
            
    if opportunities:
        for alert_msg, reply_markup in opportunities:
            send_telegram_message(alert_msg, reply_markup=reply_markup)
            time.sleep(1)
    else:
        send_telegram_message(f"⚪ *{now_str}* | Scan 4H terminé : Aucun signal valide sur les 26 actifs.")
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
        
        last_rows = df.tail(3)[['Close', 'SMA50', 'TDI_Green', 'TDI_Red', 'TDI_Yellow']].to_html(classes='table table-striped')
        
        html_output = f"""
        <h2>Résultats du calcul TDI pour : {symbol.upper()}</h2>
        <p>Voici les dernières valeurs calculées par le bot :</p>
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
