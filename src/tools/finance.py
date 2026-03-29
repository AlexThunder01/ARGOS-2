"""Finance and cryptocurrency price tools."""
import requests
from .helpers import _get_arg


def crypto_price_tool(coin_id):
    coin_id = _get_arg(coin_id, ["coin", "id", "name"])
    if not coin_id: return "Error: Please specify a coin identifier."
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id.lower()}&vs_currencies=eur"
        r = requests.get(url, timeout=5)
        val = r.json().get(coin_id.lower(), {}).get('eur')
        return f"€{val:,.2f}" if val else "Coin not found."
    except Exception as e: return f"API Error: {e}"

def finance_price_tool(asset):
    asset_name = _get_arg(asset, ["asset", "symbol", "name", "ticker"])
    if not asset_name: return "Error: Please specify an asset (e.g., 'gold', 'AAPL')."
    
    common_symbols = {
        "oro": "GC=F", "gold": "GC=F",
        "argento": "SI=F", "silver": "SI=F",
        "platino": "PL=F", "platinum": "PL=F",
        "petrolio": "CL=F", "oil": "CL=F",
        "gas": "NG=F",
        "sp500": "^GSPC", "s&p500": "^GSPC",
        "nasdaq": "^IXIC", "dow": "^DJI"
    }
    
    clean_asset = asset_name.lower().strip().replace(' in euro', '').replace('_euro','').replace(' euro', '')
    ticker = common_symbols.get(clean_asset, asset_name.upper())
    
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        if hasattr(info, 'last_price') and info.last_price is not None:
            price = info.last_price
            currency = t.info.get('currency', 'USD') if hasattr(t, 'info') else 'USD'
            
            unit_str = ""
            if "oro" in clean_asset or "gold" in clean_asset or "argento" in clean_asset or "silver" in clean_asset:
                unit_str = " per troy ounce (oz)"
                
            output = f"{asset_name.capitalize()} (Ticker: {ticker}): {price:,.2f} {currency}{unit_str}"
            
            if currency == 'USD':
                try:
                    eur_usd = yf.Ticker("EURUSD=X").fast_info.last_price
                    if eur_usd:
                        price_eur = price / eur_usd
                        output += f" (Equivalente calcolato: {price_eur:,.2f} EUR{unit_str})"
                        if unit_str:
                            price_gram_eur = price_eur / 31.1034768
                            output += f" -> Circa {price_gram_eur:,.2f} EUR al grammo"
                except Exception:
                    pass
            
            return output
        
        return f"Price not found for '{ticker}'. Please verify the asset name or ticker symbol."
    except Exception as e:
        return f"Finance API Error: {e}"
