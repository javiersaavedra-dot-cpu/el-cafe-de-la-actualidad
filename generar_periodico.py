#!/usr/bin/env python3
"""El café de la actualidad: periódico RSS gratuito, sin dependencias externas."""
import datetime as dt
import email.utils
import html
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

def card(it):
    e = lambda s: html.escape(s or '', quote=True)
    img = (f'<img loading="lazy" referrerpolicy="no-referrer" src="{e(it["image"])}" alt="Imagen proporcionada por {e(it["source"])}" onerror="this.style.display=\'none\'">'
           if it['image'] else '<div class="placeholder">☕</div>')
    excerpt = it['description'] or 'Consulta la noticia completa en el medio de origen.'
    return (f'<article class="card"><div class="visual">{img}</div><div class="inner">'
            f'<div class="section">{e(it["section"])} · {e(it["source"])}</div>'
            f'<h2><a href="{e(it["link"])}" target="_blank" rel="noopener noreferrer">{e(it["title"])}</a></h2>'
            f'<p>{e(excerpt)}</p><p class="note">Resumen extraído del RSS del medio; puede ser breve o incompleto. '
            f'La fotografía, si aparece, procede del feed original.</p>'
            f'<a class="more" href="{e(it["link"])}" target="_blank" rel="noopener noreferrer">Leer noticia original →</a>'
            f'</div></article>')

def main():
    items = []
    for feed in FEEDS:
        items.extend(fetch(*feed))
    chosen = choose(items)
    if len(chosen) < 5:
        raise SystemExit('Menos de cinco noticias recientes disponibles: se conserva la edición anterior.')
    date = NOW.strftime('%d/%m/%Y')
    body = '\n'.join(card(it) for it in chosen)
    edition = 'Edición de fin de semana' if WEEKEND else 'Edición diaria'
    page = f'''<!doctype html><html lang="es"><head>
<link rel="icon" type="image/png" href="icono.png">
<link rel="apple-touch-icon" href="icono.png">
<link rel="manifest" href="manifest.json">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>El café de la actualidad · {date}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1eee8;color:#222;font-family:Georgia,'Times New Roman',serif}}header{{background:#fff;text-align:center;border-bottom:4px double #1f1f1f;padding:26px 12px}}.tag{{font:700 11px Arial,sans-serif;letter-spacing:3px;color:#3c6575;text-transform:uppercase}}h1{{font-size:clamp(32px,6vw,66px);letter-spacing:-2px;margin:8px 0}}header p{{font:14px Arial,sans-serif;color:#666}}main{{max-width:1320px;margin:0 auto;padding:28px 18px 55px}}.intro{{margin:0 0 23px;border-bottom:1px solid #bbb;padding-bottom:14px;font:15px Arial,sans-serif;line-height:1.6}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}}.card{{background:white;min-width:0;border:1px solid #dcd7cd;box-shadow:0 2px 9px #00000009}}.visual{{height:205px;background:#e6e0d5;overflow:hidden}}.visual img{{width:100%;height:100%;object-fit:cover}}.placeholder{{height:100%;display:grid;place-items:center;font-size:45px;color:#9c9488}}.inner{{padding:19px 21px 23px}}.section{{font:700 11px Arial,sans-serif;color:#2e6a80;letter-spacing:1px;text-transform:uppercase}}h2{{font-size:clamp(20px,2vw,26px);line-height:1.12;margin:10px 0 13px}}h2 a{{text-decoration:none;color:inherit}}h2 a:hover{{color:#235c73}}.card p{{font-size:16px;line-height:1.48}}.note{{font:12px/1.4 Arial,sans-serif!important;color:#777}}.more{{font:700 13px Arial,sans-serif;color:#226079;text-decoration:none}}footer{{text-align:center;padding:25px;font:12px/1.5 Arial,sans-serif;color:#777}}@media(max-width:980px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:640px){{.grid{{grid-template-columns:1fr}}main{{padding:18px 12px}}.visual{{height:225px}}}}
</style></head><body><header><div class="tag">Tu periódico · {edition}</div><h1>El café de la actualidad</h1><p>{date} · Burgos · Noticias seleccionadas de medios abiertos</p></header><main><p class="intro"><b>Actualidad para conversar.</b> Selección automática de noticias recientes de canales RSS. Los textos proceden de las descripciones facilitadas por los medios: no son crónicas redactadas ni verificadas de forma independiente. Pulsa cada titular para conocer los detalles.</p><div class="grid">{body}</div></main><footer>Edición automática gratuita · Enlaces y derechos de las noticias y fotografías pertenecen a sus respectivos medios · Última generación: {NOW.strftime('%d/%m/%Y %H:%M')} (hora peninsular)</footer></body></html>'''
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(page)
    print(f'{edition}: {len(chosen)} noticias (objetivo {LIMIT})')

if __name__ == '__main__':
    main()
