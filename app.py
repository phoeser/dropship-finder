import os
import json
import requests
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_DIR, 'data')
PRODUCTS_FILE = os.path.join(DATA_DIR, 'products.json')
REMOVED_FILE  = os.path.join(DATA_DIR, 'removed_products.json')
CONFIG_FILE   = os.path.join(DATA_DIR, 'shopify_config.json')

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

def normalize_store_url(url):
    url = url.strip().rstrip('/')
    if url and not url.startswith('http'):
        url = 'https://' + url
    return url

@app.route('/')
def index():
    products = load_json(PRODUCTS_FILE, [])
    removed  = set(load_json(REMOVED_FILE, []))
    active   = [p for p in products if p['id'] not in removed]
    for p in active:
        buy  = p.get('buy_price', 0)
        sell = p.get('sell_price', 0)
        p['profit']     = round(sell - buy, 2)
        p['margin_pct'] = round((sell - buy) / buy * 100, 1) if buy else 0
    config      = load_json(CONFIG_FILE, {})
    has_shopify = bool(config.get('store_url') and config.get('access_token'))
    store_url   = config.get('store_url', '')
    return render_template('index.html', products=active, has_shopify=has_shopify,
                           store_url=store_url, removed_count=len(removed), total_count=len(products))

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

@app.route('/api/import-shopify/<int:product_id>', methods=['POST'])
def import_shopify(product_id):
    config       = load_json(CONFIG_FILE, {})
    store_url    = config.get('store_url', '')
    access_token = config.get('access_token', '')
    if not store_url or not access_token:
        return jsonify({'success': False, 'error': 'Shopify nicht konfiguriert.'}), 400
    products = load_json(PRODUCTS_FILE, [])
    product  = next((p for p in products if p['id'] == product_id), None)
    if not product:
        return jsonify({'success': False, 'error': 'Produkt nicht gefunden.'}), 404
    payload = {
        'product': {
            'title': product['name'],
            'body_html': '<p>' + product['description'] + '</p>',
            'vendor': 'DropShip Finder',
            'product_type': product.get('category', ''),
            'status': 'draft',
            'variants': [{'price': str(product['sell_price']), 'inventory_management': None,
                          'fulfillment_service': 'manual', 'requires_shipping': True}],
            'images': [{'src': product['image']}] if product.get('image') else [],
        }
    }
    api_url = store_url + '/admin/api/2024-01/products.json'
    headers = {'X-Shopify-Access-Token': access_token, 'Content-Type': 'application/json'}
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'Verbindung fehlgeschlagen.'}), 502
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Timeout.'}), 504
    except requests.exceptions.RequestException as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500
    if resp.status_code in (200, 201):
        created = resp.json().get('product', {})
        shopify_id = created.get('id', '?')
        return jsonify({'success': True, 'shopify_id': shopify_id,
                        'admin_url': store_url + '/admin/products/' + str(shopify_id),
                        'message': 'Produkt importiert (ID: ' + str(shopify_id) + ')'})
    try:
        errors = resp.json().get('errors', resp.text)
    except Exception:
        errors = resp.text
    return jsonify({'success': False, 'error': str(errors)}), resp.status_code

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
