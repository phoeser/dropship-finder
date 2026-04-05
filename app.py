import os
import json
import random
import hashlib
import requests
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ─── File paths ──────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_DIR, 'data')
PRODUCTS_FILE = os.path.join(DATA_DIR, 'products.json')
REMOVED_FILE  = os.path.join(DATA_DIR, 'removed_products.json')
CONFIG_FILE   = os.path.join(DATA_DIR, 'shopify_config.json')

# ─── Helpers ─────────────────────────────────────────────────────────────────
def load_json(filepath, default):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def normalize_store_url(url: str) -> str:
    url = url.strip().rstrip('/')
    if url and not url.startswith('http'):
        url = 'https://' + url
    return url

# ─── Demand Score Algorithm ───────────────────────────────────────────────────
CATEGORY_SCORES = {
    'Elektronik':    72,
    'Smart Home':    68,
    'Gaming':        66,
    'Gesundheit':    63,
    'Fitness':       61,
    'Beauty':        60,
    'Auto-Zubehör':  57,
    'Küche':         54,
    'Haustier':      52,
    'Mode':          55,
    'Büro':          49,
}

def compute_demand_score(product):
    """
    Score 1-100 basierend auf Kategorie-Trend, Preispunkt und Marge.
    Produziert realistische Streuung von ~35-95 für typische DropShipping-Produkte.
    """
    buy  = product.get('buy_price', 0) or 0
    sell = product.get('sell_price', 0) or 0
    margin_pct = (sell - buy) / buy * 100 if buy > 0 else 0

    base = CATEGORY_SCORES.get(product.get('category', ''), 50)

    # Marge-Bonus: nur bei deutlich höherer Marge relevant
    if margin_pct >= 500:   base += 6
    elif margin_pct >= 400: base += 4
    elif margin_pct >= 300: base += 2
    elif margin_pct < 100:  base -= 6
    elif margin_pct < 150:  base -= 2

    # Preis-Sweet-Spot €18–55
    if 18 <= sell <= 55:    base += 5
    elif 12 <= sell < 18:   base += 2
    elif sell > 70:         base -= 3

    # Breite, konsistente Streuung per Produkt-ID (+/- 18)
    pid = product.get('id', 0)
    if isinstance(pid, str):
        pid = abs(int(hashlib.md5(pid.encode()).hexdigest(), 16)) % 1000
    # Zwei Terme für ungleichmäßigere Verteilung
    v1 = (pid * 17 + 5)  % 23 - 11
    v2 = (pid * 7  + 13) % 15 - 7
    variance = v1 + v2  # range: -18 to +18

    return min(97, max(18, base + variance))

# ─── AliExpress Simulations-Katalog ────────────────────────────────────────
ALIEXPRESS_CATALOG = [
    {"name": "Mini Wireless Earbuds Pro", "category": "Elektronik", "buy": 8.90, "sell": 39.99,
     "image": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400&h=280&fit=crop",
     "desc": "True Wireless Earbuds mit ANC, 30h Laufzeit, IPX5, Bluetooth 5.3",
     "keywords": ["kopfhörer","earbuds","wireless","audio","musik","bluetooth","headphone"]},
    {"name": "USB-C Multiport Hub 7-in-1", "category": "Elektronik", "buy": 11.50, "sell": 49.99,
     "image": "https://images.unsplash.com/photo-1625842268584-8f3296236761?w=400&h=280&fit=crop",
     "desc": "7-in-1 Hub: 4K HDMI, 3x USB-A, USB-C PD 100W, SD/MicroSD",
     "keywords": ["hub","usb","laptop","macbook","adapter","kabel","anschluss"]},
    {"name": "Pocket Mini Projektor LED", "category": "Elektronik", "buy": 18.50, "sell": 79.99,
     "image": "https://images.unsplash.com/photo-1478720568477-152d9b164e26?w=400&h=280&fit=crop",
     "desc": "Kompakter DLP-Projektor, 200 Lumen, HDMI+USB, eingebauter Akku 2h",
     "keywords": ["projektor","beamer","kino","film","video","heimkino","projector"]},
    {"name": "Smartwatch Fitness Ultra", "category": "Elektronik", "buy": 14.20, "sell": 64.99,
     "image": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=400&h=280&fit=crop",
     "desc": "AMOLED Display, GPS, SpO2, 7 Tage Akku, 15 Sportmodi, IP68",
     "keywords": ["smartwatch","uhr","fitness","tracker","sport","wearable","watch"]},
    {"name": "RGB Gaming Mauspad XXL", "category": "Gaming", "buy": 5.80, "sell": 29.99,
     "image": "https://images.unsplash.com/photo-1612287230202-1ff1d85d1bdf?w=400&h=280&fit=crop",
     "desc": "900x400mm Extended Pad, USB RGB Beleuchtung, Anti-Rutsch, wasserfest",
     "keywords": ["gaming","maus","pad","desk","rgb","gamer","mousepad"]},
    {"name": "Mechanische Gaming-Tastatur TKL", "category": "Gaming", "buy": 19.90, "sell": 79.99,
     "image": "https://images.unsplash.com/photo-1541140532154-b024d705b90a?w=400&h=280&fit=crop",
     "desc": "TKL Layout, Hot-Swap Switches, RGB pro Taste, Aluminium-Platte",
     "keywords": ["tastatur","keyboard","gaming","mechanisch","rgb","gamer","pc"]},
    {"name": "LED Strip Lights 10m RGBIC", "category": "Smart Home", "buy": 6.20, "sell": 29.99,
     "image": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400&h=280&fit=crop",
     "desc": "RGBIC Multicolor gleichzeitig, App-Steuerung, Alexa/Google, Musiksync",
     "keywords": ["led","strip","lights","beleuchtung","rgb","smart","home","zimmer"]},
    {"name": "WLAN Steckdose 4er Set", "category": "Smart Home", "buy": 9.50, "sell": 39.99,
     "image": "https://images.unsplash.com/photo-1558002038-bb4237bb8f9a?w=400&h=280&fit=crop",
     "desc": "Smart Plug mit Energiemessung, Timer, Alexa/Google, kein Hub nötig",
     "keywords": ["steckdose","smart","wlan","plug","home","alexa","google"]},
    {"name": "Galaxis Sternenhimmel Projektor", "category": "Smart Home", "buy": 12.80, "sell": 54.99,
     "image": "https://images.unsplash.com/photo-1534796636912-3b95b3ab5986?w=400&h=280&fit=crop",
     "desc": "360° Sternenhimmel + Nebula, App-Steuerung, RGB, BT-Lautsprecher",
     "keywords": ["projektor","sterne","galaxie","nacht","lampe","schlafzimmer","ambient"]},
    {"name": "Elektrischer Nackenmassager EMS", "category": "Gesundheit", "buy": 13.50, "sell": 59.99,
     "image": "https://images.unsplash.com/photo-1544367567-0f2fcb009e0b?w=400&h=280&fit=crop",
     "desc": "EMS + Wärme, 15 Intensitäten, 6 Modi, Schulter & Nacken",
     "keywords": ["massage","nacken","schulter","ems","entspannung","gesundheit","rücken"]},
    {"name": "LED Face Mask Beauty", "category": "Beauty", "buy": 11.20, "sell": 49.99,
     "image": "https://images.unsplash.com/photo-1616394584738-fc6e612e71b9?w=400&h=280&fit=crop",
     "desc": "7 Farben LED-Therapie, Anti-Aging, Akne-Behandlung, USB-C",
     "keywords": ["maske","led","gesicht","beauty","haut","pflege","face","mask"]},
    {"name": "Elektrisches Nagelfräser-Set Pro", "category": "Beauty", "buy": 9.80, "sell": 44.99,
     "image": "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=400&h=280&fit=crop",
     "desc": "11-teilig, 6 Stufen, leise, für Maniküre + Pediküre",
     "keywords": ["nagel","fräser","maniküre","pediküre","beauty","nail","gel"]},
    {"name": "Haltungskorrektur Rückenstütze", "category": "Gesundheit", "buy": 6.20, "sell": 32.99,
     "image": "https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?w=400&h=280&fit=crop",
     "desc": "Ergonomisch, atmungsaktiv, einstellbar, für Büro und Alltag",
     "keywords": ["haltung","rücken","korrektur","posture","büro","schmerzen","ergonomie"]},
    {"name": "Tragbarer USB-Smoothie-Mixer", "category": "Küche", "buy": 8.20, "sell": 36.99,
     "image": "https://images.unsplash.com/photo-1546549032-9571cd6b27df?w=400&h=280&fit=crop",
     "desc": "400ml, USB-C, 6 Klingen, BPA-frei, für Protein-Shakes & Smoothies",
     "keywords": ["mixer","smoothie","küche","usb","portable","blender","protein","shake"]},
    {"name": "Magnetischer KFZ-Handyhalter", "category": "Auto-Zubehör", "buy": 3.20, "sell": 17.99,
     "image": "https://images.unsplash.com/photo-1601784551446-20c9e07cdbdb?w=400&h=280&fit=crop",
     "desc": "Neodym-Magnet, 360° drehbar, alle Lüftungsschlitze, kabellos ladend kompatibel",
     "keywords": ["auto","halter","handy","kfz","magnet","phone","mount","car"]},
    {"name": "Dashcam 4K WiFi Dual", "category": "Auto-Zubehör", "buy": 22.50, "sell": 89.99,
     "image": "https://images.unsplash.com/photo-1449824913935-59a10b8d2000?w=400&h=280&fit=crop",
     "desc": "4K Front + 1080p Rück, WiFi App, Nachtsicht, Parkwächter, GPS",
     "keywords": ["dashcam","kamera","auto","4k","fahrt","unfall","sicherheit","car","cam"]},
    {"name": "Selbstreinigender Haarbürste Silikon", "category": "Haustier", "buy": 3.50, "sell": 18.99,
     "image": "https://images.unsplash.com/photo-1587300003388-59208cc962cb?w=400&h=280&fit=crop",
     "desc": "Tierhaar-Entferner ohne Klebeband, für Sofa, Textilien & Auto",
     "keywords": ["haustier","hund","katze","tier","haare","fell","lint","pet"]},
    {"name": "Magnetische Geldbörse Slim RFID", "category": "Mode", "buy": 4.50, "sell": 24.99,
     "image": "https://images.unsplash.com/photo-1627123424574-724758594e93?w=400&h=280&fit=crop",
     "desc": "Aluminium RFID-Schutz, 8 Karten, magnetischer Clip, Leder-Optik",
     "keywords": ["geldbörse","wallet","rfid","slim","karte","mode","portemonnaie"]},
    {"name": "LED Schminkspiegel 10x", "category": "Beauty", "buy": 14.80, "sell": 64.99,
     "image": "https://images.unsplash.com/photo-1588854337115-1c67d9247e4d?w=400&h=280&fit=crop",
     "desc": "10x Vergrößerung, 3 Lichtfarben, Touch-Dimmer, USB-C, 360° drehbar",
     "keywords": ["spiegel","make-up","schminke","beauty","led","licht","mirror"]},
    {"name": "Laptop-Ständer Aluminium faltbar", "category": "Büro", "buy": 8.90, "sell": 39.99,
     "image": "https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?w=400&h=280&fit=crop",
     "desc": "6 Höhen, 10-17 Zoll, Wärmeabfuhr, faltbar, 1.2kg tragbar",
     "keywords": ["laptop","ständer","büro","stand","ergonomie","notebook","macbook"]},
    {"name": "Wireless Qi Ladepad 3-in-1", "category": "Elektronik", "buy": 10.20, "sell": 44.99,
     "image": "https://images.unsplash.com/photo-1583394293214-0e35eff999f0?w=400&h=280&fit=crop",
     "desc": "15W Fast Charge, für iPhone + AirPods + Apple Watch, LED-Status",
     "keywords": ["wireless","laden","qi","charger","iphone","apple","watch","airpods","kabellos"]},
]

def simulate_aliexpress_search(query: str):
    """Generiert simulierte AliExpress-Suchergebnisse basierend auf dem Suchbegriff."""
    q = query.lower().strip()
    words = q.split()

    scored = []
    for item in ALIEXPRESS_CATALOG:
        kw_score = sum(
            2 if w in item['keywords'] else
            (1 if any(w in k for k in item['keywords']) else 0)
            for w in words
        )
        if q in item['name'].lower() or q in item['desc'].lower():
            kw_score += 3
        scored.append((kw_score, item))

    scored.sort(key=lambda x: -x[0])

    top  = [item for score, item in scored if score > 0]
    rest = [item for score, item in scored if score == 0]

    rng = random.Random(hashlib.md5(q.encode()).hexdigest())
    rng.shuffle(rest)
    results_raw = (top + rest)[:8]

    results = []
    for item in results_raw:
        factor = 1 + rng.uniform(-0.05, 0.05)
        buy    = round(item['buy'] * factor, 2)
        sell   = round(item['sell'] * factor, 2)
        profit = round(sell - buy, 2)
        margin = round((sell - buy) / buy * 100, 1) if buy else 0
        prod = {
            'id':            f"search-{abs(hash(item['name'] + q)) % 99999}",
            'name':          item['name'],
            'category':      item['category'],
            'description':   item['desc'],
            'buy_price':     buy,
            'sell_price':    sell,
            'profit':        profit,
            'margin_pct':    margin,
            'image':         item['image'],
            'aliexpress_url': f"https://www.aliexpress.com/wholesale?SearchText={'+'.join(item['name'].split())}",
        }
        prod['demand_score'] = compute_demand_score(prod)
        results.append(prod)

    return results

# ─── TikTok Top 5 Trending Gadgets ───────────────────────────────────────────
TIKTOK_TOP5 = [
    {
        "rank": 1,
        "name": "Mini LED Projektor",
        "desc": "Kompakter Taschenkino-Projektor – viraler TikTok-Hit mit Millionen Views. Perfekt für Schlafzimmer-Setups.",
        "image": "https://images.unsplash.com/photo-1478720568477-152d9b164e26?w=300&h=200&fit=crop",
        "trend_tag": "#MiniProjector #TikTokRoom",
        "views": "82M Views",
        "search_url": "https://www.aliexpress.com/wholesale?SearchText=mini+led+projector+portable",
    },
    {
        "rank": 2,
        "name": "LED Face Mask",
        "desc": "7-Farben LED-Gesichtsmaske für Hautpflege – dominiert TikTok Beauty-Feeds und SkinTok.",
        "image": "https://images.unsplash.com/photo-1616394584738-fc6e612e71b9?w=300&h=200&fit=crop",
        "trend_tag": "#SkinTok #LEDMask #GlowUp",
        "views": "67M Views",
        "search_url": "https://www.aliexpress.com/wholesale?SearchText=led+face+mask+7+colors",
    },
    {
        "rank": 3,
        "name": "Galaxy Sternenhimmel-Projektor",
        "desc": "Rotierender Sternenhimmel & Nebula-Projektor. Absoluter Dauerbrenner bei Room-Decor TikToks.",
        "image": "https://images.unsplash.com/photo-1534796636912-3b95b3ab5986?w=300&h=200&fit=crop",
        "trend_tag": "#RoomTok #GalaxyProjector #AmbientLight",
        "views": "54M Views",
        "search_url": "https://www.aliexpress.com/wholesale?SearchText=galaxy+star+projector+night+light",
    },
    {
        "rank": 4,
        "name": "Magnetisches Phone Wallet",
        "desc": "Ultra-slim RFID-Schutz-Geldbörse mit Magnet-Clip – viraler EDC-Gadget-Trend auf TikTok.",
        "image": "https://images.unsplash.com/photo-1627123424574-724758594e93?w=300&h=200&fit=crop",
        "trend_tag": "#EDC #WalletTok #Minimalist",
        "views": "41M Views",
        "search_url": "https://www.aliexpress.com/wholesale?SearchText=magnetic+slim+wallet+rfid",
    },
    {
        "rank": 5,
        "name": "Elektrische Facial Brush",
        "desc": "Ultraschall-Gesichtsreinigungsbürste – fester Platz in SkinTok-Routinen weltweit.",
        "image": "https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?w=300&h=200&fit=crop",
        "trend_tag": "#SkinCare #FacialBrush #BeautyTok",
        "views": "38M Views",
        "search_url": "https://www.aliexpress.com/wholesale?SearchText=electric+facial+cleansing+brush+sonic",
    },
]

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    products = load_json(PRODUCTS_FILE, [])
    removed  = set(load_json(REMOVED_FILE, []))
    active   = [p for p in products if p['id'] not in removed]

    for p in active:
        buy  = p.get('buy_price', 0)
        sell = p.get('sell_price', 0)
        p['profit']       = round(sell - buy, 2)
        p['margin_pct']   = round((sell - buy) / buy * 100, 1) if buy else 0
        p['demand_score'] = compute_demand_score(p)

    config      = load_json(CONFIG_FILE, {})
    has_shopify = bool(config.get('store_url') and config.get('access_token'))
    store_url   = config.get('store_url', '')

    return render_template(
        'index.html',
        products=active,
        has_shopify=has_shopify,
        store_url=store_url,
        removed_count=len(removed),
        total_count=len(products),
        tiktok_top5=TIKTOK_TOP5,
    )


# ── Shopify config ─────────────────────────────────────────────────────────
@app.route('/api/shopify-config', methods=['GET'])
def get_shopify_config():
    config = load_json(CONFIG_FILE, {})
    return jsonify({'store_url': config.get('store_url', ''), 'has_token': bool(config.get('access_token'))})

@app.route('/api/shopify-config', methods=['POST'])
def save_shopify_config():
    data         = request.get_json(force=True)
    store_url    = normalize_store_url(data.get('store_url', ''))
    access_token = data.get('access_token', '').strip()
    if not store_url or not access_token:
        return jsonify({'success': False, 'error': 'Store-URL und Access Token sind erforderlich.'}), 400
    save_json(CONFIG_FILE, {'store_url': store_url, 'access_token': access_token})
    return jsonify({'success': True, 'message': 'Shopify-Konfiguration gespeichert.'})


# ── Remove / restore products ──────────────────────────────────────────────
@app.route('/api/remove-product/<int:product_id>', methods=['POST'])
def remove_product(product_id):
    removed = load_json(REMOVED_FILE, [])
    if product_id not in removed:
        removed.append(product_id)
        save_json(REMOVED_FILE, removed)
    return jsonify({'success': True, 'removed_count': len(removed)})

@app.route('/api/restore-all', methods=['POST'])
def restore_all():
    save_json(REMOVED_FILE, [])
    return jsonify({'success': True})


# ── Shared Shopify helpers ─────────────────────────────────────────────────
def _shopify_import_payload(product):
    return {
        "product": {
            "title":        product['name'],
            "body_html":    f"<p>{product.get('description', '')}</p>",
            "vendor":       "DropShip Finder",
            "product_type": product.get('category', ''),
            "status":       "draft",
            "variants": [{
                "price":                str(product['sell_price']),
                "compare_at_price":     None,
                "inventory_management": None,
                "fulfillment_service":  "manual",
                "requires_shipping":    True,
            }],
            "images": [{"src": product['image']}] if product.get('image') else [],
        }
    }

def _do_shopify_request(payload):
    config       = load_json(CONFIG_FILE, {})
    store_url    = config.get('store_url', '')
    access_token = config.get('access_token', '')
    if not store_url or not access_token:
        return None, 'Shopify nicht konfiguriert. Bitte Store-URL und Access Token eingeben.'
    api_url = f"{store_url}/admin/api/2024-01/products.json"
    headers = {'X-Shopify-Access-Token': access_token, 'Content-Type': 'application/json'}
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
        return resp, None
    except requests.exceptions.ConnectionError:
        return None, 'Verbindung zum Shopify-Store fehlgeschlagen. Bitte Store-URL prüfen.'
    except requests.exceptions.Timeout:
        return None, 'Shopify hat nicht rechtzeitig geantwortet (Timeout).'
    except requests.exceptions.RequestException as exc:
        return None, str(exc)

def _shopify_response_json(resp, product_name='Produkt'):
    if resp.status_code in (200, 201):
        created    = resp.json().get('product', {})
        shopify_id = created.get('id', '?')
        config     = load_json(CONFIG_FILE, {})
        admin_url  = f"{config.get('store_url','')}/admin/products/{shopify_id}"
        return jsonify({'success': True, 'shopify_id': shopify_id, 'admin_url': admin_url,
                        'message': f'"{product_name}" als Entwurf importiert (ID: {shopify_id})'})
    else:
        try:   errors = resp.json().get('errors', resp.text)
        except: errors = resp.text
        return jsonify({'success': False, 'error': str(errors)}), resp.status_code


# ── Shopify import (existing catalog products) ────────────────────────────
@app.route('/api/import-shopify/<int:product_id>', methods=['POST'])
def import_shopify(product_id):
    products = load_json(PRODUCTS_FILE, [])
    product  = next((p for p in products if p['id'] == product_id), None)
    if not product:
        return jsonify({'success': False, 'error': 'Produkt nicht gefunden.'}), 404

    resp, err = _do_shopify_request(_shopify_import_payload(product))
    if err:
        status = 400 if 'konfiguriert' in err else 502
        return jsonify({'success': False, 'error': err}), status
    return _shopify_response_json(resp, product['name'])


# ── AliExpress Search (simulated) ─────────────────────────────────────────
@app.route('/api/search-aliexpress', methods=['POST'])
def search_aliexpress():
    data  = request.get_json(force=True)
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'Suchbegriff fehlt.'}), 400
    results = simulate_aliexpress_search(query)
    return jsonify({'success': True, 'products': results, 'query': query})


# ── Shopify import from search results ────────────────────────────────────
@app.route('/api/import-search-to-shopify', methods=['POST'])
def import_search_to_shopify():
    data    = request.get_json(force=True)
    product = data.get('product')
    if not product:
        return jsonify({'success': False, 'error': 'Kein Produkt angegeben.'}), 400

    resp, err = _do_shopify_request(_shopify_import_payload(product))
    if err:
        status = 400 if 'konfiguriert' in err else 502
        return jsonify({'success': False, 'error': err}), status
    return _shopify_response_json(resp, product.get('name', 'Produkt'))


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
