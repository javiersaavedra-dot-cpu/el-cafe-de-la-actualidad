#!/usr/bin/env python3
"""El café de la actualidad: periódico RSS gratuito, sin dependencias externas."""
import datetime as dt
import email.utils
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Madrid')
NOW = dt.datetime.now(TZ)
WEEKEND = NOW.weekday() >= 5
LIMIT = 24 if WEEKEND else 18

# RSS públicos: algunos medios cambian sus direcciones o bloquean las peticiones.
# Un feed que falle no impide generar el periódico con el resto.
FEEDS = [
    ('RTVE España', 'España', 'https://www.rtve.es/rss/temas_noticias.xml'),
    ('RTVE Internacional', 'Internacional', 'https://www.rtve.es/rss/temas_internacional.xml'),
    ('RTVE Sociedad', 'Sociedad', 'https://www.rtve.es/rss/temas_sociedad.xml'),
    ('RTVE Cultura', 'Cultura', 'https://www.rtve.es/rss/temas_cultura.xml'),
    ('RTVE Deportes', 'Deportes', 'https://www.rtve.es/rss/temas_deportes.xml'),
    ('RTVE Ciencia', 'Ciencia', 'https://www.rtve.es/rss/temas_ciencia.xml'),
    ('RTVE Tecnología', 'Ciencia', 'https://www.rtve.es/rss/temas_tecnologia.xml'),
    ('El País portada', 'España', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada'),
    ('El País Internacional', 'Internacional', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada'),
    ('BBC Mundo', 'Internacional', 'https://feeds.bbci.co.uk/mundo/rss.xml'),
    ('20 Minutos', 'Sociedad', 'https://www.20minutos.es/rss/'),
    ('Xataka', 'Ciencia', 'https://www.xataka.com/index.xml'),
    ('SINC', 'Ciencia', 'https://www.agenciasinc.es/rss'),
    ('Diario de Burgos', 'Local', 'https://www.diariodeburgos.es/rss'),
    ('Burgos Conecta', 'Local', 'https://www.burgosconecta.es/rss/'),
    # Google Noticias permite seguir los titulares del medio sin depender de un RSS propio.
    ('El Correo de Burgos', 'Local', 'https://news.google.com/rss/search?q=site%3Aelcorreodeburgos.com&hl=es&gl=ES&ceid=ES%3Aes'),
]
NS = {
    'media': 'http://search.yahoo.com/mrss/',
    'content': 'http://purl.org/rss/1.0/modules/content/',
    'atom': 'http://www.w3.org/2005/Atom',
}
# Distribución orientativa. Las plazas sin noticias disponibles se redistribuyen.
QUOTAS = (
    {'España': 5, 'Internacional': 5, 'Local': 2, 'Sociedad': 2,
     'Ciencia': 2, 'Cultura': 1, 'Deportes': 1}
    if not WEEKEND else
    {'España': 4, 'Internacional': 4, 'Local': 3, 'Ciencia': 4,
     'Cultura': 4, 'Sociedad': 3, 'Deportes': 2}
)
STOPWORDS = {'para', 'sobre', 'desde', 'entre', 'tras', 'este', 'esta', 'estos',
             'estas', 'según', 'también', 'ante', 'como', 'hasta', 'nuevo', 'nueva'}

def plain(raw):
    raw = re.sub(r'<[^>]+>', ' ', raw or '')
    return re.sub(r'\s+', ' ', html.unescape(raw)).strip()

def first_text(item, tags):
    for tag in tags:
        el = item.find(tag, NS)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ''

def image_url(item):
    for path in ('media:content', 'media:thumbnail', 'enclosure'):
        for el in item.findall(path, NS):
            url = el.attrib.get('url', '')
            kind = el.attrib.get('type', '')
            if url.startswith('https://') and (path != 'enclosure' or kind.startswith('image/')):
                return url
    return ''

def classify(section, title, description):
    """Reclasifica titulares evidentes; no inventa noticias ni su contenido."""
    t = (title + ' ' + description[:180]).lower()
    science = ('investigación', 'científic', 'astronom', 'nasa', 'espacial',
               'descubrimient', 'universo', 'arqueolog', 'fósil', 'inteligencia artificial')
    culture = ('museo', 'exposición', 'literatura', 'novela', 'cine', 'teatro',
               'festival', 'concierto', 'patrimonio', 'historia del')
    local = ('burgos', 'castilla y león', 'valladolid', 'palencia', 'soria', 'segovia',
             'salamanca', 'zamora', 'ávila', 'león')
    if section in ('España', 'Sociedad') and any(x in t for x in local):
        return 'Local'
    if section in ('España', 'Sociedad') and any(x in t for x in science):
        return 'Ciencia'
    if section in ('España', 'Sociedad') and any(x in t for x in culture):
        return 'Cultura'
    return section

def fetch(source, section, url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; CafeActualidad/2.0; RSS reader)'})
        with urllib.request.urlopen(req, timeout=12) as response:
            data = response.read(2_000_000)
        root = ET.fromstring(data)
        items = root.findall('.//item') or root.findall('.//atom:entry', NS)
        result = []
        for it in items[:45]:
            title = plain(first_text(it, ['title', 'atom:title']))
            link = first_text(it, ['link'])
            if not link:
                lk = it.find('atom:link', NS)
                link = lk.attrib.get('href', '') if lk is not None else ''
            description = plain(first_text(it, ['description', 'summary', 'atom:summary', 'content:encoded']))
            published = first_text(it, ['pubDate', 'published', 'atom:updated', 'atom:published'])
            try:
                when = email.utils.parsedate_to_datetime(published)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=dt.timezone.utc)
                when = when.astimezone(TZ)
            except Exception:
                try:
                    when = dt.datetime.fromisoformat(published.replace('Z', '+00:00')).astimezone(TZ)
                except Exception:
                    continue
            # Ventana algo más amplia los fines de semana, cuando hay menos publicaciones.
            max_age = 76 if WEEKEND else 52
            if not title or not link.startswith('https://') or not (NOW - dt.timedelta(hours=max_age) <= when <= NOW + dt.timedelta(hours=2)):
                continue
            result.append(dict(title=title, link=link, description=description[:650],
                               published=when, source=source,
                               section=classify(section, title, description), image=image_url(it)))
        print(f'{source}: {len(result)} noticias recientes')
        return result
    except Exception as exc:
        print(f'AVISO: {source}: {exc}')
        return []

def normalize(s):
    return set(re.findall(r'\w{4,}', s.lower())) - STOPWORDS

def similar(a, b):
    wa, wb = normalize(a), normalize(b)
    common = len(wa & wb)
    return common >= 3 and common / max(1, min(len(wa), len(wb))) > 0.48

def choose(items):
    items.sort(key=lambda x: x['published'], reverse=True)
    selected, seen_links = [], set()
    sources = defaultdict(int)
    sections = defaultdict(int)
    def add(it, cap_source):
        if it['link'] in seen_links or sources[it['source']] >= cap_source:
            return False
        if any(similar(it['title'], old['title']) for old in selected):
            return False
        selected.append(it)
        seen_links.add(it['link'])
        sources[it['source']] += 1
        sections[it['section']] += 1
        return True
    # Primera pasada: llenar secciones dentro de sus cupos.
    for section, quota in QUOTAS.items():
        for it in items:
            if sections[section] >= quota:
                break
            if it['section'] == section:
                add(it, 7 if WEEKEND else 6)
    # Segunda pasada: redistribuir plazas vacías, sin perder diversidad.
    for cap in (7 if WEEKEND else 6, LIMIT):
        for it in items:
            if len(selected) >= LIMIT:
                break
            add(it, cap)
    # Presentación por actualidad, no por orden de selección de las secciones.
    return sorted(selected[:LIMIT], key=lambda x: x['published'], reverse=True)

# Ilustraciones decorativas integradas en el HTML: sin imágenes externas.
SECTION_ART = {
    'Actualidad': ('🌍', 'ACTUALIDAD'),
    'Internacional': ('🌍', 'EL MUNDO'),
    'Local': ('🏛️', 'BURGOS Y CASTILLA Y LEÓN'),
    'Sociedad': ('📰', 'SOCIEDAD'),
    'Ciencia': ('🔬', 'CIENCIA Y DESCUBRIMIENTOS'),
    'Cultura': ('🎭', 'CULTURA'),
    'Deportes': ('⚽', 'DEPORTES'),
}

def card(it):
    e = lambda s: html.escape(s or '', quote=True)
    symbol, label = SECTION_ART.get(it['section'], ('☕', 'ACTUALIDAD'))
    # La ilustración permanece detrás de la fotografía: si falla la carga,
    # el navegador muestra automáticamente la alternativa decorativa.
    fallback = (f'<div class="fallback" aria-label="Ilustración decorativa de {e(it["section"])}">'
                f'<span class="fallback-glow"></span><span class="fallback-symbol">{symbol}</span>'
                f'<span class="fallback-label">{e(label)}</span></div>')
    img = (f'<img loading="lazy" referrerpolicy="no-referrer" src="{e(it["image"])}" '
           f'alt="Imagen proporcionada por {e(it["source"])}" '
           f'onerror="this.style.display=\'none\'">' if it['image'] else '')
    excerpt = it['description'] or 'Consulta la noticia completa en el medio de origen.'
    return (f'<article id="noticia-{it.get("story_id", 0)}" class="card"><div class="visual">{fallback}{img}</div><div class="inner">'
            f'<div class="section">{e(it["section"])} · {e(it["source"])}</div>'
            f'<h2><a href="{e(it["link"])}" target="_blank" rel="noopener noreferrer">{e(it["title"])}</a></h2>'
            f'<p>{e(excerpt)}</p><p class="note">Resumen extraído del RSS del medio; puede ser breve o incompleto. '
            f'La fotografía, si aparece, procede del feed original. Las ilustraciones son decorativas.</p>'
            f'<a class="more" href="{e(it["link"])}" target="_blank" rel="noopener noreferrer">Leer noticia original →</a>'
            f'</div></article>')

def weather_block():
    """Previsión de Burgos a las 08, 14 y 21, hora peninsular.

    Si Open-Meteo no responde, no bloqueamos la edición de noticias.
    """
    url = ('https://api.open-meteo.com/v1/forecast?latitude=42.3439&longitude=-3.6969'
           '&hourly=temperature_2m,precipitation_probability,weather_code'
           '&timezone=Europe%2FMadrid&forecast_days=2')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'CafeActualidad/2.1 (weather)'})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.load(response)
        hourly = data['hourly']
        forecast = {t: i for i, t in enumerate(hourly['time'])}
        descriptions = {
            0: ('☀️', 'Despejado'), 1: ('🌤️', 'Poco nuboso'),
            2: ('⛅', 'Parcialmente nuboso'), 3: ('☁️', 'Cubierto'),
            45: ('🌫️', 'Niebla'), 48: ('🌫️', 'Niebla helada'),
            51: ('🌦️', 'Llovizna'), 53: ('🌦️', 'Llovizna'), 55: ('🌧️', 'Llovizna'),
            56: ('🌧️', 'Llovizna helada'), 57: ('🌧️', 'Llovizna helada'),
            61: ('🌦️', 'Lluvia débil'), 63: ('🌧️', 'Lluvia'), 65: ('🌧️', 'Lluvia intensa'),
            66: ('🌧️', 'Lluvia helada'), 67: ('🌧️', 'Lluvia helada'),
            71: ('🌨️', 'Nieve débil'), 73: ('🌨️', 'Nieve'), 75: ('❄️', 'Nevada intensa'),
            77: ('❄️', 'Nieve granulada'),
            80: ('🌦️', 'Chubascos'), 81: ('🌧️', 'Chubascos'), 82: ('⛈️', 'Chubascos fuertes'),
            85: ('🌨️', 'Chubascos de nieve'), 86: ('❄️', 'Nieve intensa'),
            95: ('⛈️', 'Tormenta'), 96: ('⛈️', 'Tormenta con granizo'),
            99: ('⛈️', 'Tormenta con granizo'),
        }
        blocks = []
        for hour in (8, 14, 21):
            key = f'{NOW.date().isoformat()}T{hour:02d}:00'
            i = forecast[key]
            code = int(hourly['weather_code'][i])
            icon, description = descriptions.get(code, ('🌡️', 'Previsión'))
            temp = round(float(hourly['temperature_2m'][i]))
            rain = hourly['precipitation_probability'][i]
            probability = f'{round(float(rain))} %' if rain is not None else '—'
            blocks.append(f'<div class="weather-time"><span class="weather-hour">{hour:02d}:00</span>'
                          f'<span class="weather-icon">{icon}</span>'
                          f'<strong>{temp} °C</strong><span>{html.escape(description)}</span>'
                          f'<small>💧 Lluvia: {probability}</small></div>')
        return ('<section class="weather" aria-label="Previsión meteorológica de Burgos">'
                '<div class="weather-title">EL TIEMPO EN BURGOS <span>· Previsión de hoy</span></div>'
                f'<div class="weather-grid">{"".join(blocks)}</div>'
                '<div class="weather-credit">Fuente: Open-Meteo · Probabilidad de precipitación por hora · '
                'Previsión, no observaciones en tiempo real.</div></section>')
    except Exception as exc:
        print(f'AVISO: previsión meteorológica no disponible: {exc}')
        return ('<section class="weather weather-unavailable">'
                '🌦️ Previsión de Burgos temporalmente no disponible. '
                '<a href="https://www.aemet.es/es/eltiempo/prediccion/municipios/burgos-id09059" '
                'target="_blank" rel="noopener noreferrer">Consultar AEMET →</a></section>')

SECTION_ORDER = [
    ('España', 'España', 'espana'),
    ('Internacional', 'Mundo', 'mundo'),
    ('Local', 'Burgos', 'burgos'),
    ('Sociedad', 'Sociedad', 'sociedad'),
    ('Deportes', 'Deportes', 'deportes'),
    ('Cultura', 'Cultura', 'cultura'),
    ('Ciencia', 'Ciencia', 'ciencia'),
]

def importance_score(it, all_items):
    """Heurística editorial: actualidad, alcance y corroboración entre medios.

    No es una evaluación periodística ni garantiza la noticia más importante.
    """
    age = max(0, (NOW - it['published']).total_seconds() / 3600)
    score = max(0, 24 - age * 0.65)
    section_weight = {'Internacional': 16, 'España': 15, 'Sociedad': 10,
                      'Local': 8, 'Ciencia': 5, 'Cultura': 4, 'Deportes': 4}
    score += section_weight.get(it['section'], 0)
    title = it['title'].lower()
    important = ('guerra', 'ataque', 'atentado', 'elecciones', 'elección', 'crisis',
                 'terremoto', 'inundaci', 'incendio', 'muertos', 'fallecidos',
                 'manifestaci', 'protesta', 'acuerdo', 'alto el fuego', 'dimisión',
                 'emergencia', 'evacuación', 'conflicto', 'parlamento', 'gobierno')
    score += min(18, 9 * sum(word in title for word in important))
    # Un mismo suceso tratado por varias cabeceras aporta confianza a la prioridad.
    corroborating = {other['source'] for other in all_items
                     if other['source'] != it['source'] and similar(it['title'], other['title'])}
    score += min(24, len(corroborating) * 12)
    # Evita elegir una noticia principal de apenas una frase cuando hay alternativas.
    if len(it['description']) < 90:
        score -= 8
    return score


def cover_html(chosen, all_items):
    """Portada destacada y tres avances que enlazan a sus noticias completas."""
    ranked = sorted(chosen, key=lambda it: importance_score(it, all_items), reverse=True)
    lead = ranked[0]
    secondary = ranked[1:4]
    e = lambda value: html.escape(value or '', quote=True)
    symbol, label = SECTION_ART.get(lead['section'], ('☕', 'ACTUALIDAD'))
    fallback = (f'<div class="fallback" aria-label="Ilustración decorativa">'
                f'<span class="fallback-glow"></span><span class="fallback-symbol">{symbol}</span>'
                f'<span class="fallback-label">{e(label)}</span></div>')
    photo = (f'<img src="{e(lead["image"])}" alt="Fotografía facilitada por {e(lead["source"])}" '
             'referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">') if lead['image'] else ''
    summary = lead['description'] or 'Lee la información en el medio de origen.'
    hero = (f'<article class="cover-lead"><div class="cover-image">{fallback}{photo}</div>'
            f'<div class="cover-copy"><span class="cover-label">LA NOTICIA DEL DÍA · {e(lead["section"])}</span>'
            f'<h2>{e(lead["title"])}</h2><p>{e(summary)}</p>'
            f'<span class="cover-source">Fuente: {e(lead["source"])}</span><br>'
            f'<a class="more" href="{e(lead["link"])}" target="_blank" rel="noopener noreferrer">Leer noticia original →</a>'
            '</div></article>')
    teasers = ''.join(f'<a class="cover-teaser" href="#noticia-{it["story_id"]}">'
                      f'<span>{e(it["section"])} · {e(it["source"])}</span>'
                      f'<strong>{e(it["title"])}</strong><small>Ver noticia en su sección ↓</small></a>'
                      for it in secondary)
    return ('<section class="cover" id="portada-noticias"><h2 class="cover-heading">Portada</h2>'
            + hero + '<h3 class="cover-subtitle">Otras noticias destacadas</h3>'
            + f'<div class="cover-teasers">{teasers}</div></section>'), lead


def sections_html(chosen, lead):
    """Agrupa las noticias por sección y crea destinos para el menú."""
    output = []
    for section, label, anchor in SECTION_ORDER:
        articles = [item for item in chosen if item['section'] == section and item is not lead]
        if not articles:
            continue
        output.append(f'<section class="news-section" id="{anchor}" aria-labelledby="heading-{anchor}">'
                      f'<div class="section-heading"><h2 id="heading-{anchor}">{label}</h2>'
                      f'<a href="#portada-noticias" class="back-top">↑ Portada</a></div>'
                      f'<div class="grid">{"".join(card(item) for item in articles)}</div></section>')
    return '\n'.join(output)

def navigation_html(chosen):
    links = ['<a href="#portada-noticias">Portada</a>']
    for section, label, anchor in SECTION_ORDER:
        if any(item['section'] == section for item in chosen):
            links.append(f'<a href="#{anchor}">{label}</a>')
    return '<nav class="news-nav" aria-label="Secciones del periódico"><div class="nav-inner">' + ' '.join(links) + '</div></nav>'


def main():
    items = []
    for feed in FEEDS:
        items.extend(fetch(*feed))
    chosen = choose(items)
    if len(chosen) < 5:
        raise SystemExit('Menos de cinco noticias recientes disponibles: se conserva la edición anterior.')
    date = NOW.strftime('%d/%m/%Y')
    for i, item in enumerate(chosen):
        item['story_id'] = i + 1
    cover, lead = cover_html(chosen, items)
    body = sections_html(chosen, lead)
    navigation = navigation_html(chosen)
    forecast_html = weather_block()
    edition = 'Edición de fin de semana' if WEEKEND else 'Edición diaria'
    page = f'''<!doctype html><html lang="es"><head>
<link rel="icon" type="image/png" href="icono.png">
<link rel="apple-touch-icon" href="icono.png">
<link rel="manifest" href="manifest.json">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>El café de la actualidad · {date}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1eee8;color:#222;font-family:Georgia,'Times New Roman',serif}}html{{scroll-behavior:smooth;scroll-padding-top:70px}}header{{background:#fff;text-align:center;border-bottom:4px double #1f1f1f;padding:26px 12px}}.tag{{font:700 11px Arial,sans-serif;letter-spacing:3px;color:#3c6575;text-transform:uppercase}}h1{{font-size:clamp(32px,6vw,66px);letter-spacing:-2px;margin:8px 0}}header p{{font:14px Arial,sans-serif;color:#666}}main{{max-width:1320px;margin:0 auto;padding:28px 18px 55px}}.intro{{margin:0 0 23px;border-bottom:1px solid #bbb;padding-bottom:14px;font:15px Arial,sans-serif;line-height:1.6}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}}.card{{background:white;min-width:0;border:1px solid #dcd7cd;box-shadow:0 2px 9px #00000009}}.visual{{height:205px;background:#e6e0d5;overflow:hidden;position:relative}}.visual img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.fallback{{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;position:relative;overflow:hidden;background:linear-gradient(135deg,#d9e6e4,#f1e2cb);color:#385d63}}.fallback-glow{{position:absolute;width:260px;height:260px;border:2px solid #ffffff66;border-radius:50%;box-shadow:0 0 0 38px #ffffff24,0 0 0 78px #ffffff19}}.fallback-symbol{{position:relative;font-size:66px;line-height:1.1;filter:drop-shadow(0 4px 5px #00000020)}}.fallback-label{{position:relative;font:700 11px Arial,sans-serif;letter-spacing:2px;text-align:center;padding:0 15px}}.inner{{padding:19px 21px 23px}}.section{{font:700 11px Arial,sans-serif;color:#2e6a80;letter-spacing:1px;text-transform:uppercase}}h2{{font-size:22px;line-height:1.12;margin:10px 0 13px}}h2 a{{text-decoration:none;color:inherit}}h2 a:hover{{color:#235c73}}.card p{{font-size:16px;line-height:1.48}}.note{{font:12px/1.4 Arial,sans-serif!important;color:#777}}.more{{font:700 13px Arial,sans-serif;color:#226079;text-decoration:none}}footer{{text-align:center;padding:25px;font:12px/1.5 Arial,sans-serif;color:#777}}@media(max-width:980px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:640px){{.grid{{grid-template-columns:1fr}}main{{padding:18px 12px}}.visual{{height:225px}}h2{{font-size:20px}}}}
 .news-nav{{position:sticky;top:0;z-index:20;background:#fff;border-bottom:2px solid #252525;box-shadow:0 2px 8px #00000012;font-family:Arial,sans-serif}}.nav-inner{{max-width:1320px;margin:auto;display:flex;gap:4px;align-items:center;overflow-x:auto;white-space:nowrap;padding:0 12px;scrollbar-width:thin}}.news-nav a{{display:inline-block;padding:14px 13px;text-decoration:none;color:#222;font-size:13px;font-weight:700}}.news-nav a:hover,.news-nav a:focus-visible{{background:#eee9df;color:#1b6177}}.news-section{{margin:24px 0 42px;scroll-margin-top:74px}}.section-heading{{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:3px solid #262626;border-bottom:1px solid #bbb;margin:0 0 20px;padding:9px 0}}.section-heading h2{{font:700 clamp(23px,3vw,31px) Georgia,serif;margin:0}}.back-top{{font:12px Arial,sans-serif;color:#31677a;text-decoration:none}}@media(max-width:640px){{.news-nav a{{padding:12px 10px;font-size:12px}}.news-section{{margin-bottom:32px}}}}
 .weather{{max-width:850px;margin:16px auto 0;padding:13px 18px;border:1px solid #ded9cf;border-radius:9px;background:#f7f5ef;font-family:Arial,sans-serif;text-align:center}}.weather-title{{font-size:12px;letter-spacing:1.4px;font-weight:700;color:#31586a}}.weather-title span{{font-weight:400;letter-spacing:0;color:#777}}.weather-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:12px 0}}.weather-time{{display:flex;flex-direction:column;align-items:center;gap:5px;border-right:1px solid #ddd;font-size:12px;color:#555}}.weather-time:last-child{{border-right:0}}.weather-hour{{font-weight:700}}.weather-icon{{font-size:24px}}.weather-time strong{{font-size:19px;color:#222}}.weather-time small{{font-size:11px}}.weather-credit{{font-size:10px;color:#777}}.weather-unavailable{{font-size:12px}}@media(max-width:640px){{.weather{{padding:11px 6px}}.weather-time strong{{font-size:17px}}.weather-time small{{font-size:10px}}}}
 .cover{{scroll-margin-top:74px;margin-bottom:35px}}.cover-heading{{font:700 30px Georgia,serif;border-bottom:3px solid #222;padding-bottom:12px;margin:0 0 20px}}.cover-lead{{display:grid;grid-template-columns:1.05fr 1fr;background:#fff;border:1px solid #dcd7cd}}.cover-image{{position:relative;min-height:340px;overflow:hidden;background:#e6e0d5}}.cover-image img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.cover-copy{{padding:28px}}.cover-label{{font:700 12px Arial,sans-serif;letter-spacing:1px;color:#a0392f}}.cover-copy h2{{font-size:clamp(26px,3.2vw,42px);line-height:1.12;margin:14px 0}}.cover-copy p{{font:17px/1.55 Georgia,serif}}.cover-source{{display:inline-block;font:12px Arial,sans-serif;color:#666;margin-bottom:15px}}.cover-subtitle{{font:700 21px Georgia,serif;margin:25px 0 13px}}.cover-teasers{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}.cover-teaser{{display:flex;flex-direction:column;gap:10px;text-decoration:none;color:#222;border-top:3px solid #333;background:#fff;padding:18px;min-width:0}}.cover-teaser span{{font:700 11px Arial,sans-serif;color:#2e6a80;text-transform:uppercase}}.cover-teaser strong{{font:700 19px/1.2 Georgia,serif}}.cover-teaser small{{margin-top:auto;font:12px Arial,sans-serif;color:#226079}}@media(max-width:760px){{.cover-lead{{grid-template-columns:1fr}}.cover-image{{min-height:230px}}.cover-copy{{padding:20px}}.cover-teasers{{grid-template-columns:1fr}}}}
</style></head><body><header id="portada"><div class="tag">Tu periódico · {edition}</div><h1>El café de la actualidad</h1><p>{date} · Burgos · Noticias seleccionadas de medios abiertos</p>{forecast_html}</header>{navigation}<main><p class="intro"><b>Actualidad para conversar.</b> Selección automática de noticias recientes de canales RSS. Los textos proceden de las descripciones facilitadas por los medios: no son crónicas redactadas ni verificadas de forma independiente. Pulsa cada titular para conocer los detalles.</p>{cover}{body}</main><footer>Edición automática gratuita · Enlaces y derechos de las noticias y fotografías pertenecen a sus respectivos medios · Última generación: {NOW.strftime('%d/%m/%Y %H:%M')} (hora peninsular)</footer></body></html>'''
    # Guion de voz en el orden visual: portada y después secciones.
    spoken = [lead] + [it for section, _, _ in SECTION_ORDER for it in chosen
                        if it['section'] == section and it is not lead]
    chunks = ['Bienvenidos a El café de la actualidad. Estas son las noticias del día.']
    for index, item in enumerate(spoken, 1):
        chunks.append(f'Noticia {index}. {item["section"]}. {item["title"]}. '
                      + (item['description'] or 'Consulta el medio original para ampliar esta noticia.'))
    chunks.append('Hasta aquí El café de la actualidad. Gracias por escucharnos.')
    with open('guion_audio.txt', 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(chunks))
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(page)
    print(f'{edition}: {len(chosen)} noticias (objetivo {LIMIT})')

if __name__ == '__main__':
    main()
