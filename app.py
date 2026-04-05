from flask import Flask, jsonify, request, render_template_string
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests
import os

app = Flask(__name__)

# Datenbank-Konfiguration (SQLite lokal, PostgreSQL auf Render)
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///dropship.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ── Datenmodell ─────────────────────────────────────────────────────────────────

class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(100))
    category = db.Column(db.String(100))
    trend_score = db.Column(db.Integer, default=0)
    link = db.Column(db.String(1000))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(1000))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── DB initialisieren (auch unter Gunicorn) ──────────────────────────────────────

with app.app_context():
    db.create_all()


# ── In-Memory Cache ──────────────────────────────────────────────────────────────

products_cache = []
last_refresh = None


# ── Datenquellen ─────────────────────────────────────────────────────────────────

def fetch_reddit_products():
    products = []
    subreddits = ['dropship', 'dropshipping', 'Entrepreneur']
    headers = {'User-Agent': 'DropshipFinder/1.0 (research-tool)'}

    for subreddit in subreddits:
        try:
            r = requests.get(
                f'https://www.reddit.com/r/{subreddit}/hot.json?limit=20',
                headers=headers, timeout=10
            )
            data = r.json()
            for post in data['data']['children']:
                p = post['data']
                if p.get('score', 0) > 10 and not p.get('stickied', False):
                    thumbnail = p.get('thumbnail', '')
                    products.append({
                        'id': f"reddit_{p['id']}",
                        'name': p['title'],
                        'source': f"Reddit r/{subreddit}",
                        'category': 'Community',
                        'trend_score': p['score'],
                        'link': f"https://reddit.com{p['permalink']}",
                        'description': (p.get('selftext', '') or 'Kein Text verfügbar')[:250],
                        'image_url': thumbnail if thumbnail.startswith('http') else None,
                        'fetched_at': datetime.utcnow().isoformat()
                    })
        except Exception as e:
            print(f"[Reddit] Fehler bei r/{subreddit}: {e}")

    return products


def fetch_google_trends_products():
    products = []
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='de-DE', tz=60, timeout=(10, 25))
        keywords = ['dropshipping produkt', 'tiktok trending produkt', 'viral produkt kaufen']

        for kw in keywords:
            try:
                pytrends.build_payload([kw], timeframe='now 7-d', geo='DE')
                related = pytrends.related_queries()
                if related and kw in related:
                    rising = related[kw].get('rising')
                    if rising is not None and not rising.empty:
                        for _, row in rising.head(5).iterrows():
                            query = row['query']
                            value = row['value']
                            score = 999 if value == 'Breakout' else int(value)
                            products.append({
                                'id': f"trends_{query.replace(' ', '_').lower()}",
                                'name': query.title(),
                                'source': 'Google Trends',
                                'category': 'Trending',
                                'trend_score': score,
                                'link': f"https://trends.google.de/trends/explore?q={query.replace(' ', '+')}&geo=DE",
                                'description': f"Wachstumsrate: {value}{'%' if value != 'Breakout' else ' (Breakout!)'}",
                                'image_url': None,
                                'fetched_at': datetime.utcnow().isoformat()
                            })
            except Exception as e:
                print(f"[Google Trends] Fehler bei '{kw}': {e}")

    except Exception as e:
        print(f"[Google Trends] Fehler: {e}")

    return products


def fetch_tiktok_products():
    products = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'de-DE,de;q=0.9',
            'Referer': 'https://ads.tiktok.com/creative_center/product-sale/pc/en',
        }
        url = 'https://ads.tiktok.com/creative_center/api/trending/product/list/?page=1&limit=20&period=7&country_code=DE'
        r = requests.get(url, headers=headers, timeout=12)

        if r.status_code == 200:
            data = r.json()
            for item in data.get('data', {}).get('list', []):
                products.append({
                    'id': f"tiktok_{item.get('id', item.get('title', '')[:20])}",
                    'name': item.get('title', 'Unbekannt'),
                    'source': 'TikTok Creative Center',
                    'category': item.get('first_level_category_name', 'TikTok'),
                    'trend_score': int(item.get('popularity', 0)),
                    'link': f"https://www.tiktok.com/search?q={item.get('title', '').replace(' ', '+')}",
                    'description': f"Kategorie: {item.get('first_level_category_name', '–')}",
                    'image_url': item.get('cover', None),
                    'fetched_at': datetime.utcnow().isoformat()
                })
        else:
            print(f"[TikTok] HTTP {r.status_code}")
    except Exception as e:
        print(f"[TikTok] Fehler: {e}")

    return products


def fetch_aliexpress_products():
    """Kuratierte Liste spezifischer, trendiger Dropshipping-Produkte mit echten Beispiel-Links."""
    now = datetime.utcnow().isoformat()
    return [
        {
            'id': 'ali_bp_smartwatch',
            'name': 'Blutdruck-Smartwatch mit EKG & SpO2',
            'source': 'AliExpress',
            'category': 'Gesundheit',
            'trend_score': 980,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=blood+pressure+smartwatch+ECG+spo2&SortType=total_tranpro_desc',
            'description': 'Misst Blutdruck, EKG und Sauerstoffsaettigung kontinuierlich. Zielgruppe 40+. EK ca. 20 EUR, VK 60-100 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_ems_abs',
            'name': 'EMS Bauchmuskel-Guertel (6 Modi, kabellos)',
            'source': 'AliExpress',
            'category': 'Fitness',
            'trend_score': 850,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=EMS+abs+trainer+muscle+stimulator+belt&SortType=total_tranpro_desc',
            'description': 'Elektrischer Muskelstimulator fuer Bauch & Koerper. Viral auf TikTok. EK ca. 5-10 EUR, VK 25-45 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_massage_gun_mini',
            'name': 'Mini-Massagepistole faltbar (6 Aufsaetze, USB-C)',
            'source': 'AliExpress',
            'category': 'Wellness',
            'trend_score': 920,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=mini+foldable+massage+gun+fascia+USB-C&SortType=total_tranpro_desc',
            'description': 'Kompakte Faszienpistole zum Klappen, USB-C-Ladung, 6 Aufaetze. EK ca. 15-25 EUR, VK 50-80 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_led_face_mask',
            'name': 'LED-Lichttherapiemaske (7 Farben, Anti-Akne)',
            'source': 'AliExpress',
            'category': 'Beauty',
            'trend_score': 870,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=LED+light+therapy+face+mask+7+colors+acne&SortType=total_tranpro_desc',
            'description': 'Professionelle LED-Maske gegen Akne & Falten. Stark auf TikTok. EK ca. 10-20 EUR, VK 40-70 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_smart_ring',
            'name': 'Smart Ring Gesundheitsmonitor (Schlaf, HRV, SpO2)',
            'source': 'AliExpress',
            'category': 'Gesundheit',
            'trend_score': 999,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=smart+ring+health+monitor+sleep+tracker+HRV&SortType=total_tranpro_desc',
            'description': 'Schlanker Ring trackt Schlaf, HRV, SpO2 & Schritte ohne Display. Breakout-Trend 2025. EK ca. 30 EUR, VK 90-130 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_garlic_chopper',
            'name': 'Elektrischer Knoblauch- & Gemuesehacker (USB)',
            'source': 'AliExpress',
            'category': 'Kueche',
            'trend_score': 780,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=electric+garlic+chopper+vegetable+USB+rechargeable&SortType=total_tranpro_desc',
            'description': 'USB-aufladbarer Mini-Zerkleinerer fuer Knoblauch, Zwiebeln & Chili. EK ca. 4-8 EUR, VK 20-35 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_mini_air_fryer',
            'name': 'Mini-Heissluftfritteuse 2 Liter (kompakt, fuer 1-2 Personen)',
            'source': 'AliExpress',
            'category': 'Kueche',
            'trend_score': 890,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=mini+air+fryer+2L+compact+electric+small&SortType=total_tranpro_desc',
            'description': 'Kompakte Luftfritteuse fuer Singles & Studenten. Sehr gefragt. EK ca. 20-35 EUR, VK 60-90 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_beeswax_wrap',
            'name': 'Bienenwachs-Frischhaltefolie nachhaltig (3er-Set)',
            'source': 'AliExpress',
            'category': 'Kueche',
            'trend_score': 680,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=beeswax+food+wrap+reusable+organic+eco&SortType=total_tranpro_desc',
            'description': 'Nachhaltige Alternative zu Plastikfolie. Ideal fuer Oeko-Zielgruppe. EK ca. 3-6 EUR, VK 15-25 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_drawer_organizer',
            'name': 'Ausziehbarer Kuechenschubladenteiler (kein Kleben)',
            'source': 'AliExpress',
            'category': 'Haushalt',
            'trend_score': 720,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=expandable+drawer+divider+organizer+kitchen+no+glue&SortType=total_tranpro_desc',
            'description': 'Flexibler Schubladenteiler ohne Kleben. Trendet auf Pinterest & TikTok. EK ca. 2-5 EUR, VK 12-20 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_fridge_organizer',
            'name': 'Kuehlschrank-Organisierboxen stapelbar (4er-Set)',
            'source': 'AliExpress',
            'category': 'Haushalt',
            'trend_score': 810,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=fridge+organizer+bins+stackable+transparent+set&SortType=total_tranpro_desc',
            'description': 'Stapelbare transparente Kuehlschrankboxen. Viral auf Instagram. EK ca. 6-12 EUR, VK 25-40 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_blackhead_vacuum',
            'name': 'Mitesser-Absauggeraet mit LED-Kamera & App',
            'source': 'AliExpress',
            'category': 'Beauty',
            'trend_score': 830,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=blackhead+remover+vacuum+suction+camera+app&SortType=total_tranpro_desc',
            'description': 'Elektrisches Vakuum-Geraet mit eingebauter Kamera & App. Riesiger TikTok-Hit. EK ca. 8-15 EUR, VK 30-50 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_shower_filter',
            'name': 'Duschkopf-Wasserfilter gegen Chlor & Kalk (Vitamin C)',
            'source': 'AliExpress',
            'category': 'Bad',
            'trend_score': 760,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=shower+head+filter+chlorine+vitamin+C+hair&SortType=total_tranpro_desc',
            'description': 'Filterduschkopf mit Vitamin-C-Kartuschen fuer gesundes Haar. EK ca. 6-12 EUR, VK 25-45 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_led_mirror',
            'name': 'LED-Schminkspiegel mit Bluetooth-Lautsprecher',
            'source': 'AliExpress',
            'category': 'Bad',
            'trend_score': 800,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=LED+makeup+mirror+bluetooth+speaker+light+USB&SortType=total_tranpro_desc',
            'description': 'Beleuchteter Klappspiegel mit eingebautem BT-Lautsprecher & USB-Ladeport. EK ca. 15-25 EUR, VK 50-80 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_crystal_hair_eraser',
            'name': 'Kristall-Haarentferner nano (schmerzfrei, wiederverwendbar)',
            'source': 'AliExpress',
            'category': 'Beauty',
            'trend_score': 770,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=crystal+hair+eraser+remover+painless+nano+glass&SortType=total_tranpro_desc',
            'description': 'Nano-Glas-Haarentferner ohne Klinge oder Chemie. Viral auf TikTok. EK ca. 2-4 EUR, VK 15-25 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_diatomite_mat',
            'name': 'Diatomit-Badematte ultraschnell trocknend (Steinoptik)',
            'source': 'AliExpress',
            'category': 'Bad',
            'trend_score': 740,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=diatomite+bath+mat+quick+dry+stone+bathroom&SortType=total_tranpro_desc',
            'description': 'Steinmatte aus Diatomeenerde, trocknet in Sekunden. Nachhaltig & stilvoll. EK ca. 8-15 EUR, VK 30-50 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_mini_drone',
            'name': 'Mini-Drohne mit 4K-Kamera & Faltarmen (GPS-Rueckkehr)',
            'source': 'AliExpress',
            'category': 'Drohnen',
            'trend_score': 950,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=mini+drone+4K+camera+foldable+GPS+brushless&SortType=total_tranpro_desc',
            'description': 'Kompakte Einsteiger-Drohne mit 4K-Kamera, GPS-Rueckkehr & 20 Min. Flugzeit. EK ca. 35-60 EUR, VK 90-160 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_magsafe_wallet',
            'name': 'MagSafe-Kartenhalter & Geldbeutel fuer iPhone',
            'source': 'AliExpress',
            'category': 'Handy-Zubehoer',
            'trend_score': 820,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=magsafe+wallet+card+holder+magnetic+iPhone+15&SortType=total_tranpro_desc',
            'description': 'Magnetisches Karten-Wallet fuer iPhone 12-16 Pro Max. Guenstiger Apple-Klon. EK ca. 3-6 EUR, VK 18-30 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_portable_cooler',
            'name': 'Mini-USB-Luftkuehler Desktop (Verdunstungskuehler)',
            'source': 'AliExpress',
            'category': 'Smart Home',
            'trend_score': 860,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=mini+air+cooler+USB+portable+evaporative+desktop&SortType=total_tranpro_desc',
            'description': 'Verdunstungskuehler mit Wassertank fuer Schreibtisch & Bett. Sommer-Trendprodukt. EK ca. 10-18 EUR, VK 35-60 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_smart_plug',
            'name': 'WLAN-Smart-Stecker EU (Alexa & Google Home)',
            'source': 'AliExpress',
            'category': 'Smart Home',
            'trend_score': 750,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=smart+plug+wifi+alexa+google+home+EU+energy+monitor&SortType=total_tranpro_desc',
            'description': 'EU-Stecker mit App-Steuerung & Energiemessung. Dauerhafter Bestseller. EK ca. 3-7 EUR, VK 15-25 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_bt_keyboard',
            'name': 'Faltbares Bluetooth-Keyboard Reisetastatur (ultraduenn)',
            'source': 'AliExpress',
            'category': 'Buero',
            'trend_score': 700,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=foldable+bluetooth+keyboard+mini+travel+wireless+slim&SortType=total_tranpro_desc',
            'description': 'Ultraduenne BT-Tastatur fuer Smartphone & Tablet. Passt in jede Tasche. EK ca. 8-15 EUR, VK 30-50 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_filter_bottle',
            'name': 'Wasserfilter-Trinkflasche 550ml (Survival, Camping)',
            'source': 'AliExpress',
            'category': 'Outdoor',
            'trend_score': 790,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=water+filter+bottle+survival+purification+hiking+550ml&SortType=total_tranpro_desc',
            'description': 'Filtert Bakterien & Viren direkt beim Trinken. Camping & Reise-Must-have. EK ca. 8-15 EUR, VK 30-50 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_solar_powerbank',
            'name': 'Solar-Powerbank 20000mAh wasserdicht (Outdoor, LED)',
            'source': 'AliExpress',
            'category': 'Outdoor',
            'trend_score': 840,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=solar+power+bank+20000mAh+waterproof+LED+camping&SortType=total_tranpro_desc',
            'description': 'Outdoor-Powerbank mit Solarpanel, LED-Taschenlampe & USB-C. EK ca. 12-20 EUR, VK 40-65 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_wireless_car_charger',
            'name': 'Magnetischer KFZ-Handyhalter 15W Wireless Charging',
            'source': 'AliExpress',
            'category': 'Auto-Zubehoer',
            'trend_score': 880,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=magnetic+car+phone+holder+wireless+charger+15W+MagSafe&SortType=total_tranpro_desc',
            'description': 'Automatischer Klemm-Halter mit kabellosem Schnellladen 15W. Bestseller 2025. EK ca. 12-20 EUR, VK 40-70 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_resistance_bands',
            'name': 'Resistance-Bands Stoff-Set 5-teilig (Booty, Gym)',
            'source': 'AliExpress',
            'category': 'Fitness',
            'trend_score': 740,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=resistance+bands+set+fabric+booty+gym+5+levels&SortType=total_tranpro_desc',
            'description': 'Stoff-Widerstandsbaender in 5 Staerken fuer Po & Beine. Immergruenprodukt. EK ca. 3-6 EUR, VK 18-30 EUR.',
            'image_url': None,
            'fetched_at': now
        },
        {
            'id': 'ali_trekking_pole',
            'name': 'Carbon-Teleskop-Wanderstock faltbar ultraleicht (Paar)',
            'source': 'AliExpress',
            'category': 'Outdoor',
            'trend_score': 660,
            'link': 'https://de.aliexpress.com/wholesale?SearchText=carbon+fiber+trekking+pole+folding+ultralight+anti+shock&SortType=total_tranpro_desc',
            'description': 'Ultraleichtes Carbon-Stockpaar mit Anti-Schock-Daempfung. EK ca. 15-25 EUR, VK 60-90 EUR.',
            'image_url': None,
            'fetched_at': now
        },
    ]



# ── DB und Cache initialisieren (auch unter Gunicorn) ────────────

with app.app_context():
    db.create_all()
    # Kuratierte Produkte direkt beim Start laden
    products_cache = fetch_aliexpress_products()
    last_refresh = datetime.utcnow()



HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DropshipFinder – Täglich Trending</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a; --border: #2e3248;
      --accent: #6c63ff; --accent2: #ff6584; --tiktok: #fe2c55; --reddit: #ff4500;
      --google: #4285f4; --ali: #ff6a00; --text: #e8eaf0; --muted: #8b8fa8;
      --success: #4caf50; --radius: 10px;
    }
    body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }
    header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 2rem; display: flex; align-items: center; justify-content: space-between; height: 64px; position: sticky; top: 0; z-index: 100; }
    .logo { display: flex; align-items: center; gap: 10px; font-size: 1.2rem; font-weight: 700; }
    .logo-icon { width: 36px; height: 36px; background: linear-gradient(135deg, var(--accent), var(--accent2)); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
    .header-right { display: flex; align-items: center; gap: 16px; }
    .last-updated { font-size: 0.8rem; color: var(--muted); }
    .btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 18px; border-radius: var(--radius); border: none; cursor: pointer; font-size: 0.88rem; font-weight: 600; transition: all 0.2s; }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover { background: #5a52e0; transform: translateY(-1px); }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
    main { max-width: 1400px; margin: 0 auto; padding: 2rem; }
    .stats-bar { display: flex; gap: 16px; margin-bottom: 1.5rem; flex-wrap: wrap; }
    .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 20px; flex: 1; min-width: 140px; }
    .stat-label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
    .stat-value { font-size: 1.5rem; font-weight: 700; }
    .tabs { display: flex; gap: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 4px; margin-bottom: 1.5rem; width: fit-content; }
    .tab { padding: 8px 20px; border-radius: 7px; border: none; background: transparent; color: var(--muted); cursor: pointer; font-size: 0.88rem; font-weight: 600; transition: all 0.2s; }
    .tab.active { background: var(--accent); color: #fff; }
    .tab:hover:not(.active) { color: var(--text); background: var(--surface2); }
    .controls { display: flex; gap: 12px; margin-bottom: 1.2rem; flex-wrap: wrap; align-items: center; }
    .search-box { flex: 1; min-width: 200px; position: relative; }
    .search-box input { width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 9px 14px 9px 38px; color: var(--text); font-size: 0.88rem; outline: none; transition: border-color 0.2s; }
    .search-box input:focus { border-color: var(--accent); }
    .search-box input::placeholder { color: var(--muted); }
    .search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--muted); font-size: 14px; }
    .source-filter { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 9px 14px; color: var(--text); font-size: 0.88rem; outline: none; cursor: pointer; }
    .table-wrapper { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
    table { width: 100%; border-collapse: collapse; }
    thead { background: var(--surface2); border-bottom: 1px solid var(--border); }
    th { padding: 12px 16px; text-align: left; font-size: 0.78rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; cursor: pointer; user-select: none; transition: color 0.2s; }
    th:hover { color: var(--text); }
    th .sort-arrow { margin-left: 4px; font-size: 10px; }
    td { padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 0.88rem; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(108, 99, 255, 0.04); }
    .source-badge { display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
    .badge-tiktok { background: rgba(254,44,85,0.15); color: var(--tiktok); }
    .badge-reddit { background: rgba(255,69,0,0.15); color: var(--reddit); }
    .badge-google { background: rgba(66,133,244,0.15); color: var(--google); }
    .badge-aliexpress { background: rgba(255,106,0,0.15); color: var(--ali); }
    .badge-default { background: rgba(255,255,255,0.08); color: var(--muted); }
    .trend-score { display: inline-flex; align-items: center; gap: 5px; font-weight: 700; font-size: 0.88rem; }
    .trend-bar { height: 4px; border-radius: 2px; background: linear-gradient(90deg, var(--accent), var(--accent2)); min-width: 4px; }
    .product-name { font-weight: 600; color: var(--text); max-width: 320px; line-height: 1.4; }
    .product-desc { font-size: 0.78rem; color: var(--muted); margin-top: 3px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .link-btn { display: inline-flex; align-items: center; gap: 5px; padding: 5px 12px; border-radius: 6px; background: var(--surface2); border: 1px solid var(--border); color: var(--text); text-decoration: none; font-size: 0.78rem; font-weight: 600; transition: all 0.2s; white-space: nowrap; }
    .link-btn:hover { background: var(--accent); border-color: var(--accent); color: #fff; }
    .bookmark-btn { background: none; border: 1px solid var(--border); border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 16px; transition: all 0.2s; line-height: 1; }
    .bookmark-btn:hover { border-color: #ffd700; background: rgba(255,215,0,0.1); }
    .bookmark-btn.active { border-color: #ffd700; background: rgba(255,215,0,0.15); }
    .empty-state { text-align: center; padding: 60px 20px; color: var(--muted); }
    .empty-state .icon { font-size: 48px; margin-bottom: 16px; }
    .empty-state h3 { font-size: 1.1rem; color: var(--text); margin-bottom: 8px; }
    .empty-state p { font-size: 0.88rem; }
    .loading-overlay { display: none; position: fixed; inset: 0; background: rgba(15,17,23,0.7); backdrop-filter: blur(4px); z-index: 200; align-items: center; justify-content: center; flex-direction: column; gap: 16px; }
    .loading-overlay.visible { display: flex; }
    .spinner { width: 48px; height: 48px; border: 4px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .loading-text { color: var(--text); font-size: 0.95rem; font-weight: 600; }
    .toast { position: fixed; bottom: 24px; right: 24px; background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 20px; font-size: 0.88rem; font-weight: 600; z-index: 300; transform: translateY(80px); opacity: 0; transition: all 0.3s ease; max-width: 320px; }
    .toast.show { transform: translateY(0); opacity: 1; }
    .toast.success { border-left: 4px solid var(--success); }
    .toast.error { border-left: 4px solid var(--accent2); }
    @media (max-width: 768px) { header { padding: 0 1rem; } main { padding: 1rem; } .product-name { max-width: 180px; } .product-desc { display: none; } }
  </style>
</head>
<body>
<div class="loading-overlay" id="loadingOverlay"><div class="spinner"></div><div class="loading-text">Daten werden geladen…</div></div>
<div class="toast" id="toast"></div>
<header>
  <div class="logo"><div class="logo-icon">🚀</div><span>DropshipFinder</span></div>
  <div class="header-right">
    <span class="last-updated" id="lastUpdated">Noch nicht aktualisiert</span>
    <button class="btn btn-primary" id="refreshBtn" onclick="refreshData()"><span>↻</span> Jetzt aktualisieren</button>
  </div>
</header>
<main>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-label">Produkte gesamt</div><div class="stat-value" id="statTotal">–</div></div>
    <div class="stat-card"><div class="stat-label">Bookmarks</div><div class="stat-value" id="statBookmarks">–</div></div>
    <div class="stat-card"><div class="stat-label">Quellen aktiv</div><div class="stat-value" id="statSources">4</div></div>
    <div class="stat-card"><div class="stat-label">Heute</div><div class="stat-value" id="statDate">–</div></div>
  </div>
  <div class="tabs">
    <button class="tab active" onclick="switchTab('all', this)">Alle Produkte</button>
    <button class="tab" onclick="switchTab('bookmarks', this)">⭐ Bookmarks</button>
  </div>
  <div class="controls">
    <div class="search-box">
      <span class="search-icon">🔍</span>
      <input type="text" id="searchInput" placeholder="Produkte suchen…" oninput="applyFilters()" />
    </div>
    <select class="source-filter" id="sourceFilter" onchange="applyFilters()">
      <option value="">Alle Quellen</option>
      <option value="Reddit">Reddit</option>
      <option value="Google Trends">Google Trends</option>
      <option value="TikTok">TikTok Creative Center</option>
      <option value="AliExpress">AliExpress</option>
    </select>
  </div>
  <div class="table-wrapper">
    <table>
      <thead>
        <tr>
          <th onclick="sortBy('name')">Produkt <span class="sort-arrow" id="sort-name"></span></th>
          <th onclick="sortBy('source')">Quelle <span class="sort-arrow" id="sort-source"></span></th>
          <th onclick="sortBy('category')">Kategorie <span class="sort-arrow" id="sort-category"></span></th>
          <th onclick="sortBy('trend_score')">Trend-Score <span class="sort-arrow" id="sort-trend_score">↓</span></th>
          <th>Link</th>
          <th>Merken</th>
        </tr>
      </thead>
      <tbody id="tableBody">
        <tr><td colspan="6"><div class="empty-state"><div class="icon">🔄</div><h3>Noch keine Daten</h3><p>Klicke auf „Jetzt aktualisieren", um Trending-Produkte zu laden.</p></div></td></tr>
      </tbody>
    </table>
  </div>
</main>
<script>
  let allProducts = [], bookmarkedProducts = [], currentTab = 'all';
  let sortColumn = 'trend_score', sortDir = 'desc', bookmarkedIds = new Set();

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('statDate').textContent = new Date().toLocaleDateString('de-DE', {day:'2-digit',month:'2-digit',year:'numeric'});
    loadProducts(); loadBookmarks();
  });

  async function loadProducts() {
    try {
      const r = await fetch('/api/products');
      const data = await r.json();
      allProducts = data.products || [];
      bookmarkedIds = new Set(allProducts.filter(p => p.bookmarked).map(p => p.id));
      if (data.last_refresh) setLastUpdated(data.last_refresh);
      updateStats(); applyFilters();
    } catch(e) { console.error('Fehler:', e); }
  }

  async function loadBookmarks() {
    try {
      const r = await fetch('/api/bookmarks');
      bookmarkedProducts = await r.json();
      document.getElementById('statBookmarks').textContent = bookmarkedProducts.length;
    } catch(e) {}
  }

  async function refreshData() {
    const btn = document.getElementById('refreshBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block"></span> Wird geladen…';
    document.getElementById('loadingOverlay').classList.add('visible');
    try {
      const r = await fetch('/api/refresh', {method:'POST'});
      const data = await r.json();
      if (data.success) { await loadProducts(); await loadBookmarks(); showToast('✅ ' + data.count + ' Produkte geladen', 'success'); }
    } catch(e) { showToast('Fehler beim Aktualisieren', 'error'); }
    finally { btn.disabled = false; btn.innerHTML = '<span>↻</span> Jetzt aktualisieren'; document.getElementById('loadingOverlay').classList.remove('visible'); }
  }

  function switchTab(tab, el) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active'); applyFilters();
  }

  function applyFilters() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const sf = document.getElementById('sourceFilter').value.toLowerCase();
    let data = currentTab === 'bookmarks' ? bookmarkedProducts.map(b => ({...b, bookmarked:true})) : allProducts;
    if (search) data = data.filter(p => p.name.toLowerCase().includes(search) || (p.description||'').toLowerCase().includes(search));
    if (sf) data = data.filter(p => p.source.toLowerCase().includes(sf));
    data = [...data].sort((a,b) => {
      let va = a[sortColumn]??'', vb = b[sortColumn]??'';
      if (typeof va==='string') va=va.toLowerCase();
      if (typeof vb==='string') vb=vb.toLowerCase();
      return sortDir==='asc' ? (va<vb?-1:va>vb?1:0) : (va>vb?-1:va<vb?1:0);
    });
    renderTable(data);
  }

  function sortBy(col) {
    sortDir = sortColumn===col ? (sortDir==='asc'?'desc':'asc') : 'desc';
    sortColumn = col;
    document.querySelectorAll('.sort-arrow').forEach(el => el.textContent='');
    document.getElementById('sort-'+col).textContent = sortDir==='asc'?'↑':'↓';
    applyFilters();
  }

  function renderTable(products) {
    const tbody = document.getElementById('tableBody');
    if (!products.length) {
      tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="icon">'+(currentTab==='bookmarks'?'⭐':'🔍')+'</div><h3>'+(currentTab==='bookmarks'?'Noch keine Bookmarks':'Keine Produkte gefunden')+'</h3><p>'+(currentTab==='bookmarks'?'Markiere Produkte mit dem ⭐-Button.':'Versuche andere Suchbegriffe oder klicke auf Jetzt aktualisieren.')+'</p></div></td></tr>';
      return;
    }
    const maxScore = Math.max(...products.map(p=>p.trend_score||0), 1);
    tbody.innerHTML = products.map(p => {
      const isBookmarked = bookmarkedIds.has(p.id)||p.bookmarked;
      const score = p.trend_score||0;
      const barWidth = Math.max(4, Math.round((score/maxScore)*60));
      return '<tr><td><div class="product-name">'+escHtml(p.name)+'</div>'+(p.description?'<div class="product-desc">'+escHtml(p.description)+'</div>':'')+'</td>'
        +'<td><span class="source-badge '+sourceBadgeClass(p.source)+'">'+sourceIcon(p.source)+' '+escHtml(p.source)+'</span></td>'
        +'<td><span style="color:var(--muted);font-size:0.82rem">'+escHtml(p.category||'–')+'</span></td>'
        +'<td><div class="trend-score"><div class="trend-bar" style="width:'+barWidth+'px"></div><span>'+(score>=999?'🔥 Breakout':score.toLocaleString('de-DE'))+'</span></div></td>'
        +'<td><a href="'+escHtml(p.link||'#')+'" target="_blank" rel="noopener" class="link-btn">↗ Öffnen</a></td>'
        +'<td><button class="bookmark-btn'+(isBookmarked?' active':'')+'" onclick="toggleBookmark(this,'+JSON.stringify(p).replace(/'/g,"\\'")+\')" title="'+(isBookmarked?'Bookmark entfernen':'Als Bookmark speichern')+'">'+(isBookmarked?'⭐':'☆')+'</button></td></tr>';
    }).join('');
  }

  async function toggleBookmark(btn, product) {
    const isBookmarked = bookmarkedIds.has(product.id);
    if (isBookmarked) {
      try {
        const r = await fetch('/api/bookmarks/'+encodeURIComponent(product.id), {method:'DELETE'});
        const d = await r.json();
        if (d.success) { bookmarkedIds.delete(product.id); btn.classList.remove('active'); btn.textContent='☆'; showToast('Bookmark entfernt','success'); await loadBookmarks(); if(currentTab==='bookmarks') applyFilters(); }
      } catch(e) { showToast('Fehler','error'); }
    } else {
      try {
        const r = await fetch('/api/bookmarks', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(product)});
        const d = await r.json();
        if (d.success) { bookmarkedIds.add(product.id); btn.classList.add('active'); btn.textContent='⭐'; showToast('⭐ Gespeichert!','success'); await loadBookmarks(); }
        else showToast('Bereits gespeichert','error');
      } catch(e) { showToast('Fehler','error'); }
    }
  }

  function sourceBadgeClass(s) {
    if (!s) return 'badge-default';
    s = s.toLowerCase();
    if (s.includes('tiktok')) return 'badge-tiktok';
    if (s.includes('reddit')) return 'badge-reddit';
    if (s.includes('google')) return 'badge-google';
    if (s.includes('aliexpress')) return 'badge-aliexpress';
    return 'badge-default';
  }

  function sourceIcon(s) {
    if (!s) return '';
    s = s.toLowerCase();
    if (s.includes('tiktok')) return '🎵';
    if (s.includes('reddit')) return '🤖';
    if (s.includes('google')) return '📈';
    if (s.includes('aliexpress')) return '🛒';
    return '🌐';
  }

  function escHtml(str) {
    return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function setLastUpdated(iso) {
    const d = new Date(iso);
    document.getElementById('lastUpdated').textContent = 'Zuletzt: '+d.toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+' Uhr';
  }

  function updateStats() {
    document.getElementById('statTotal').textContent = allProducts.length;
    document.getElementById('statSources').textContent = new Set(allProducts.map(p=>p.source)).size || 4;
  }

  function showToast(msg, type='success') {
    const t = document.getElementById('toast');
    t.textContent = msg; t.className = 'toast '+type+' show';
    setTimeout(() => t.classList.remove('show'), 3000);
  }
</script>
</body>
</html>"""


# ── API-Endpunkte ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/products', methods=['GET'])
def get_products():
    bookmarked_ids = {b.product_id for b in Bookmark.query.all()}
    enriched = [{**p, 'bookmarked': p['id'] in bookmarked_ids} for p in products_cache]
    return jsonify({
        'products': enriched,
        'last_refresh': last_refresh.isoformat() if last_refresh else None,
        'count': len(enriched)
    })


@app.route('/api/refresh', methods=['POST'])
def refresh_products():
    global products_cache, last_refresh
    all_products = fetch_reddit_products() + fetch_tiktok_products() + fetch_google_trends_products() + fetch_aliexpress_products()

    seen, unique = set(), []
    for p in all_products:
        if p['id'] not in seen:
            seen.add(p['id']); unique.append(p)

    unique.sort(key=lambda x: x.get('trend_score', 0), reverse=True)
    products_cache = unique
    last_refresh = datetime.utcnow()
    return jsonify({'success': True, 'count': len(unique), 'last_refresh': last_refresh.isoformat()})


@app.route('/api/bookmarks', methods=['GET'])
def get_bookmarks():
    return jsonify([{
        'id': b.id, 'product_id': b.product_id, 'name': b.name, 'source': b.source,
        'category': b.category, 'trend_score': b.trend_score, 'link': b.link,
        'description': b.description, 'image_url': b.image_url, 'bookmarked': True,
        'created_at': b.created_at.isoformat()
    } for b in Bookmark.query.order_by(Bookmark.created_at.desc()).all()])


@app.route('/api/bookmarks', methods=['POST'])
def add_bookmark():
    data = request.json
    if not data or not data.get('product_id'):
        return jsonify({'success': False, 'message': 'Fehlende Daten'}), 400
    if Bookmark.query.filter_by(product_id=data['product_id']).first():
        return jsonify({'success': False, 'message': 'Bereits gespeichert'})
    db.session.add(Bookmark(
        product_id=data['product_id'], name=data.get('name', ''),
        source=data.get('source', ''), category=data.get('category', ''),
        trend_score=data.get('trend_score', 0), link=data.get('link', ''),
        description=data.get('description', ''), image_url=data.get('image_url', '')
    ))
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/bookmarks/<path:product_id>', methods=['DELETE'])
def remove_bookmark(product_id):
    b = Bookmark.query.filter_by(product_id=product_id).first()
    if b:
        db.session.delete(b); db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False}), 404


# ── Start ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
