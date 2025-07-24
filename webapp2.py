# webapp.py - Auto Parts Finder - EXCLUSIVO REPUESTOS DE AUTOS (USA)
from flask import Flask, request, jsonify, session, redirect, url_for, render_template_string, flash
import requests
import os
import re
import html
import time
import io
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from functools import wraps

# Imports para búsqueda por imagen (opcionales)
try:
    from PIL import Image
    PIL_AVAILABLE = True
    print("✅ PIL (Pillow) disponible para procesamiento de imagen")
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ PIL (Pillow) no disponible - búsqueda por imagen limitada")

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
    print("✅ Google Generative AI (Gemini) disponible")
except ImportError:
    genai = None
    GEMINI_AVAILABLE = False
    print("⚠️ Google Generative AI no disponible - instalar con: pip install google-generativeai")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-key-change-in-production')
app.config['PERMANENT_SESSION_LIFETIME'] = 1800
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True if os.environ.get('RENDER') else False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# --- CONFIGURACIÓN DE APIs ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        print("✅ API de Google Gemini configurada correctamente")
        GEMINI_READY = True
    except Exception as e:
        print(f"❌ Error configurando Gemini: {e}")
        GEMINI_READY = False
else:
    GEMINI_READY = False
    print("⚠️ Gemini no disponible o sin API Key. Búsqueda por imagen desactivada.")

# =============================================================================
# VALIDACIÓN DE RELEVANCIA DE BÚSQUEDA
# =============================================================================
AUTO_PART_KEYWORDS = {
    # Español
    'repuesto', 'parte', 'pieza', 'freno', 'pastilla', 'disco', 'motor', 'filtro', 'aceite',
    'aire', 'bujia', 'bobina', 'alternador', 'arranque', 'bateria', 'suspension', 'amortiguador',
    'faro', 'luz', 'calavera', 'stop', 'parachoque', 'defensa', 'espejo', 'radiador', 'bomba', 'agua', 'gasolina',
    'llanta', 'rin', 'rueda', 'sensor', 'inyector', 'correa', 'banda', 'cadena', 'tiempo', 'escape',
    'silenciador', 'catalizador', 'balero', 'rodamiento', 'eje', 'homocinetica', 'transmision',
    'embrague', 'clutch', 'termostato', 'valvula', 'marcha', 'maf', 'map', 'oxigeno', 'horquilla', 'rotula',
    # Inglés
    'part', 'replacement', 'brake', 'pad', 'rotor', 'caliper', 'engine', 'filter', 'oil',
    'air', 'spark', 'plug', 'coil', 'ignition', 'alternator', 'starter', 'battery', 'suspension',
    'shock', 'strut', 'absorber', 'headlight', 'taillight', 'light', 'bulb', 'bumper', 'mirror',
    'radiator', 'pump', 'water', 'fuel', 'tire', 'rim', 'wheel', 'sensor', 'injector', 'belt',
    'chain', 'timing', 'exhaust', 'muffler', 'converter', 'bearing', 'axle', 'cv-joint',
    'transmission', 'clutch', 'thermostat', 'gasket', 'valve', 'maf', 'map', 'oxygen', 'control-arm', 'ball-joint'
}


# =============================================================================
# INTEGRACIÓN DE VEHICLEDATABASES.COM API
# =============================================================================
class VehicleDB:
    def __init__(self):
        self.api_id = os.environ.get('VEHICLE_API_ID')
        self.api_key = os.environ.get('VEHICLE_API_KEY')
        self.base_url = "https://api.vehicledatabases.com/v1"
        if self.api_id and self.api_key:
            print(f"✅ VehicleDatabases.com API configurada (ID: {self.api_id})")
        else:
            print("⚠️ VehicleDatabases.com API no configurada. Funcionalidad limitada.")

    def is_configured(self):
        return self.api_id and self.api_key

    def search_by_ymm(self, year, make, model):
        if not self.is_configured(): return None
        endpoint = f"{self.base_url}/vehicles/ymm-search"
        params = {'api_key': self.api_key, 'api_id': self.api_id, 'year': year, 'make': make, 'model': model}
        try:
            response = requests.get(endpoint, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and 'vehicle_id' in data[0]:
                print(f"🚗 Vehículo encontrado en DB: {data[0]['year']} {data[0]['make']} {data[0]['model']}")
                return data[0]
            return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Error en API VehicleDatabases: {e}")
            return None

vehicle_db_client = VehicleDB()


# =============================================================================
# BASE DE DATOS INTERNA DE AUTOPARTES Y MARCAS
# =============================================================================
AUTO_PARTS_STORES = {
    'rockauto.com', 'autozone.com', 'oreillyauto.com', 'shop.advanceautoparts.com',
    'napaonline.com', 'carparts.com', 'partsgeek.com', 'fcpeuro.com', 'pelicanparts.com', 'tascaparts.com'
}

CAR_BRAND_EQUIVALENTS = {
    'ford': {'oem_sites': ['parts.ford.com', 'tascaparts.com'], 'compatible_brands': ['lincoln', 'mercury']},
    'chevrolet': {'oem_sites': ['gmpartsdirect.com', 'gmpartsgiant.com'], 'compatible_brands': ['gmc', 'cadillac', 'buick']},
    'toyota': {'oem_sites': ['parts.toyota.com', 'toyotapartsdeal.com'], 'compatible_brands': ['lexus', 'scion']},
    'honda': {'oem_sites': ['hondapartsnow.com', 'bernardiparts.com'], 'compatible_brands': ['acura']},
    'nissan': {'oem_sites': ['nissanpartsdeal.com', 'nissanpartsplus.com'], 'compatible_brands': ['infiniti']},
    'bmw': {'oem_sites': ['getbmwparts.com', 'bimmerworld.com', 'fcpeuro.com'], 'compatible_brands': ['mini']},
    'gmc': {'oem_sites': ['gmpartsdirect.com', 'gmpartsgiant.com'], 'compatible_brands': ['chevrolet']},
    'dodge': {'oem_sites': ['mopar.com', 'allmoparparts.com'], 'compatible_brands': ['chrysler', 'jeep', 'ram']},
    'jeep': {'oem_sites': ['mopar.com', 'allmoparparts.com'], 'compatible_brands': ['dodge', 'chrysler']},
    'volkswagen': {'oem_sites': ['parts.vw.com'], 'compatible_brands': ['audi']},
    # ... se pueden agregar más marcas
}
ALL_CAR_BRANDS = set(CAR_BRAND_EQUIVALENTS.keys())


# =============================================================================
# CLASE DE AUTENTICACIÓN
# =============================================================================
class FirebaseAuth:
    def __init__(self):
        self.firebase_web_api_key = os.environ.get("FIREBASE_WEB_API_KEY")
        if not self.firebase_web_api_key: print("WARNING: FIREBASE_WEB_API_KEY no configurada")
        else: print("SUCCESS: Firebase Auth configurado")

    def login_user(self, email, password):
        if not self.firebase_web_api_key: return {'success': False, 'message': 'Servicio no configurado'}
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.firebase_web_api_key}"
        payload = {'email': email, 'password': password, 'returnSecureToken': True}
        try:
            response = requests.post(url, json=payload, timeout=8)
            response.raise_for_status()
            return {'success': True, 'message': 'Bienvenido!', 'user_data': response.json()}
        except requests.exceptions.HTTPError:
            return {'success': False, 'message': 'Correo o contraseña incorrectos'}
        except Exception:
            return {'success': False, 'message': 'Error de conexión'}

    def set_user_session(self, user_data):
        session['user_id'] = user_data['localId']
        session['user_name'] = user_data.get('displayName', user_data['email'].split('@')[0])
        session.permanent = True

    def clear_user_session(self): session.clear()
    def is_user_logged_in(self): return 'user_id' in session
    def get_current_user(self): return {'user_name': session.get('user_name')} if self.is_user_logged_in() else None

firebase_auth = FirebaseAuth()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not firebase_auth.is_user_logged_in():
            flash('Tu sesión ha expirado. Inicia sesión nuevamente.', 'warning')
            return redirect(url_for('auth_login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ==============================================================================
# LÓGICA DE BÚSQUEDA DE AUTOPARTES ESPECIALIZADA
# ==============================================================================
class AutoPartsFinder:
    def __init__(self):
        self.serpapi_key = os.environ.get('SERPAPI_KEY')
        if not self.serpapi_key: print("⚠️ SerpAPI no configurado. Se usarán resultados de ejemplo.")
        else: print(f"✅ SerpAPI configurado (key: ...{self.serpapi_key[-4:]})")

    def is_valid_auto_part_query(self, query):
        """Verifica si la consulta parece ser para un repuesto de auto."""
        query_lower = " " + query.lower() + " "
        if any(f" {keyword} " in query_lower for keyword in AUTO_PART_KEYWORDS): return True
        if any(f" {brand} " in query_lower for brand in ALL_CAR_BRANDS): return True
        if re.search(r'\b(19[6-9]\d|20[0-2]\d|2030)\b', query_lower): return True
        print(f"🕵️ Búsqueda rechazada: '{query}' no parece ser un repuesto de auto.")
        return False

    def _extract_price(self, text):
        if not text: return 0.0
        match = re.search(r'\$?(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)', str(text))
        return float(match.group(1).replace(',', '')) if match else 0.0

    def _make_api_request(self, query):
        if not self.serpapi_key: return None
        params = {'api_key': self.serpapi_key, 'engine': 'google', 'q': query, 'location': 'United States', 'gl': 'us', 'hl': 'en', 'num': 10}
        try:
            response = requests.get("https://serpapi.com/search", params=params, timeout=12)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Error en SerpAPI: {e}")
            return None

    def _process_results(self, data, query_info):
        products = []
        if not data or 'organic_results' not in data: return []
        for item in data['organic_results']:
            link = item.get('link', '#')
            # Filtro agresivo para solo tiendas de USA
            if not any(domain in link for domain in AUTO_PARTS_STORES.union(query_info.get('oem_sites', set()))):
                continue
            
            price_str, price_num = None, 0.0
            if item.get('rich_snippet') and 'top' in item['rich_snippet']:
                price_str = item['rich_snippet']['top'].get('detected_extensions', {}).get('price')
                price_num = self._extract_price(price_str)
            
            if price_num > 0:
                products.append({
                    'title': html.escape(item.get('title', 'Sin Título')),
                    'price': price_str or f"${price_num:.2f}", 'price_numeric': price_num,
                    'source': urlparse(link).hostname.replace('www.', ''),
                    'link': link, 'is_oem': query_info['type'] == 'oem',
                    'compatibility_note': query_info.get('note', '')
                })
        return products

    def search_parts(self, text_query, target_brand=None):
        if not self.is_valid_auto_part_query(text_query):
            return "INVALID_QUERY"

        if not self.serpapi_key:
            return [{'title': f'Ejemplo: Filtro de Aceite para {target_brand or "Ford"}', 'price': '$15.50', 'price_numeric': 15.50, 'source': 'oemparts.com', 'link': '#', 'is_oem': True, 'compatibility_note': ''}]

        query_lower = text_query.lower()
        final_brand = target_brand or next((brand for brand in ALL_CAR_BRANDS if brand in query_lower), None)
        if not final_brand:
            flash("Por favor, especifica una marca de auto en tu búsqueda o selecciónala.", "warning")
            return []

        all_products, seen_links = [], set()
        brand_data = CAR_BRAND_EQUIVALENTS.get(final_brand, {})
        
        # 1. Búsqueda OEM
        oem_sites = brand_data.get('oem_sites', [])
        if oem_sites:
            oem_query = f'"{text_query}" site:{" OR site:".join(oem_sites)}'
            data = self._make_api_request(oem_query)
            all_products.extend(self._process_results(data, {'type': 'oem', 'oem_sites': oem_sites}))
            seen_links.update(p['link'] for p in all_products)

        # 2. Búsqueda en Tiendas Aftermarket
        aftermarket_query = f'"{text_query}" site:{" OR site:".join(AUTO_PARTS_STORES)}'
        data = self._make_api_request(aftermarket_query)
        for p in self._process_results(data, {'type': 'aftermarket'}):
            if p['link'] not in seen_links: all_products.append(p)

        # 3. Búsqueda de Equivalentes
        if len(all_products) < 5:
            for comp_brand in brand_data.get('compatible_brands', []):
                comp_query_text = text_query.replace(final_brand, comp_brand)
                comp_query = f'"{comp_query_text}" site:{" OR site:".join(AUTO_PARTS_STORES)}'
                data = self._make_api_request(comp_query)
                for p in self._process_results(data, {'type': 'compatible', 'note': f'Compatible con {final_brand.upper()}'}):
                    if p['link'] not in seen_links: all_products.append(p)
        
        return sorted(all_products, key=lambda x: (not x['is_oem'], x['price_numeric']))[:10]

auto_parts_finder = AutoPartsFinder()


# ==============================================================================
# RUTAS DE LA APLICACIÓN FLASK
# ==============================================================================
@app.route('/auth/login-page')
def auth_login_page():
    return render_template_string("""
        <!DOCTYPE html><html lang="es"><head><title>Iniciar Sesión</title></head>
        <body><h1>Iniciar Sesión</h1><form method="post" action="/auth/login">
        <input name="email" placeholder="Correo" required><br>
        <input name="password" type="password" placeholder="Contraseña" required><br>
        <button type="submit">Entrar</button></form></body></html>
    """)

@app.route('/auth/login', methods=['POST'])
def auth_login():
    result = firebase_auth.login_user(request.form['email'], request.form['password'])
    if result['success']:
        firebase_auth.set_user_session(result['user_data'])
        return redirect(url_for('search_page'))
    flash(result['message'], 'danger')
    return redirect(url_for('auth_login_page'))

@app.route('/auth/logout')
def auth_logout():
    firebase_auth.clear_user_session()
    flash('Has cerrado la sesión correctamente.', 'success')
    return redirect(url_for('auth_login_page'))

@app.route('/')
def index():
    return redirect(url_for('search_page')) if firebase_auth.is_user_logged_in() else redirect(url_for('auth_login_page'))

@app.route('/search')
@login_required
def search_page():
    brands = sorted(list(CAR_BRAND_EQUIVALENTS.keys()))
    return render_template_string("""
        <!DOCTYPE html><html lang="es"><head><title>Buscar Repuestos</title>
        <style>body{font-family:sans-serif;max-width:800px;margin:auto;padding:20px;}
        .error{background-color:#f8d7da;color:#721c24;padding:10px;border-radius:5px;margin:10px 0;}
        form * {padding:8px;margin:5px;font-size:16px;}</style></head>
        <body><h1>🔧 Buscador de Repuestos de Auto (USA)</h1>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}{% for category, message in messages %}
                <div class="error"><strong>Error:</strong> {{ message }}</div>
            {% endfor %}{% endif %}
        {% endwith %}
        <form action="{{ url_for('handle_search') }}" method="POST">
            <input type="text" name="query" placeholder="Ej: brake pads 2018 ford f-150" required size="40">
            <select name="target_brand"><option value="">Marca (Opcional)</option>
            {% for brand in brands %}<option value="{{ brand }}">{{ brand.title() }}</option>{% endfor %}
            </select><button type="submit">Buscar</button></form></body></html>
    """, brands=brands)

@app.route('/handle_search', methods=['POST'])
@login_required
def handle_search():
    query = request.form.get('query')
    target_brand = request.form.get('target_brand')
    if not query:
        flash("Por favor, ingresa una pieza a buscar.", "danger")
        return redirect(url_for('search_page'))
    
    products = auto_parts_finder.search_parts(query, target_brand)
    
    if products == "INVALID_QUERY":
        flash("Sitio web exclusivamente para repuestos.", "danger")
        return redirect(url_for('search_page'))

    session['last_results'] = products
    session['last_query'] = query
    return redirect(url_for('results_page'))

@app.route('/results')
@login_required
def results_page():
    results = session.get('last_results', [])
    query = session.get('last_query', 'Búsqueda')
    return render_template_string("""
        <!DOCTYPE html><html lang="es"><head><title>Resultados</title>
        <style>body{font-family:sans-serif;max-width:800px;margin:auto;padding:20px;}
        .product{border:1px solid #ddd;padding:15px;margin:15px 0;border-radius:8px;position:relative;}
        .product.oem{border-left:5px solid #0d6efd;} .product.compatible{border-left:5px solid #ffc107;}
        .badge{font-weight:bold;padding:3px 8px;color:white;border-radius:10px;font-size:12px;display:inline-block;}
        .badge-oem{background-color:#0d6efd;} .badge-comp{background-color:#ffc107;}
        h3,p{margin:5px 0;}</style></head>
        <body><h1>Resultados para: "{{ query }}"</h1>
        <a href="{{ url_for('search_page') }}">Nueva Búsqueda</a><hr>
        {% for product in results %}
            <div class="product {{ 'oem' if product.is_oem else 'compatible' if product.compatibility_note else '' }}">
                {% if product.is_oem %}<span class="badge badge-oem">OEM Original</span>
                {% elif product.compatibility_note %}<span class="badge badge-comp">Compatible</span>{% endif %}
                <h3>{{ product.title }}</h3>
                <p><strong>Precio:</strong> {{ product.price }}</p>
                <p><strong>Vendido por:</strong> {{ product.source }}</p>
                {% if product.compatibility_note %}<p style="color:#856404;"><em>{{ product.compatibility_note }}</em></p>{% endif %}
                <a href="{{ product.link }}" target="_blank" rel="noopener noreferrer">Ver Producto</a>
            </div>
        {% else %}
            <p>No se encontraron resultados. Intenta ser más específico o revisa la ortografía.</p>
        {% endfor %}</body></html>
    """, results=results, query=query)


# --- PUNTO DE ENTRADA DE LA APLICACIÓN ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
