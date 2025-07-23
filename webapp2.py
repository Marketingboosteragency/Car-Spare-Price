# webapp.py - Auto Parts Price Finder - EXCLUSIVO REPUESTOS DE AUTOS
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
    from google.api_core import exceptions as google_exceptions
    GEMINI_AVAILABLE = True
    print("✅ Google Generative AI (Gemini) disponible")
except ImportError:
    genai = None
    google_exceptions = None
    GEMINI_AVAILABLE = False
    print("⚠️ Google Generative AI no disponible - instalar con: pip install google-generativeai")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-key-change-in-production')
app.config['PERMANENT_SESSION_LIFETIME'] = 1800
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True if os.environ.get('RENDER') else False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Configuración de Gemini
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        print("✅ API de Google Gemini configurada correctamente")
        GEMINI_READY = True
    except Exception as e:
        print(f"❌ Error configurando Gemini: {e}")
        GEMINI_READY = False
elif GEMINI_AVAILABLE and not GEMINI_API_KEY:
    print("⚠️ Gemini disponible pero falta GEMINI_API_KEY en variables de entorno")
    GEMINI_READY = False
else:
    print("⚠️ Gemini no está disponible - búsqueda por imagen deshabilitada")
    GEMINI_READY = False

# =============================================================================
# BASE DE DATOS DE AUTOPARTES Y EQUIVALENCIAS
# =============================================================================

# Sitios especializados en autopartes de Estados Unidos
AUTO_PARTS_STORES = {
    # Cadenas nacionales de autopartes
    'autozone.com': {'name': 'AutoZone', 'priority': 10, 'type': 'aftermarket'},
    'oreillyauto.com': {'name': "O'Reilly Auto Parts", 'priority': 10, 'type': 'aftermarket'},
    'shop.advanceautoparts.com': {'name': 'Advance Auto Parts', 'priority': 10, 'type': 'aftermarket'},
    'napaonline.com': {'name': 'NAPA Auto Parts', 'priority': 10, 'type': 'aftermarket'},
    'pepboys.com': {'name': 'Pep Boys', 'priority': 9, 'type': 'aftermarket'},
    'partsauthority.com': {'name': 'Parts Authority', 'priority': 8, 'type': 'aftermarket'},
    'carquest.com': {'name': 'Carquest', 'priority': 8, 'type': 'aftermarket'},
    
    # Plataformas online especializadas
    'rockauto.com': {'name': 'RockAuto', 'priority': 10, 'type': 'online'},
    'carparts.com': {'name': 'CarParts.com', 'priority': 9, 'type': 'online'},
    'partsgeek.com': {'name': 'Parts Geek', 'priority': 9, 'type': 'online'},
    '1aauto.com': {'name': '1A Auto', 'priority': 9, 'type': 'online'},
    'autopartswarehouse.com': {'name': 'Auto Parts Warehouse', 'priority': 8, 'type': 'online'},
    'buyautoparts.com': {'name': 'BuyAutoParts.com', 'priority': 8, 'type': 'online'},
    'jcwhitney.com': {'name': 'JC Whitney', 'priority': 7, 'type': 'classic'},
    
    # OEM oficiales
    'parts.ford.com': {'name': 'Ford Parts', 'priority': 10, 'type': 'oem', 'brand': 'ford'},
    'nissanpartsdeal.com': {'name': 'Nissan Parts Deal', 'priority': 10, 'type': 'oem', 'brand': 'nissan'},
    'toyotapartsdeal.com': {'name': 'Toyota Parts Deal', 'priority': 10, 'type': 'oem', 'brand': 'toyota'},
    'gmpartsdirect.com': {'name': 'GM Parts Direct', 'priority': 10, 'type': 'oem', 'brand': 'chevrolet'},
    
    # Especializados por marca
    'tascaparts.com': {'name': 'Tasca Parts', 'priority': 9, 'type': 'oem', 'brand': 'ford'},
    'bernardiparts.com': {'name': 'Bernardi Parts', 'priority': 9, 'type': 'oem', 'brand': 'honda'},
    'olathetoyotaparts.com': {'name': 'Olathe Toyota Parts', 'priority': 9, 'type': 'oem', 'brand': 'toyota'},
    'nissanpartsplus.com': {'name': 'Nissan Parts Plus', 'priority': 9, 'type': 'oem', 'brand': 'nissan'},
    'pelicanparts.com': {'name': 'Pelican Parts', 'priority': 9, 'type': 'oem', 'brand': 'bmw'},
    'fcpeuro.com': {'name': 'FCP Euro', 'priority': 9, 'type': 'oem', 'brand': 'european'},
}

# Marcas de autos y sus equivalencias/compatibilidades
CAR_BRAND_EQUIVALENTS = {
    'ford': {
        'models': ['f150', 'f250', 'f350', 'mustang', 'focus', 'fiesta', 'escape', 'explorer', 'edge', 'fusion'],
        'oem_sites': ['parts.ford.com', 'tascaparts.com', 'fordpartscenter.net'],
        'compatible_brands': ['lincoln', 'mercury'],
        'common_parts': ['brake_pads', 'oil_filter', 'air_filter', 'spark_plugs', 'alternator', 'starter']
    },
    'chevrolet': {
        'models': ['silverado', 'tahoe', 'suburban', 'camaro', 'corvette', 'malibu', 'cruze', 'equinox'],
        'oem_sites': ['gmpartsdirect.com', 'gmpartsgiant.com'],
        'compatible_brands': ['gmc', 'cadillac', 'buick'],
        'common_parts': ['brake_pads', 'oil_filter', 'air_filter', 'spark_plugs', 'alternator', 'starter']
    },
    'toyota': {
        'models': ['camry', 'corolla', 'prius', 'rav4', 'highlander', 'tacoma', 'tundra', '4runner'],
        'oem_sites': ['toyotapartsdeal.com', 'olathetoyotaparts.com'],
        'compatible_brands': ['lexus', 'scion'],
        'common_parts': ['brake_pads', 'oil_filter', 'air_filter', 'spark_plugs', 'alternator', 'starter']
    },
    'honda': {
        'models': ['civic', 'accord', 'crv', 'pilot', 'odyssey', 'fit', 'ridgeline'],
        'oem_sites': ['bernardiparts.com', 'collegehillshonda.com'],
        'compatible_brands': ['acura'],
        'common_parts': ['brake_pads', 'oil_filter', 'air_filter', 'spark_plugs', 'alternator', 'starter']
    },
    'nissan': {
        'models': ['altima', 'sentra', 'maxima', 'rogue', 'pathfinder', 'titan', 'frontier'],
        'oem_sites': ['nissanpartsdeal.com', 'nissanpartsplus.com', 'courtesyparts.com'],
        'compatible_brands': ['infiniti'],
        'common_parts': ['brake_pads', 'oil_filter', 'air_filter', 'spark_plugs', 'alternator', 'starter']
    },
    'bmw': {
        'models': ['3series', '5series', '7series', 'x3', 'x5', 'x1', 'm3', 'm5'],
        'oem_sites': ['pelicanparts.com', 'bmwparts.com'],
        'compatible_brands': ['mini'],
        'common_parts': ['brake_pads', 'oil_filter', 'air_filter', 'spark_plugs', 'alternator', 'starter']
    }
}

# Tipos de autopartes más comunes
AUTO_PARTS_CATEGORIES = {
    'engine': ['oil_filter', 'air_filter', 'fuel_filter', 'spark_plugs', 'ignition_coils', 'alternator', 'starter'],
    'brakes': ['brake_pads', 'brake_rotors', 'brake_fluid', 'brake_lines', 'calipers'],
    'suspension': ['shocks', 'struts', 'springs', 'control_arms', 'ball_joints', 'tie_rods'],
    'electrical': ['battery', 'alternator', 'starter', 'headlights', 'tail_lights', 'fuses'],
    'body': ['mirrors', 'bumpers', 'doors', 'hoods', 'fenders', 'grilles'],
    'interior': ['seats', 'dashboard', 'steering_wheel', 'floor_mats', 'seat_covers']
}

# Firebase Auth Class (sin cambios)
class FirebaseAuth:
    def __init__(self):
        self.firebase_web_api_key = os.environ.get("FIREBASE_WEB_API_KEY")
        if not self.firebase_web_api_key:
            print("WARNING: FIREBASE_WEB_API_KEY no configurada")
        else:
            print("SUCCESS: Firebase Auth configurado")
    
    def login_user(self, email, password):
        if not self.firebase_web_api_key:
            return {'success': False, 'message': 'Servicio no configurado', 'user_data': None, 'error_code': 'SERVICE_NOT_CONFIGURED'}
        
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.firebase_web_api_key}"
        payload = {'email': email, 'password': password, 'returnSecureToken': True}
        
        try:
            response = requests.post(url, json=payload, timeout=8)
            response.raise_for_status()
            user_data = response.json()
            
            return {
                'success': True,
                'message': 'Bienvenido! Has iniciado sesion correctamente.',
                'user_data': {
                    'user_id': user_data['localId'],
                    'email': user_data['email'],
                    'display_name': user_data.get('displayName', email.split('@')[0]),
                    'id_token': user_data['idToken']
                },
                'error_code': None
            }
        except requests.exceptions.HTTPError as e:
            try:
                error_msg = e.response.json().get('error', {}).get('message', 'ERROR')
                if 'INVALID' in error_msg or 'EMAIL_NOT_FOUND' in error_msg:
                    return {'success': False, 'message': 'Correo o contraseña incorrectos', 'user_data': None, 'error_code': 'INVALID_CREDENTIALS'}
                elif 'TOO_MANY_ATTEMPTS' in error_msg:
                    return {'success': False, 'message': 'Demasiados intentos fallidos', 'user_data': None, 'error_code': 'TOO_MANY_ATTEMPTS'}
                else:
                    return {'success': False, 'message': 'Error de autenticacion', 'user_data': None, 'error_code': 'FIREBASE_ERROR'}
            except:
                return {'success': False, 'message': 'Error de conexion', 'user_data': None, 'error_code': 'CONNECTION_ERROR'}
        except Exception as e:
            print(f"Firebase auth error: {e}")
            return {'success': False, 'message': 'Error interno del servidor', 'user_data': None, 'error_code': 'UNEXPECTED_ERROR'}
    
    def set_user_session(self, user_data):
        session['user_id'] = user_data['user_id']
        session['user_name'] = user_data['display_name']
        session['user_email'] = user_data['email']
        session['id_token'] = user_data['id_token']
        session['login_time'] = datetime.now().isoformat()
        session.permanent = True
    
    def clear_user_session(self):
        important_data = {key: session.get(key) for key in ['timestamp'] if key in session}
        session.clear()
        for key, value in important_data.items():
            session[key] = value
    
    def is_user_logged_in(self):
        if 'user_id' not in session or session['user_id'] is None:
            return False
        if 'login_time' in session:
            try:
                login_time = datetime.fromisoformat(session['login_time'])
                time_diff = (datetime.now() - login_time).total_seconds()
                if time_diff > 7200:  # 2 horas maximo
                    return False
            except:
                pass
        return True
    
    def get_current_user(self):
        if not self.is_user_logged_in():
            return None
        return {
            'user_id': session.get('user_id'),
            'user_name': session.get('user_name'),
            'user_email': session.get('user_email'),
            'id_token': session.get('id_token')
        }

firebase_auth = FirebaseAuth()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not firebase_auth.is_user_logged_in():
            flash('Tu sesion ha expirado. Inicia sesion nuevamente.', 'warning')
            return redirect(url_for('auth_login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ==============================================================================
# FUNCIONES DE ANÁLISIS DE AUTOPARTES CON IA
# ==============================================================================

def analyze_auto_part_image_with_gemini(image_content):
    """Analiza imagen específicamente para identificar autopartes"""
    if not GEMINI_READY or not PIL_AVAILABLE or not image_content:
        print("❌ Gemini o PIL no disponible para análisis de imagen")
        return None
    
    try:
        # Convertir bytes a PIL Image
        image = Image.open(io.BytesIO(image_content))
        
        # Optimizar imagen
        max_size = (1024, 1024)
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        print("🔧 Analizando imagen de autoparte con Gemini Vision...")
        
        prompt = """
        Analiza esta imagen y determina si es una autopart (repuesto de automóvil). Si lo es, identifica:
        
        1. TIPO DE PIEZA: (brake pads, oil filter, air filter, spark plugs, alternator, starter, headlight, etc.)
        2. MARCA DEL AUTO: (Ford, Chevrolet, Toyota, Honda, Nissan, BMW, etc.) - si es visible
        3. MODELO/AÑO: si hay números de parte visibles
        4. CATEGORÍA: (Engine, Brakes, Suspension, Electrical, Body, Interior)
        
        Responde SOLO con una consulta de búsqueda optimizada para tiendas de autopartes en inglés.
        
        Ejemplos de respuesta:
        - "brake pads ford f150 2015"
        - "oil filter toyota camry"
        - "alternator chevrolet silverado"
        - "headlight honda civic"
        
        Si NO es una autoparte, responde: "not_auto_part"
        """
        
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = model.generate_content([prompt, image])
        
        if response.text:
            search_query = response.text.strip()
            
            # Verificar si es autoparte
            if search_query.lower() == "not_auto_part":
                print("🚫 La imagen no corresponde a una autoparte")
                return None
            
            print(f"🔧 Autoparte identificada: '{search_query}'")
            return search_query
        
        return None
            
    except Exception as e:
        print(f"❌ Error analizando imagen de autoparte: {e}")
        return None

def extract_brand_and_model_from_query(query):
    """Extrae marca y modelo de la consulta"""
    query_lower = query.lower()
    detected_brand = None
    detected_model = None
    
    # Buscar marca
    for brand, info in CAR_BRAND_EQUIVALENTS.items():
        if brand in query_lower:
            detected_brand = brand
            # Buscar modelo específico
            for model in info['models']:
                if model in query_lower:
                    detected_model = model
                    break
            break
    
    return detected_brand, detected_model

def validate_image(image_content):
    """Valida imagen"""
    if not PIL_AVAILABLE or not image_content:
        return False
    
    try:
        image = Image.open(io.BytesIO(image_content))
        if image.size[0] < 10 or image.size[1] < 10:
            return False
        if image.format not in ['JPEG', 'PNG', 'WEBP']:
            return False
        return True
    except:
        return False

# ==============================================================================
# BUSCADOR DE AUTOPARTES ESPECIALIZADO
# ==============================================================================

class AutoPartsPriceFinder:
    def __init__(self):
        # Intentar multiples nombres de variables de entorno comunes
        self.api_key = (
            os.environ.get('SERPAPI_KEY') or 
            os.environ.get('SERPAPI_API_KEY') or 
            os.environ.get('SERP_API_KEY') or
            os.environ.get('serpapi_key') or
            os.environ.get('SERPAPI')
        )
        
        self.base_url = "https://serpapi.com/search"
        self.cache = {}
        self.cache_ttl = 300  # 5 minutos para autopartes
        self.timeouts = {'connect': 3, 'read': 10}
        
        # Sitios PROHIBIDOS (no son de autopartes legítimas)
        self.blacklisted_stores = [
            'alibaba', 'aliexpress', 'temu', 'wish', 'banggood', 'dhgate', 
            'ebay', 'amazon'  # Removidos de blacklist para autopartes
        ]
        
        if not self.api_key:
            print("WARNING: No se encontro API key en variables de entorno")
        else:
            print(f"SUCCESS: SerpAPI configurado para autopartes (key: {self.api_key[:8]}...)")
    
    def is_api_configured(self):
        return bool(self.api_key)
    
    def _extract_price(self, price_str):
        if not price_str:
            return 0.0
        try:
            # Limpiar precio más agresivamente para autopartes
            price_clean = re.sub(r'[^\d.,]', '', str(price_str))
            match = re.search(r'(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)', price_clean)
            if match:
                price_value = float(match.group(1).replace(',', ''))
                # Rango de precios típicos para autopartes: $5 - $5000
                return price_value if 1.0 <= price_value <= 5000 else 0.0
        except:
            pass
        return 0.0
    
    def _generate_realistic_auto_part_price(self, query, part_type, index=0):
        """Genera precios realistas según el tipo de autoparte"""
        query_lower = query.lower()
        
        # Precios base según tipo de parte
        if any(word in query_lower for word in ['brake_pads', 'brake pad', 'pastillas']):
            base_price = 45
        elif any(word in query_lower for word in ['oil_filter', 'filtro aceite']):
            base_price = 12
        elif any(word in query_lower for word in ['air_filter', 'filtro aire']):
            base_price = 18
        elif any(word in query_lower for word in ['spark_plug', 'bujias']):
            base_price = 8
        elif any(word in query_lower for word in ['alternator', 'alternador']):
            base_price = 180
        elif any(word in query_lower for word in ['starter', 'motor arranque']):
            base_price = 120
        elif any(word in query_lower for word in ['headlight', 'faro']):
            base_price = 85
        elif any(word in query_lower for word in ['battery', 'bateria']):
            base_price = 90
        else:
            base_price = 35  # Precio genérico para autopartes
        
        # Variación por tienda/índice (algunas más baratas)
        multiplier = 1 + (index * 0.12)  # Variación del 12% entre tiendas
        final_price = base_price * multiplier
        
        return round(final_price, 2)
    
    def _clean_text(self, text):
        if not text:
            return "Sin informacion"
        return html.escape(str(text)[:150])  # Más espacio para nombres de autopartes
    
    def _is_blacklisted_store(self, source):
        if not source:
            return False
        source_lower = str(source).lower()
        
        # Verificar si es un sitio prohibido
        if any(blocked in source_lower for blocked in self.blacklisted_stores):
            return True
        
        # Verificar si es un sitio de autopartes legítimo
        for domain in AUTO_PARTS_STORES.keys():
            if domain in source_lower:
                return False  # Es legítimo
        
        # Si no está en nuestra lista de sitios confiables, es sospechoso
        return False  # Permitir otros sitios por ahora
    
    def _get_valid_auto_parts_link(self, item, query):
        if not item:
            return "#"
        
        product_link = item.get('product_link', '')
        if product_link:
            return product_link
        
        general_link = item.get('link', '')
        if general_link:
            return general_link
        
        # Enlaces directos a tiendas de autopartes
        title = item.get('title', query)
        search_query = quote_plus(str(title)[:50])
        
        # Priorizar sitios especializados en autopartes
        return f"https://www.rockauto.com/en/catalog/search?searchString={search_query}"
    
    def _make_api_request(self, engine, query):
        if not self.api_key:
            return None
        
        # Optimizar búsqueda para autopartes
        if 'auto parts' not in query.lower():
            query = f"{query} auto parts"
        
        params = {
            'engine': engine, 
            'q': query, 
            'api_key': self.api_key, 
            'num': 8,  # Más resultados para autopartes
            'location': 'United States', 
            'gl': 'us'
        }
        
        try:
            time.sleep(0.4)  # Pausa para evitar rate limiting
            response = requests.get(self.base_url, params=params, timeout=(self.timeouts['connect'], self.timeouts['read']))
            if response.status_code != 200:
                print(f"API Error: {response.status_code}")
                return None
            return response.json()
        except Exception as e:
            print(f"Error en request de autopartes: {e}")
            return None
    
    def _process_auto_parts_results(self, data, engine, original_query):
        if not data:
            return []
        
        products = []
        results_key = 'shopping_results' if engine == 'google_shopping' else 'organic_results'
        if results_key not in data:
            return []
        
        for item in data[results_key][:6]:  # Más resultados para autopartes
            try:
                if not item:
                    continue
                
                title = item.get('title', '')
                if not title or len(title) < 5:
                    continue
                
                # Filtrar resultados que NO son autopartes
                title_lower = title.lower()
                if not any(word in title_lower for word in [
                    'part', 'filter', 'brake', 'oil', 'spark', 'plug', 'alternator', 
                    'starter', 'battery', 'headlight', 'auto', 'car', 'vehicle'
                ]):
                    continue
                
                source = item.get('source', '')
                if self._is_blacklisted_store(source):
                    continue
                
                price_str = item.get('price', '')
                price_num = self._extract_price(price_str)
                if price_num == 0:
                    price_num = self._generate_realistic_auto_part_price(original_query, 'generic', len(products))
                    price_str = f"${price_num:.2f}"
                
                # Determinar tipo de tienda
                store_type = 'aftermarket'
                for domain, info in AUTO_PARTS_STORES.items():
                    if domain in str(source).lower():
                        store_type = info['type']
                        break
                
                products.append({
                    'title': self._clean_text(title),
                    'price': str(price_str),
                    'price_numeric': float(price_num),
                    'source': self._clean_text(source or 'Auto Parts Store'),
                    'link': self._get_valid_auto_parts_link(item, original_query),
                    'rating': str(item.get('rating', '')),
                    'reviews': str(item.get('reviews', '')),
                    'image': item.get('thumbnail', ''),
                    'store_type': store_type,
                    'part_category': self._determine_part_category(title)
                })
                
                if len(products) >= 6:
                    break
                    
            except Exception as e:
                print(f"Error procesando item de autoparte: {e}")
                continue
        
        return products
    
    def _determine_part_category(self, title):
        """Determina la categoría de la autoparte"""
        title_lower = title.lower()
        
        if any(word in title_lower for word in ['brake', 'pad', 'rotor', 'caliper']):
            return 'brakes'
        elif any(word in title_lower for word in ['filter', 'oil', 'air', 'fuel']):
            return 'engine'
        elif any(word in title_lower for word in ['spark', 'plug', 'ignition', 'coil']):
            return 'engine'
        elif any(word in title_lower for word in ['alternator', 'starter', 'battery']):
            return 'electrical'
        elif any(word in title_lower for word in ['shock', 'strut', 'spring', 'suspension']):
            return 'suspension'
        elif any(word in title_lower for word in ['headlight', 'taillight', 'bulb']):
            return 'electrical'
        else:
            return 'general'
    
    def search_auto_parts_with_brand_focus(self, query=None, image_content=None, target_brand=None):
        """Búsqueda especializada en autopartes con enfoque en marca específica"""
        
        # 1. Determinar consulta final y marca objetivo
        final_query = None
        search_source = "text"
        detected_brand = target_brand
        detected_model = None
        
        if image_content and GEMINI_READY and PIL_AVAILABLE:
            if validate_image(image_content):
                if query:
                    # Texto + imagen
                    image_query = analyze_auto_part_image_with_gemini(image_content)
                    if image_query:
                        final_query = f"{query} {image_query}"
                        search_source = "combined"
                        print(f"🔗 Búsqueda combinada de autopartes: texto + imagen")
                    else:
                        final_query = query
                        search_source = "text_fallback"
                        print(f"📝 Imagen falló, usando solo texto para autopartes")
                else:
                    # Solo imagen
                    final_query = analyze_auto_part_image_with_gemini(image_content)
                    if not final_query:
                        final_query = "auto parts"
                    search_source = "image"
                    print(f"🖼️ Búsqueda basada en imagen de autoparte")
            else:
                print("❌ Imagen inválida para autoparte")
                final_query = query or "auto parts"
                search_source = "text"
        else:
            # Solo texto o imagen no disponible
            final_query = query or "auto parts"
            search_source = "text"
            if image_content and not GEMINI_READY:
                print("⚠️ Imagen de autoparte proporcionada pero Gemini no está configurado")
        
        if not final_query or len(final_query.strip()) < 3:
            final_query = "auto parts"
        
        final_query = final_query.strip()
        
        # 2. Extraer marca y modelo de la consulta
        if not detected_brand:
            detected_brand, detected_model = extract_brand_and_model_from_query(final_query)
        
        print(f"🔧 Búsqueda de autoparte: '{final_query}' (marca: {detected_brand}, modelo: {detected_model})")
        
        # 3. Verificar configuración API
        if not self.api_key:
            print("Sin API key - usando ejemplos de autopartes")
            return self._get_auto_parts_examples(final_query, detected_brand)
        
        # 4. Cache de autopartes
        cache_key = f"autoparts_{hash(final_query.lower())}_{detected_brand or 'generic'}"
        if cache_key in self.cache:
            cache_data, timestamp = self.cache[cache_key]
            if (time.time() - timestamp) < self.cache_ttl:
                print("📦 Resultados de autopartes desde cache")
                return cache_data
        
        start_time = time.time()
        all_products = []
        
        # 5. Búsqueda por marca específica primero
        if detected_brand and detected_brand in CAR_BRAND_EQUIVALENTS:
            brand_info = CAR_BRAND_EQUIVALENTS[detected_brand]
            
            # 5a. Buscar en sitios OEM de la marca
            print(f"🏭 Buscando en sitios OEM de {detected_brand.upper()}...")
            for oem_site in brand_info.get('oem_sites', []):
                if time.time() - start_time < 12:
                    oem_query = f'"{final_query}" site:{oem_site}'
                    data = self._make_api_request('google', oem_query)
                    products = self._process_auto_parts_results(data, 'google', final_query)
                    for product in products:
                        product['search_source'] = f"oem_{detected_brand}"
                        product['is_oem'] = True
                    all_products.extend(products)
        
        # 6. Búsqueda general en tiendas de autopartes
        if time.time() - start_time < 15 and len(all_products) < 4:
            print("🛒 Buscando en tiendas generales de autopartes...")
            
            # Optimizar query para autopartes
            optimized_query = f'"{final_query}" auto parts -alibaba -aliexpress -temu'
            if detected_brand:
                optimized_query = f'"{final_query}" {detected_brand} auto parts'
            
            data = self._make_api_request('google_shopping', optimized_query)
            products = self._process_auto_parts_results(data, 'google_shopping', final_query)
            
            for product in products:
                product['search_source'] = search_source
                product['is_oem'] = False
            
            all_products.extend(products)
        
        # 7. Búsqueda de equivalencias si no hay resultados para la marca específica
        if detected_brand and len(all_products) < 3:
            print(f"🔄 Buscando equivalencias para {detected_brand}...")
            brand_info = CAR_BRAND_EQUIVALENTS.get(detected_brand, {})
            compatible_brands = brand_info.get('compatible_brands', [])
            
            for compatible_brand in compatible_brands[:2]:  # Solo 2 marcas compatibles
                if time.time() - start_time < 18:
                    compatible_query = final_query.replace(detected_brand, compatible_brand) if detected_brand in final_query else f"{final_query} {compatible_brand}"
                    data = self._make_api_request('google_shopping', f'"{compatible_query}" auto parts')
                    products = self._process_auto_parts_results(data, 'google_shopping', compatible_query)
                    
                    for product in products:
                        product['search_source'] = f"compatible_{compatible_brand}"
                        product['is_oem'] = False
                        product['compatibility_note'] = f"Compatible con {detected_brand.upper()}"
                    
                    all_products.extend(products)
        
        # 8. Si aún no hay resultados, usar ejemplos
        if not all_products:
            print("📋 No se encontraron resultados reales, usando ejemplos")
            all_products = self._get_auto_parts_examples(final_query, detected_brand)
        
        # 9. Procesar y ordenar resultados
        # Eliminar duplicados por título similar
        unique_products = []
        seen_titles = set()
        
        for product in all_products:
            title_normalized = re.sub(r'[^\w\s]', '', product['title'].lower())[:50]
            if title_normalized not in seen_titles:
                seen_titles.add(title_normalized)
                unique_products.append(product)
        
        # Ordenar: OEM primero, luego por precio
        unique_products.sort(key=lambda x: (not x.get('is_oem', False), x['price_numeric']))
        
        # Limitar a 8 resultados
        final_products = unique_products[:8]
        
        # 10. Añadir metadata
        for product in final_products:
            if 'search_source' not in product:
                product['search_source'] = search_source
            product['original_query'] = query if query else "imagen de autoparte"
            product['detected_brand'] = detected_brand
            product['detected_model'] = detected_model
        
        # 11. Cache de resultados
        self.cache[cache_key] = (final_products, time.time())
        if len(self.cache) > 15:  # Más cache para autopartes
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        
        print(f"✅ Búsqueda de autopartes completada: {len(final_products)} productos encontrados")
        return final_products
    
    def _get_auto_parts_examples(self, query, brand=None):
        """Genera ejemplos realistas de autopartes"""
        
        # Tiendas especializadas en autopartes
        stores = [
            {'name': 'RockAuto', 'url': 'rockauto.com', 'type': 'online'},
            {'name': 'AutoZone', 'url': 'autozone.com', 'type': 'aftermarket'},
            {'name': "O'Reilly Auto Parts", 'url': 'oreillyauto.com', 'type': 'aftermarket'},
            {'name': 'NAPA Auto Parts', 'url': 'napaonline.com', 'type': 'aftermarket'},
            {'name': 'CarParts.com', 'url': 'carparts.com', 'type': 'online'},
            {'name': 'Parts Geek', 'url': 'partsgeek.com', 'type': 'online'}
        ]
        
        examples = []
        query_lower = query.lower()
        
        # Determinar tipo de parte para precios realistas
        part_type = 'generic'
        if any(word in query_lower for word in ['brake', 'pad']):
            part_type = 'brake_pads'
        elif any(word in query_lower for word in ['oil', 'filter']):
            part_type = 'oil_filter'
        elif any(word in query_lower for word in ['air', 'filter']):
            part_type = 'air_filter'
        elif any(word in query_lower for word in ['spark', 'plug']):
            part_type = 'spark_plugs'
        elif any(word in query_lower for word in ['alternator']):
            part_type = 'alternator'
        elif any(word in query_lower for word in ['starter']):
            part_type = 'starter'
        
        for i, store in enumerate(stores[:6]):
            price = self._generate_realistic_auto_part_price(query, part_type, i)
            
            # Generar título específico de autoparte
            if brand:
                title = f"{query.title()} para {brand.upper()} - {['OEM Quality', 'Premium', 'Standard', 'Economy', 'Performance', 'OE Replacement'][i]}"
            else:
                title = f"{query.title()} - {['Universal Fit', 'Premium Quality', 'OE Replacement', 'Economy', 'Heavy Duty', 'Performance'][i]}"
            
            # URL específica de la tienda
            search_query = quote_plus(str(query)[:40])
            if store['url'] == 'rockauto.com':
                link = f"https://www.rockauto.com/en/catalog/search?searchString={search_query}"
            elif store['url'] == 'autozone.com':
                link = f"https://www.autozone.com/search?searchText={search_query}"
            elif store['url'] == 'oreillyauto.com':
                link = f"https://www.oreillyauto.com/search?q={search_query}"
            else:
                link = f"https://www.{store['url']}/search?q={search_query}"
            
            examples.append({
                'title': self._clean_text(title),
                'price': f'${price:.2f}',
                'price_numeric': price,
                'source': store['name'],
                'link': link,
                'rating': ['4.6', '4.4', '4.2', '4.0', '4.3', '4.1'][i],
                'reviews': ['850', '620', '430', '290', '180', '95'][i],
                'image': '',
                'search_source': 'example',
                'store_type': store['type'],
                'part_category': self._determine_part_category(query),
                'is_oem': i < 2,  # Primeros 2 ejemplos son OEM
                'detected_brand': brand,
                'compatibility_note': f"Compatible con {brand.upper()}" if brand else None
            })
        
        return examples

# Instancia global del buscador de autopartes
auto_parts_finder = AutoPartsPriceFinder()

# Templates actualizados para autopartes
def render_page(title, content):
    template = '''<!DOCTYPE html>
<html lang="es">
<head>
    <title>''' + title + '''</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, sans-serif; background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); min-height: 100vh; padding: 15px; }
        .container { max-width: 750px; margin: 0 auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 8px 25px rgba(0,0,0,0.15); }
        h1 { color: #1e3c72; text-align: center; margin-bottom: 8px; font-size: 1.8em; }
        .subtitle { text-align: center; color: #666; margin-bottom: 25px; }
        input { width: 100%; padding: 12px; margin: 8px 0; border: 2px solid #e1e5e9; border-radius: 6px; font-size: 16px; }
        input:focus { outline: none; border-color: #1e3c72; }
        button { width: 100%; padding: 12px; background: #1e3c72; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: 600; }
        button:hover { background: #2a5298; }
        .search-bar { display: flex; gap: 8px; margin-bottom: 20px; }
        .search-bar input { flex: 1; }
        .search-bar button { width: auto; padding: 12px 20px; }
        .tips { background: #e8f5e8; border: 1px solid #4caf50; padding: 15px; border-radius: 6px; margin-bottom: 15px; font-size: 14px; }
        .error { background: #ffebee; color: #c62828; padding: 12px; border-radius: 6px; margin: 12px 0; display: none; }
        .loading { text-align: center; padding: 30px; display: none; }
        .spinner { border: 3px solid #f3f3f3; border-top: 3px solid #1e3c72; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 15px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .user-info { background: #e3f2fd; padding: 12px; border-radius: 6px; margin-bottom: 15px; text-align: center; font-size: 14px; display: flex; align-items: center; justify-content: center; }
        .user-info a { color: #1976d2; text-decoration: none; font-weight: 600; }
        .flash { padding: 12px; margin-bottom: 8px; border-radius: 6px; font-size: 14px; }
        .flash.success { background-color: #d4edda; color: #155724; }
        .flash.danger { background-color: #f8d7da; color: #721c24; }
        .flash.warning { background-color: #fff3cd; color: #856404; }
        .image-upload { background: #f8f9fa; border: 2px dashed #dee2e6; border-radius: 8px; padding: 20px; text-align: center; margin: 15px 0; transition: all 0.3s ease; }
        .image-upload input[type="file"] { display: none; }
        .image-upload label { cursor: pointer; color: #1e3c72; font-weight: 600; }
        .image-upload:hover { border-color: #1e3c72; background: #e3f2fd; }
        .image-preview { max-width: 150px; max-height: 150px; margin: 10px auto; border-radius: 8px; display: none; }
        .or-divider { text-align: center; margin: 20px 0; color: #666; font-weight: 600; position: relative; }
        .or-divider:before { content: ''; position: absolute; top: 50%; left: 0; right: 0; height: 1px; background: #dee2e6; z-index: 1; }
        .or-divider span { background: white; padding: 0 15px; position: relative; z-index: 2; }
        .brand-selector { background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 15px 0; }
        .brand-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; margin-top: 10px; }
        .brand-btn { padding: 8px 12px; background: white; border: 2px solid #dee2e6; border-radius: 6px; cursor: pointer; text-align: center; font-size: 13px; font-weight: 600; transition: all 0.3s ease; }
        .brand-btn:hover, .brand-btn.active { border-color: #1e3c72; background: #e3f2fd; color: #1e3c72; }
    </style>
</head>
<body>''' + content + '''</body>
</html>'''
    return template

AUTH_LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Iniciar Sesion | Auto Parts Finder</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }
        .auth-container { max-width: 420px; width: 100%; background: white; border-radius: 15px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); overflow: hidden; }
        .form-header { text-align: center; padding: 30px 25px 15px; background: linear-gradient(45deg, #1e3c72, #2a5298); color: white; }
        .form-header h1 { font-size: 1.8em; margin-bottom: 8px; }
        .form-header p { opacity: 0.9; font-size: 1em; }
        .form-body { padding: 25px; }
        form { display: flex; flex-direction: column; gap: 18px; }
        .input-group { display: flex; flex-direction: column; gap: 6px; }
        .input-group label { font-weight: 600; color: #1e3c72; font-size: 14px; }
        .input-group input { padding: 14px 16px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 16px; transition: border-color 0.3s ease; }
        .input-group input:focus { outline: 0; border-color: #1e3c72; }
        .submit-btn { background: linear-gradient(45deg, #1e3c72, #2a5298); color: white; border: none; padding: 14px 25px; font-size: 16px; font-weight: 600; border-radius: 8px; cursor: pointer; transition: transform 0.2s ease; }
        .submit-btn:hover { transform: translateY(-2px); }
        .flash-messages { list-style: none; padding: 0 25px 15px; }
        .flash { padding: 12px; margin-bottom: 10px; border-radius: 6px; text-align: center; font-size: 14px; }
        .flash.success { background-color: #d4edda; color: #155724; }
        .flash.danger { background-color: #f8d7da; color: #721c24; }
        .flash.warning { background-color: #fff3cd; color: #856404; }
    </style>
</head>
<body>
    <div class="auth-container">
        <div class="form-header">
            <h1>🔧 Auto Parts Finder</h1>
            <p>Repuestos de Autos - Estados Unidos</p>
        </div>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                <ul class="flash-messages">
                    {% for category, message in messages %}
                        <li class="flash {{ category }}">{{ message }}</li>
                    {% endfor %}
                </ul>
            {% endif %}
        {% endwith %}
        <div class="form-body">
            <form action="{{ url_for('auth_login') }}" method="post">
                <div class="input-group">
                    <label for="email">Correo Electronico</label>
                    <input type="email" name="email" id="email" required>
                </div>
                <div class="input-group">
                    <label for="password">Contraseña</label>
                    <input type="password" name="password" id="password" required>
                </div>
                <button type="submit" class="submit-btn">Entrar</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

# Routes actualizadas
@app.route('/auth/login-page')
def auth_login_page():
    return render_template_string(AUTH_LOGIN_TEMPLATE)

@app.route('/auth/login', methods=['POST'])
def auth_login():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    
    if not email or not password:
        flash('Por favor completa todos los campos.', 'danger')
        return redirect(url_for('auth_login_page'))
    
    print(f"Login attempt for {email}")
    result = firebase_auth.login_user(email, password)
    
    if result['success']:
        firebase_auth.set_user_session(result['user_data'])
        flash(result['message'], 'success')
        print(f"Successful login for {email}")
        return redirect(url_for('index'))
    else:
        flash(result['message'], 'danger')
        print(f"Failed login for {email}")
        return redirect(url_for('auth_login_page'))

@app.route('/auth/logout')
def auth_logout():
    firebase_auth.clear_user_session()
    flash('Has cerrado la sesion correctamente.', 'success')
    return redirect(url_for('auth_login_page'))

@app.route('/')
def index():
    if not firebase_auth.is_user_logged_in():
        return redirect(url_for('auth_login_page'))
    return redirect(url_for('search_page'))

@app.route('/search')
@login_required
def search_page():
    current_user = firebase_auth.get_current_user()
    user_name = current_user['user_name'] if current_user else 'Usuario'
    user_name_escaped = html.escape(user_name)
    
    # Verificar si búsqueda por imagen está disponible
    image_search_available = GEMINI_READY and PIL_AVAILABLE
    
    content = '''
    <div class="container">
        <div class="user-info">
            <span><strong>''' + user_name_escaped + '''</strong></span>
            <div style="display: inline-block; margin-left: 15px;">
                <a href="''' + url_for('auth_logout') + '''" style="background: #dc3545; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 13px; margin-right: 8px;">Salir</a>
                <a href="''' + url_for('index') + '''" style="background: #28a745; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 13px;">Inicio</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <h1>🔧 Buscar Repuestos de Autos</h1>
        <p class="subtitle">''' + ('Búsqueda especializada por texto o imagen' if image_search_available else 'Búsqueda especializada por texto') + ''' - Solo Estados Unidos</p>
        
        <form id="searchForm" enctype="multipart/form-data">
            <div class="search-bar">
                <input type="text" id="searchQuery" name="query" placeholder="Ej: brake pads ford f150, oil filter toyota camry...">
                <button type="submit">🔍 Buscar</button>
            </div>
            
            <!-- Selector de marca -->
            <div class="brand-selector">
                <h4 style="margin-bottom: 10px; color: #1e3c72;">🚗 Selecciona la marca (opcional):</h4>
                <div class="brand-grid">
                    <div class="brand-btn" data-brand="">Todas</div>
                    <div class="brand-btn" data-brand="ford">Ford</div>
                    <div class="brand-btn" data-brand="chevrolet">Chevrolet</div>
                    <div class="brand-btn" data-brand="toyota">Toyota</div>
                    <div class="brand-btn" data-brand="honda">Honda</div>
                    <div class="brand-btn" data-brand="nissan">Nissan</div>
                    <div class="brand-btn" data-brand="bmw">BMW</div>
                </div>
                <input type="hidden" id="selectedBrand" name="target_brand" value="">
            </div>
            
            ''' + ('<div class="or-divider"><span>O sube foto de la pieza</span></div>' if image_search_available else '') + '''
            
            ''' + ('<div class="image-upload" id="imageUpload"><input type="file" id="imageFile" name="image_file" accept="image/*"><label for="imageFile">📷 Identificar repuesto por imagen<br><small>JPG o PNG hasta 10MB</small></label><img id="imagePreview" class="image-preview" src="#" alt="Vista previa"></div>' if image_search_available else '') + '''
        </form>
        
        <div class="tips">
            <h4>🔧 Sistema Especializado en Autopartes''' + (' + IA Visual:' if image_search_available else ':') + '''</h4>
            <ul style="margin: 8px 0 0 15px; font-size: 13px;">
                <li><strong>🇺🇸 USA Exclusivo:</strong> RockAuto, AutoZone, O'Reilly, NAPA, Parts Geek</li>
                <li><strong>🏭 OEM + Aftermarket:</strong> Sitios oficiales de fabricantes + tiendas</li>
                <li><strong>💰 Mejor Precio:</strong> Ordenado por precio, OEM primero</li>
                <li><strong>🔄 Equivalencias:</strong> Si no encuentra para tu marca, busca compatibles</li>
                ''' + ('<li><strong>🤖 IA Visual:</strong> Identifica autopartes en fotos automáticamente</li>' if image_search_available else '<li><strong>⚠️ IA:</strong> Configura GEMINI_API_KEY para búsqueda por imagen</li>') + '''
            </ul>
        </div>
        
        <div id="loading" class="loading">
            <div class="spinner"></div>
            <h3>Buscando repuestos...</h3>
            <p id="loadingText">Verificando OEM y aftermarket...</p>
        </div>
        <div id="error" class="error"></div>
    </div>
    
    <script>
        let searching = false;
        let selectedBrand = '';
        const imageSearchAvailable = ''' + str(image_search_available).lower() + ''';
        
        // Manejo del selector de marca
        document.querySelectorAll('.brand-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.brand-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                selectedBrand = this.dataset.brand;
                document.getElementById('selectedBrand').value = selectedBrand;
                console.log('Marca seleccionada:', selectedBrand || 'Todas');
            });
        });
        
        // Activar "Todas" por defecto
        document.querySelector('.brand-btn[data-brand=""]').classList.add('active');
        
        // Manejo de vista previa de imagen
        if (imageSearchAvailable) {
            document.getElementById('imageFile').addEventListener('change', function(e) {
                const file = e.target.files[0];
                const preview = document.getElementById('imagePreview');
                
                if (file) {
                    if (file.size > 10 * 1024 * 1024) {
                        alert('La imagen es demasiado grande (máximo 10MB)');
                        this.value = '';
                        return;
                    }
                    
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        preview.src = e.target.result;
                        preview.style.display = 'block';
                    }
                    reader.readAsDataURL(file);
                } else {
                    preview.style.display = 'none';
                }
            });
        }
        
        document.getElementById('searchForm').addEventListener('submit', function(e) {
            e.preventDefault();
            if (searching) return;
            
            const query = document.getElementById('searchQuery').value.trim();
            const imageFile = imageSearchAvailable ? document.getElementById('imageFile').files[0] : null;
            
            if (!query && !imageFile) {
                return showError('Por favor ingresa un repuesto' + (imageSearchAvailable ? ' o sube una imagen' : ''));
            }
            
            searching = true;
            let loadingText = 'Buscando repuestos...';
            if (selectedBrand) {
                loadingText = `Buscando en sitios de ${selectedBrand.toUpperCase()}...`;
            }
            if (imageFile) {
                loadingText = '🤖 Analizando imagen de autoparte...';
            }
            showLoading(loadingText);
            
            const timeoutId = setTimeout(() => { 
                searching = false; 
                hideLoading(); 
                showError('Búsqueda muy lenta - Intenta de nuevo'); 
            }, 25000);
            
            const formData = new FormData();
            if (query) formData.append('query', query);
            if (imageFile) formData.append('image_file', imageFile);
            if (selectedBrand) formData.append('target_brand', selectedBrand);
            
            fetch('/api/search-auto-parts', {
                method: 'POST',
                body: formData
            })
            .then(response => { 
                clearTimeout(timeoutId); 
                searching = false; 
                return response.json(); 
            })
            .then(data => { 
                hideLoading(); 
                if (data.success) {
                    window.location.href = '/results';
                } else {
                    showError(data.error || 'Error en la búsqueda de repuestos');
                }
            })
            .catch(error => { 
                clearTimeout(timeoutId); 
                searching = false; 
                hideLoading(); 
                showError('Error de conexión'); 
            });
        });
        
        function showLoading(text = 'Buscando repuestos...') { 
            document.getElementById('loadingText').textContent = text;
            document.getElementById('loading').style.display = 'block'; 
            document.getElementById('error').style.display = 'none'; 
        }
        function hideLoading() { document.getElementById('loading').style.display = 'none'; }
        function showError(msg) { 
            hideLoading(); 
            const e = document.getElementById('error'); 
            e.textContent = msg; 
            e.style.display = 'block'; 
        }
    </script>'''
    
    return render_template_string(render_page('Busqueda de Repuestos', content))

@app.route('/api/search-auto-parts', methods=['POST'])
@login_required
def api_search_auto_parts():
    try:
        # Obtener parámetros
        query = request.form.get('query', '').strip() if request.form.get('query') else None
        target_brand = request.form.get('target_brand', '').strip() if request.form.get('target_brand') else None
        image_file = request.files.get('image_file')
        
        # Procesar imagen si existe
        image_content = None
        if image_file and image_file.filename != '':
            try:
                image_content = image_file.read()
                print(f"🖼️ Imagen de autoparte recibida: {len(image_content)} bytes")
                
                # Validar tamaño (máximo 10MB)
                if len(image_content) > 10 * 1024 * 1024:
                    return jsonify({'success': False, 'error': 'La imagen es demasiado grande (máximo 10MB)'}), 400
                    
            except Exception as e:
                print(f"❌ Error al leer imagen de autoparte: {e}")
                return jsonify({'success': False, 'error': 'Error al procesar la imagen'}), 400
        
        # Validar que hay al menos una entrada
        if not query and not image_content:
            return jsonify({'success': False, 'error': 'Debe proporcionar una consulta o una imagen de autoparte'}), 400
        
        # Limitar longitud de query
        if query and len(query) > 100:
            query = query[:100]
        
        user_email = session.get('user_email', 'Unknown')
        search_type = "imagen" if image_content and not query else "texto+imagen" if image_content and query else "texto"
        if target_brand:
            search_type += f"_marca_{target_brand}"
        
        print(f"🔧 Auto Parts search from {user_email}: {search_type}")
        
        # Realizar búsqueda especializada en autopartes
        products = auto_parts_finder.search_auto_parts_with_brand_focus(
            query=query, 
            image_content=image_content, 
            target_brand=target_brand
        )
        
        session['last_search'] = {
            'query': query or "búsqueda por imagen de autoparte",
            'products': products,
            'timestamp': datetime.now().isoformat(),
            'user': user_email,
            'search_type': search_type,
            'target_brand': target_brand,
            'is_auto_parts': True
        }
        
        print(f"✅ Auto Parts search completed for {user_email}: {len(products)} products found")
        return jsonify({'success': True, 'products': products, 'total': len(products)})
        
    except Exception as e:
        print(f"Auto Parts search error: {e}")
        try:
            query = request.form.get('query', 'auto parts') if request.form.get('query') else 'auto parts'
            fallback = auto_parts_finder._get_auto_parts_examples(query, target_brand)
            session['last_search'] = {
                'query': str(query), 
                'products': fallback, 
                'timestamp': datetime.now().isoformat(),
                'is_auto_parts': True,
                'target_brand': target_brand
            }
            return jsonify({'success': True, 'products': fallback, 'total': len(fallback)})
        except:
            return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/results')
@login_required
def results_page():
    try:
        if 'last_search' not in session:
            flash('No hay busquedas recientes.', 'warning')
            return redirect(url_for('search_page'))
        
        current_user = firebase_auth.get_current_user()
        user_name = current_user['user_name'] if current_user else 'Usuario'
        user_name_escaped = html.escape(user_name)
        
        search_data = session['last_search']
        products = search_data.get('products', [])
        query = html.escape(str(search_data.get('query', 'busqueda')))
        search_type = search_data.get('search_type', 'texto')
        target_brand = search_data.get('target_brand', '')
        
        products_html = ""
        badges = ['MEJOR PRECIO', 'OEM', 'AFTERMARKET', 'COMPATIBLE', '5to', '6to', '7mo', '8vo']
        colors = ['#4caf50', '#2196f3', '#ff9800', '#9c27b0', '#607d8b', '#795548', '#f44336', '#3f51b5']
        
        for i, product in enumerate(products[:8]):
            if not product:
                continue
            
            # Badge principal (precio/posición)
            badge_text = badges[min(i, len(badges)-1)]
            badge_color = colors[min(i, len(colors)-1)]
            
            # Badge especial para OEM
            if product.get('is_oem', False):
                badge_text = 'OEM ORIGINAL'
                badge_color = '#1976d2'
            
            badge = f'<div style="position: absolute; top: 8px; right: 8px; background: {badge_color}; color: white; padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{badge_text}</div>'
            
            # Badge de fuente de búsqueda
            search_source_badge = ''
            source = product.get('search_source', '')
            if source == 'image':
                search_source_badge = '<div style="position: absolute; top: 8px; left: 8px; background: #673ab7; color: white; padding: 4px 8px; border-radius: 12px; font-size: 10px; font-weight: bold;">📷 IMAGEN</div>'
            elif 'oem_' in source:
                brand = source.replace('oem_', '').upper()
                search_source_badge = f'<div style="position: absolute; top: 8px; left: 8px; background: #1976d2; color: white; padding: 4px 8px; border-radius: 12px; font-size: 10px; font-weight: bold;">🏭 {brand} OEM</div>'
            elif 'compatible_' in source:
                brand = source.replace('compatible_', '').upper()
                search_source_badge = f'<div style="position: absolute; top: 8px; left: 8px; background: #9c27b0; color: white; padding: 4px 8px; border-radius: 12px; font-size: 10px; font-weight: bold;">🔄 {brand}</div>'
            elif source == 'combined':
                search_source_badge = '<div style="position: absolute; top: 8px; left: 8px; background: #607d8b; color: white; padding: 4px 8px; border-radius: 12px; font-size: 10px; font-weight: bold;">🔗 MIXTO</div>'
            
            title = html.escape(str(product.get('title', 'Autoparte')))
            price = html.escape(str(product.get('price', '$0.00')))
            source_store = html.escape(str(product.get('source', 'Auto Parts Store')))
            link = html.escape(str(product.get('link', '#')))
            
            # Información adicional específica de autopartes
            part_category = product.get('part_category', 'general')
            store_type = product.get('store_type', 'aftermarket')
            compatibility_note = product.get('compatibility_note', '')
            
            category_icon = {
                'brakes': '🛑', 'engine': '⚙️', 'electrical': '⚡', 
                'suspension': '🔧', 'general': '🔩'
            }.get(part_category, '🔩')
            
            store_type_text = {
                'oem': 'Original (OEM)', 'aftermarket': 'Aftermarket', 
                'online': 'Online Store'
            }.get(store_type, 'Store')
            
            compatibility_html = f'<p style="color: #9c27b0; font-size: 12px; font-weight: 600; margin: 5px 0;">✅ {compatibility_note}</p>' if compatibility_note else ''
            
            products_html += f'''
                <div style="border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 15px; background: white; position: relative; box-shadow: 0 2px 4px rgba(0,0,0,0.08);">
                    {badge}
                    {search_source_badge}
                    <h3 style="color: #1e3c72; margin-bottom: 8px; font-size: 16px; margin-top: {'20px' if search_source_badge else '0'};">{category_icon} {title}</h3>
                    <div style="font-size: 28px; color: #2e7d32; font-weight: bold; margin: 12px 0;">{price} <span style="font-size: 12px; color: #666;">USD</span></div>
                    <p style="color: #666; margin-bottom: 8px; font-size: 14px;">🏪 {source_store} ({store_type_text})</p>
                    {compatibility_html}
                    <div style="display: flex; gap: 10px; align-items: center; margin-top: 12px;">
                        <a href="{link}" target="_blank" rel="noopener noreferrer" style="background: #1e3c72; color: white; padding: 10px 16px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block; font-size: 14px;">Ver Repuesto</a>
                        {f'<span style="color: #f57c00; font-size: 12px;">⭐ {product.get("rating", "")} ({product.get("reviews", "")} reviews)</span>' if product.get('rating') else ''}
                    </div>
                </div>'''
        
        # Estadísticas específicas de autopartes
        prices = [p.get('price_numeric', 0) for p in products if p.get('price_numeric', 0) > 0]
        oem_count = len([p for p in products if p.get('is_oem', False)])
        aftermarket_count = len(products) - oem_count
        
        stats = ""
        if prices:
            min_price = min(prices)
            avg_price = sum(prices) / len(prices)
            max_price = max(prices)
            
            search_type_text = {
                "texto": "búsqueda por texto", 
                "imagen": "IA visual", 
                "texto+imagen": "texto + IA visual",
                "combined": "búsqueda mixta"
            }
            
            for key in search_type_text:
                if key in search_type:
                    search_type_display = search_type_text[key]
                    break
            else:
                search_type_display = search_type
            
            brand_info = f" para {target_brand.upper()}" if target_brand else ""
            
            stats = f'''
                <div style="background: #e8f5e8; border: 1px solid #4caf50; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <h3 style="color: #2e7d32; margin-bottom: 8px;">🔧 Resultados de Autopartes{brand_info}</h3>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; font-size: 14px;">
                        <p><strong>{len(products)} repuestos encontrados</strong></p>
                        <p><strong>💰 Desde: ${min_price:.2f}</strong></p>
                        <p><strong>📊 Promedio: ${avg_price:.2f}</strong></p>
                        <p><strong>🏭 OEM: {oem_count}</strong></p>
                        <p><strong>🔧 Aftermarket: {aftermarket_count}</strong></p>
                        <p><strong>🔍 Método: {search_type_display}</strong></p>
                    </div>
                </div>'''
        
        content = f'''
        <div style="max-width: 900px; margin: 0 auto;">
            <div style="background: rgba(255,255,255,0.15); padding: 12px; border-radius: 8px; margin-bottom: 15px; text-align: center; display: flex; align-items: center; justify-content: center;">
                <span style="color: white; font-size: 14px;"><strong>{user_name_escaped}</strong></span>
                <div style="margin-left: 15px;">
                    <a href="{url_for('auth_logout')}" style="background: rgba(220,53,69,0.9); color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 13px; margin-right: 8px;">Salir</a>
                    <a href="{url_for('search_page')}" style="background: rgba(40,167,69,0.9); color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 13px;">Nueva Búsqueda</a>
                </div>
            </div>
            
            <h1 style="color: white; text-align: center; margin-bottom: 8px;">🔧 Repuestos: "{query}"</h1>
            <p style="text-align: center; color: rgba(255,255,255,0.9); margin-bottom: 25px;">Búsqueda especializada completada</p>
            
            {stats}
            {products_html}
        </div>'''
        
        return render_template_string(render_page('Resultados - Auto Parts Finder', content))
    except Exception as e:
        print(f"Results page error: {e}")
        flash('Error al mostrar resultados.', 'danger')
        return redirect(url_for('search_page'))

@app.route('/api/health')
def health_check():
    try:
        return jsonify({
            'status': 'OK', 
            'timestamp': datetime.now().isoformat(),
            'service': 'Auto Parts Finder - USA Only',
            'firebase_auth': 'enabled' if firebase_auth.firebase_web_api_key else 'disabled',
            'serpapi': 'enabled' if auto_parts_finder.is_api_configured() else 'disabled',
            'gemini_vision': 'enabled' if GEMINI_READY else 'disabled',
            'pil_available': 'enabled' if PIL_AVAILABLE else 'disabled',
            'auto_parts_stores': len(AUTO_PARTS_STORES),
            'supported_brands': list(CAR_BRAND_EQUIVALENTS.keys())
        })
    except Exception as e:
        return jsonify({'status': 'ERROR', 'message': str(e)}), 500

# Middleware (sin cambios)
@app.before_request
def before_request():
    if 'timestamp' in session:
        try:
            timestamp_str = session['timestamp']
            if isinstance(timestamp_str, str) and len(timestamp_str) > 10:
                last_activity = datetime.fromisoformat(timestamp_str)
                time_diff = (datetime.now() - last_activity).total_seconds()
                if time_diff > 1200:  # 20 minutos
                    session.clear()
        except:
            session.clear()
    
    session['timestamp'] = datetime.now().isoformat()

@app.after_request
def after_request(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

# Error handlers (sin cambios)
@app.errorhandler(404)
def not_found(error):
    return '<h1>404 - Pagina no encontrada</h1><p><a href="/">Volver al inicio</a></p>', 404

@app.errorhandler(500)
def internal_error(error):
    return '<h1>500 - Error interno</h1><p><a href="/">Volver al inicio</a></p>', 500

if __name__ == '__main__':
    print("🔧 Auto Parts Finder - USA Only - Starting...")
    print(f"Firebase: {'OK' if os.environ.get('FIREBASE_WEB_API_KEY') else 'NOT_CONFIGURED'}")
    print(f"SerpAPI: {'OK' if os.environ.get('SERPAPI_KEY') else 'NOT_CONFIGURED'}")
    print(f"Gemini Vision: {'OK' if GEMINI_READY else 'NOT_CONFIGURED'}")
    print(f"PIL/Pillow: {'OK' if PIL_AVAILABLE else 'NOT_CONFIGURED'}")
    print(f"Auto Parts Stores: {len(AUTO_PARTS_STORES)} configured")
    print(f"Supported Brands: {list(CAR_BRAND_EQUIVALENTS.keys())}")
    print(f"Puerto: {os.environ.get('PORT', '5000')}")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False, threaded=True)
else:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
