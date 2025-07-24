# webapp.py - Auto Parts Finder - EXCLUSIVO REPUESTOS DE AUTOS (UI Avanzada + Lógica Robusta)
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
# VALIDACIÓN DE RELEVANCIA Y BASE DE DATOS INTERNA
# =============================================================================
AUTO_PART_KEYWORDS = {
    'repuesto', 'parte', 'pieza', 'freno', 'pastilla', 'disco', 'motor', 'filtro', 'aceite',
    'aire', 'bujia', 'bobina', 'alternador', 'arranque', 'bateria', 'suspension', 'amortiguador',
    'faro', 'luz', 'calavera', 'stop', 'parachoque', 'defensa', 'espejo', 'radiador', 'bomba', 'agua', 'gasolina',
    'llanta', 'rin', 'rueda', 'sensor', 'inyector', 'correa', 'banda', 'cadena', 'tiempo', 'escape',
    'silenciador', 'catalizador', 'balero', 'rodamiento', 'eje', 'homocinetica', 'transmision', 'embrague', 'clutch',
    'termostato', 'valvula', 'marcha', 'maf', 'map', 'oxigeno', 'horquilla', 'rotula', 'part', 'replacement',
    'brake', 'pad', 'rotor', 'caliper', 'engine', 'filter', 'oil', 'air', 'spark', 'plug', 'coil', 'ignition',
    'alternator', 'starter', 'battery', 'suspension', 'shock', 'strut', 'absorber', 'headlight', 'taillight',
    'light', 'bulb', 'bumper', 'mirror', 'radiator', 'pump', 'water', 'fuel', 'tire', 'rim', 'wheel', 'sensor',
    'injector', 'belt', 'chain', 'timing', 'exhaust', 'muffler', 'converter', 'bearing', 'axle', 'cv-joint',
    'transmission', 'clutch', 'thermostat', 'gasket', 'valve', 'maf', 'map', 'oxygen', 'control-arm', 'ball-joint'
}

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
}
ALL_CAR_BRANDS = set(CAR_BRAND_EQUIVALENTS.keys())


# =============================================================================
# CLASES DE AUTENTICACIÓN Y BÚSQUEDA
# =============================================================================
class FirebaseAuth:
    # ... (El código de esta clase no cambia) ...
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
                    'source': urlparse(link).hostname.replace('www.', ''), 'link': link,
                    'is_oem': query_info['type'] == 'oem', 'compatibility_note': query_info.get('note', ''),
                    'rating': item.get('rating', 0), 'reviews': item.get('reviews', 0) # Añadido para UI
                })
        return products

    def search_auto_parts(self, text_query, target_brand=None):
        if not self.is_valid_auto_part_query(text_query):
            return "INVALID_QUERY"

        if not self.serpapi_key:
            return [{'title': f'Ejemplo: Filtro de Aceite para {target_brand or "Ford"}', 'price': '$15.50', 'price_numeric': 15.50, 'source': 'oemparts.com', 'link': '#', 'is_oem': True, 'compatibility_note': '', 'rating': 4.5, 'reviews': 120}]

        query_lower = text_query.lower()
        final_brand = target_brand or next((brand for brand in ALL_CAR_BRANDS if brand in query_lower), None)
        if not final_brand: return "INVALID_QUERY" # Si no hay marca, también es inválido
        
        all_products, seen_links = [], set()
        brand_data = CAR_BRAND_EQUIVALENTS.get(final_brand, {})
        
        # 1. Búsqueda OEM
        oem_sites = brand_data.get('oem_sites', [])
        if oem_sites:
            oem_query = f'"{text_query}" site:{" OR site:".join(oem_sites)}'
            data = self._make_api_request(oem_query)
            for p in self._process_results(data, {'type': 'oem', 'oem_sites': oem_sites}):
                if p['link'] not in seen_links:
                    all_products.append(p)
                    seen_links.add(p['link'])

        # 2. Búsqueda en Tiendas Aftermarket
        aftermarket_query = f'"{text_query}" site:{" OR site:".join(AUTO_PARTS_STORES)}'
        data = self._make_api_request(aftermarket_query)
        for p in self._process_results(data, {'type': 'aftermarket'}):
            if p['link'] not in seen_links:
                all_products.append(p)
                seen_links.add(p['link'])

        # 3. Búsqueda de Equivalentes
        if len(all_products) < 5:
            for comp_brand in brand_data.get('compatible_brands', []):
                comp_query_text = text_query.replace(final_brand, comp_brand)
                comp_query = f'"{comp_query_text}" site:{" OR site:".join(AUTO_PARTS_STORES)}'
                data = self._make_api_request(comp_query)
                for p in self._process_results(data, {'type': 'compatible', 'note': f'Compatible con {final_brand.upper()}'}):
                    if p['link'] not in seen_links:
                        all_products.append(p)
                        seen_links.add(p['link'])
        
        return sorted(all_products, key=lambda x: (not x['is_oem'], x['price_numeric']))[:10]

auto_parts_finder = AutoPartsFinder()


# ==============================================================================
# RUTAS Y TEMPLATES DE LA APLICACIÓN
# ==============================================================================

# --- Templates HTML/CSS/JS (UI Avanzada) ---
def render_page(title, content):
    # ... (El código de esta función no cambia) ...
    return f'''<!DOCTYPE html><html lang="es"><head><title>{title}</title><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, sans-serif; background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); min-height: 100vh; padding: 15px; }}
        .container {{ max-width: 750px; margin: 0 auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 8px 25px rgba(0,0,0,0.15); }}
        h1 {{ color: #1e3c72; text-align: center; margin-bottom: 8px; font-size: 1.8em; }}
        .subtitle {{ text-align: center; color: #666; margin-bottom: 25px; }}
        .search-bar input {{ width:100%; flex: 1; padding: 12px; margin: 8px 0; border: 2px solid #e1e5e9; border-radius: 6px; font-size: 16px; }}
        .search-bar button {{ width: auto; padding: 12px 20px; background: #1e3c72; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: 600; }}
        .tips {{ background: #e8f5e8; border: 1px solid #4caf50; padding: 15px; border-radius: 6px; margin-bottom: 15px; font-size: 14px; }}
        .error {{ background: #f8d7da; color: #721c24; padding: 12px; border-radius: 6px; margin: 12px 0; display: none; text-align:center; font-weight:bold; }}
        .loading {{ text-align: center; padding: 30px; display: none; }}
        .spinner {{ border: 3px solid #f3f3f3; border-top: 3px solid #1e3c72; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 15px; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        .user-info {{ background: #e3f2fd; padding: 12px; border-radius: 6px; margin-bottom: 15px; text-align: center; }}
        .brand-selector {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 15px 0; }}
        .brand-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; margin-top: 10px; }}
        .brand-btn {{ padding: 8px 12px; background: white; border: 2px solid #dee2e6; border-radius: 6px; cursor: pointer; text-align: center; font-size: 13px; font-weight: 600; }}
        .brand-btn:hover, .brand-btn.active {{ border-color: #1e3c72; background: #e3f2fd; color: #1e3c72; }}
    </style></head><body>{content}</body></html>'''

# --- Rutas ---
@app.route('/')
def index():
    return redirect(url_for('search_page')) if firebase_auth.is_user_logged_in() else redirect(url_for('auth_login_page'))
    
@app.route('/auth/login-page')
def auth_login_page():
    # ... Tu template de login aquí ...
    return "Login Page"

@app.route('/auth/login', methods=['POST'])
def auth_login():
    # ... Tu lógica de login aquí ...
    return redirect(url_for('search_page'))
    
@app.route('/search')
@login_required
def search_page():
    # ... (El código de esta función es largo y no cambia, se puede dejar como está en tu versión UI) ...
    brands = sorted(list(CAR_BRAND_EQUIVALENTS.keys()))
    content = f'''
    <div class="container">
        <h1>🔧 Buscar Repuestos de Autos</h1>
        <p class="subtitle">Búsqueda especializada por texto - Solo Estados Unidos</p>
        
        <form id="searchForm">
            <div class="search-bar">
                <input type="text" id="searchQuery" name="query" placeholder="Ej: brake pads 2018 ford f-150" required>
            </div>
            
            <div class="brand-selector">
                <h4 style="margin-bottom: 10px; color: #1e3c72;">🚗 Selecciona la marca (obligatorio si no está en el texto):</h4>
                <div class="brand-grid">
                    {''.join([f'<div class="brand-btn" data-brand="{b}">{b.title()}</div>' for b in brands])}
                </div>
                <input type="hidden" id="selectedBrand" name="target_brand" value="">
            </div>
            <button type="submit" style="width:100%;">🔍 Buscar</button>
        </form>
        
        <div id="loading" class="loading"><div class="spinner"></div><h3>Buscando repuestos...</h3></div>
        <div id="error" class="error"></div>
    </div>
    <script>
        document.querySelectorAll('.brand-btn').forEach(btn => {{
            btn.addEventListener('click', function() {{
                document.querySelectorAll('.brand-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                document.getElementById('selectedBrand').value = this.dataset.brand;
            }});
        }});
        document.getElementById('searchForm').addEventListener('submit', function(e) {{
            e.preventDefault();
            const query = document.getElementById('searchQuery').value.trim();
            if (!query) return;
            
            document.getElementById('loading').style.display = 'block';
            document.getElementById('error').style.display = 'none';
            
            const formData = new FormData(this);
            fetch('/api/search-auto-parts', {{ method: 'POST', body: formData }})
            .then(res => res.json())
            .then(data => {{
                document.getElementById('loading').style.display = 'none';
                if (data.success) {{
                    window.location.href = '/results';
                }} else {{
                    const errorDiv = document.getElementById('error');
                    errorDiv.textContent = data.error || 'Ocurrió un error.';
                    errorDiv.style.display = 'block';
                }}
            }}).catch(err => {{
                document.getElementById('loading').style.display = 'none';
                const errorDiv = document.getElementById('error');
                errorDiv.textContent = 'Error de conexión.';
                errorDiv.style.display = 'block';
            }});
        }});
    </script>
    '''
    return render_page('Busqueda de Repuestos', content)


@app.route('/api/search-auto-parts', methods=['POST'])
@login_required
def api_search_auto_parts():
    query = request.form.get('query')
    target_brand = request.form.get('target_brand')
    if not query:
        return jsonify({'success': False, 'error': 'La consulta no puede estar vacía.'}), 400

    # LÓGICA CLAVE: Llamar al buscador que ahora incluye la validación
    products = auto_parts_finder.search_auto_parts(query, target_brand)
    
    # MANEJO DE ERROR: Si el buscador devuelve el string de error, notificar a la UI
    if products == "INVALID_QUERY":
        return jsonify({'success': False, 'error': 'Sitio web exclusivamente para repuestos. Por favor, sé más específico.'}), 400

    # Si todo va bien, guardar resultados en sesión y notificar éxito
    session['last_search'] = {'query': query, 'products': products}
    return jsonify({'success': True})

@app.route('/results')
@login_required
def results_page():
    # ... (El código de esta función es largo y no cambia, se puede dejar como está en tu versión UI) ...
    search_data = session.get('last_search', {})
    query = search_data.get('query', 'Búsqueda')
    products = search_data.get('products', [])
    
    products_html = ""
    for p in products:
        badge = ''
        if p.get('is_oem'): badge = '<span class="badge badge-oem">OEM Original</span>'
        elif p.get('compatibility_note'): badge = '<span class="badge badge-comp">Compatible</span>'
        products_html += f'''
        <div class="product {'oem' if p.get('is_oem') else 'compatible' if p.get('compatibility_note') else ''}">
            {badge}
            <h3>{p.get("title")}</h3>
            <p><strong>Precio:</strong> {p.get("price")}</p>
            <p><strong>Vendido por:</strong> {p.get("source")}</p>
            {f'<p style="color:#856404;"><em>{p.get("compatibility_note")}</em></p>' if p.get("compatibility_note") else ''}
            <a href="{p.get("link")}" target="_blank">Ver Producto</a>
        </div>'''

    content = f'''
    <div style="max-width: 800px; margin: 0 auto;">
        <a href="{url_for('search_page')}">Nueva Búsqueda</a>
        <h1>Resultados para: "{html.escape(query)}"</h1>
        {products_html if products else "<p>No se encontraron resultados.</p>"}
    </div>'''
    return render_page(f'Resultados - {html.escape(query)}', content)

# --- Punto de Entrada ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
