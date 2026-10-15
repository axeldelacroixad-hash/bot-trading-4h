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
RISK_AMOUNT = CAPITAL * RISK_PCT  # 100 € de risque
RISQUE_DU_TRADE_TP1 = 2  # Ratio pour le TP 1 (50%)
RISQUE_DU_TRADE_TP2 = 4  # Ratio pour le TP 2 (50% restant)

PARIS_TZ = pytz.timezone('Europe/Paris')

# Liste nettoyée des 26 actifs
ASSETS = {
    # --- Forex & Actifs de base ---
    "EURUSD=X": {"name": "EUR/USD", "country": "Zone Euro / États-Unis", "sector": "Forex (Devises)", "tv": "FX:EURUSD", "currency": "USD"},
    "GBPUSD=X": {"name": "GBP/USD", "country": "Royaume-Uni / États-Unis", "sector": "Forex (Devises)", "tv": "FX:GBPUSD", "currency": "USD"},
    "USDJPY=X": {"name": "USD/JPY", "country": "États-Unis / Japon", "sector": "Forex (Devises)", "tv": "FX:USDJPY", "currency": "JPY"},
    "AUDUSD=X": {"name": "AUD/USD", "country": "Australie / États-Unis", "sector": "Forex (Devises)", "tv": "FX:AUDUSD", "currency": "USD"},
    "USDCAD=X": {"name": "USD/CAD", "country": "États-Unis / Canada", "sector": "Forex (Devises)", "tv": "FX:USDCAD", "currency": "CAD"},
    "EURJPY=X": {"name": "EUR/JPY", "country": "Zone Euro / Japon", "sector": "Forex (Devises)", "tv": "FX:EURJPY", "currency": "JPY"},
    "GBPJPY=X": {"name": "GBP/JPY", "country": "Royaume-Uni / Japon", "sector": "Forex (Devises)", "tv": "FX:GBPJPY", "currency": "JPY"},
    "GLD": {"name": "Or (ETF Gold)", "country": "Mondial", "sector": "Matières Premières (Metaux)", "tv": "AMEX:GLD", "currency": "USD"},
    "USO": {"name": "Pétrole (ETF USO)", "country": "États-Unis / Mondial", "sector": "Matières Premières (Énergie)", "tv": "AMEX:USO", "currency": "USD"},
    "BTC-USD": {"name": "Bitcoin", "country": "Mondial", "sector": "Cryptomonnaie", "tv": "BINANCE:BTCUSDT", "currency": "USD"},
    "ETH-USD": {"name": "Ethereum", "country": "Mondial", "sector": "Cryptomonnaie", "tv": "BINANCE:ETHUSDT", "currency": "USD"},
    
    # --- Indices boursiers ---
    "^FCHI": {"name": "CAC 40", "country": "France", "sector": "Indices boursiers", "tv": "EURONEXT:PX1", "currency": "EUR"},
    "^GDAXI": {"name": "DAX 40", "country": "Allemagne", "sector": "Indices boursiers", "tv": "XAYR:GER40", "currency": "EUR"},
    "^FTSE": {"name": "FTSE 100", "country": "Royaume-Uni", "sector": "Indices boursiers", "tv": "TVC:UKX", "currency": "GBP"},
    "^SPX": {"name": "S&P 500", "country": "États-Unis", "sector": "Indices boursiers", "tv": "SP:SPX", "currency": "USD"},
    "^NDX": {"name": "Nasdaq 100", "country": "États-Unis", "sector": "Indices boursiers", "tv": "NASDAQ:NDX", "currency": "USD"},
    "^N225": {"name": "Nikkei 225", "country": "Japon", "sector": "Indices boursiers", "tv": "TVC:NI225", "currency": "JPY"},
    "^DJI": {"name": "Dow Jones Industrial", "country": "États-Unis", "sector": "Indices boursiers", "tv": "DJ:DJI", "currency": "USD"},
    "^RUT": {"name": "Russell 2000", "country": "États-Unis", "sector": "Indices boursiers", "tv": "TVC:RUT", "currency": "USD"},
    "^STOXX50E": {"name": "Euro Stoxx 50", "country": "Zone Euro", "sector": "Indices boursiers", "tv": "STOXX:SX5E", "currency": "EUR"},
    "^AXJO": {"name": "S&P/ASX 200", "country": "Australie", "sector": "Indices boursiers", "tv": "ASX:XJO", "currency": "AUD"},
    "^HSI": {"name": "Hang Seng Index", "country": "Hong Kong / Asie", "sector": "Indices boursiers", "tv": "HSI:HSI", "currency": "HKD"},

    # --- Secteurs Technologiques ---
    "^TWII": {"name": "Taiwan Weighted", "country": "Taïwan", "sector": "Technologie & Semi-conducteurs", "tv": "TWSE:TAIEX", "currency": "TWD"},
    "^KS11": {"name": "KOSPI", "country": "Corée du Sud", "sector": "Technologie & Électronique", "tv": "KRX:KOSPI", "currency": "KRW"},
    "^SOX": {"name": "Philadelphia Semiconductor", "country": "États-Unis", "sector": "Technologie (Semi-conducteurs)", "tv": "NASDAQ:SOX", "currency": "USD"},
    "XLK": {"name": "Technology Select Sector", "country": "États-Unis", "sector": "Technologie (Software/Hardware)", "tv": "AMEX:XLK", "currency": "USD"}
}

def get_eur_conversion_rate(asset_currency):
    if asset_currency == "EUR":
        return 1.0
    try:
        pair = f"EUR{asset_currency}=X"
        df_curr = yf.download(pair, period="5d", progress=False)
        if not df_curr.empty:
            if isinstance(df_curr.columns, pd.MultiIndex):
                df_curr.columns = df_curr.columns.get_level_values(0)
            rate_eur_to_target = float(df_curr['Close'].iloc[-1])
            return 1.0 / rate_eur_to_target
    except Exception:
        pass
    
    fallbacks = {"USD": 1.08, "JPY": 165.0, "GBP": 0.85, "CAD": 1.48, "AUD": 1.65, "HKD": 8.4, "TWD": 35.0, "KRW": 1450.0}
    return 1.0 / fallbacks.get(asset_currency, 1.0)

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

            asset_curr = info.get("currency", "USD")
            eur_per_unit_currency = get_eur_conversion_rate(asset_curr)

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
                
                nb_unite = RISK_AMOUNT / (sl_distance * eur_per_unit_currency)
                total_trade_eur = nb_unite * price * eur_per_unit_currency
                
                if total_trade_eur > CAPITAL:
                    total_trade_eur = CAPITAL
                
                take_profit_1 = price + (sl_distance * RISQUE_DU_TRADE_TP1)
                take_profit_2 = price + (sl_distance * RISQUE_DU_TRADE_TP2)
                
                msg = (
                    f"🟢 *{now_str}* | *{symbol}* | **{info['name']}**\n"
                    f"🌍 **Région :** {info['country']}\n"
                    f"🏢 **Secteur :** {info['sector']}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"• Signal : **LONG (Achat)**\n"
                    f"• Prix actuel : {price:.3f}\n"
                    f"• Stop Loss : {sl_price:.3f}\n"
                    f"• Take Profit 1 (50%) : {take_profit_1:.3f}\n"
                    f"• Take Profit 2 (50%) : {take_profit_2:.3f}\n"
                    f"• Nb d'unités total : *{nb_unite:.3f}*\n"
                    f"• Risque : 100.00 € (1%)\n"
                    f"• Montant Total : *{total_trade_eur:.2f} €*\n"
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
                
                nb_unite = RISK_AMOUNT / (sl_distance * eur_per_unit_currency)
                total_trade_eur = nb_unite * price * eur_per_unit_currency
                
                if total_trade_eur > CAPITAL:
                    total_trade_eur = CAPITAL
                
                take_profit_1 = price - (sl_distance * RISQUE_DU_TRADE_TP1)
                take_profit_2 = price - (sl_distance * RISQUE_DU_TRADE_TP2)
                
                msg = (
                    f"🔴 *{now_str}* | *{symbol}* | **{info['name']}**\n"
                    f"🌍 **Région :** {info['country']}\n"
                    f"🏢 **Secteur :** {info['sector']}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"• Signal : **SHORT (Vente)**\n"
                    f"• Prix actuel : {price:.3f}\n"
                    f"• Stop Loss : {sl_price:.3f}\n"
                    f"• Take Profit 1 (50%) : {take_profit_1:.3f}\n"
                    f"• Take Profit 2 (50%) : {take_profit_2:.3f}\n"
                    f"• Nb d'unités total : *{nb_unite:.3f}*\n"
                    f"• Risque : 100.00 € (1%)\n"
                    f"• Montant Total : *{total_trade_eur:.2f} €*\n"
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
            
        now = datetime.now(PARIS_TZ)
        current_hour = now.hour
        target_hours = [0, 4, 8, 12, 16, 20]
        
        next_hour = None
        for h in target_hours:
            if h > current_hour or (h == current_hour and now.minute < 2):
                next_hour = h
                break
                
        if next_hour is None:
            next_target = now.replace(hour=0, minute=2, second=0, microsecond=0) + pd.Timedelta(days=1)
        else:
            next_target = now.replace(hour=next_hour, minute=2, second=0, microsecond=0)
            
        if next_target <= now:
            next_target = now + pd.Timedelta(hours=4)
            
        sleep_seconds = (next_target - now).total_seconds()
        print(f"Prochain scan prévu à : {next_target.strftime('%H:%M:%S')} (dans {int(sleep_seconds/60)} minutes)")
        time.sleep(sleep_seconds)

@app.route('/')
def home():
    return "Le bot de trading swing 4H est en ligne, synchronisé et actif avec TP 1 & TP 2 !"

@app.route('/test-scan')
def test_scan():
    scan_markets()
    return "Scan manuel exécuté avec succès !"

if __name__ == '__main__':
    t = threading.Thread(target=run_bot_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
