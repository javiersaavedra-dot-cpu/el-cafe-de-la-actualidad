"""Genera el MP3 por fragmentos y conserva la edición anterior si falla."""
import asyncio
import datetime
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import edge_tts

VOICE = 'es-ES-ElviraNeural'
RATE = '-5%'
MAX_CHARS = 1100


def dividir_guion(guion):
    """Mantiene separadas las noticias y limita la longitud de cada petición TTS."""
    partes = []
    for bloque in re.split(r'\n\s*\n', guion.strip()):
        bloque = re.sub(r'\s+', ' ', bloque).strip()
        if not bloque:
            continue
        if len(bloque) <= MAX_CHARS:
            partes.append(bloque)
            continue
        # Separar primero por frases; si una frase es demasiado larga, por palabras.
        frases = re.split(r'(?<=[.!?…])\s+', bloque)
        actual = ''
        for frase in frases:
            if len(frase) > MAX_CHARS:
                if actual:
                    partes.append(actual)
                    actual = ''
                palabras = frase.split()
                trozo = ''
                for palabra in palabras:
                    if trozo and len(trozo) + len(palabra) + 1 > MAX_CHARS:
                        partes.append(trozo)
                        trozo = ''
                    trozo = f'{trozo} {palabra}'.strip()
                if trozo:
                    partes.append(trozo)
            elif actual and len(actual) + len(frase) + 1 > MAX_CHARS:
                partes.append(actual)
                actual = frase
            else:
                actual = f'{actual} {frase}'.strip()
        if actual:
            partes.append(actual)
    return partes


def duracion_mp3(ruta):
    resultado = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', str(ruta)],
        capture_output=True, text=True, check=True)
    return float(resultado.stdout.strip())


async def main():
    guion = Path('guion_audio.txt').read_text(encoding='utf-8').strip()
    if not guion:
        raise RuntimeError('Guion vacío')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('Se necesitan ffmpeg y ffprobe para unir y verificar los audios')
    partes = dividir_guion(guion)
    if not partes:
        raise RuntimeError('No hay fragmentos para narrar')
    print(f'Audio: {len(partes)} fragmentos; {len(guion)} caracteres de guion.')

    with tempfile.TemporaryDirectory(prefix='cafe_audio_') as carpeta:
        carpeta = Path(carpeta)
        rutas = []
        for indice, texto in enumerate(partes, 1):
            ruta = carpeta / f'parte_{indice:03d}.mp3'
            # Cada fragmento tiene su propia conexión; un fallo detiene la publicación.
            await edge_tts.Communicate(texto, VOICE, rate=RATE).save(str(ruta))
            if not ruta.exists() or ruta.stat().st_size < 1000:
                raise RuntimeError(f'Fragmento {indice} vacío o incompleto')
            segundos = duracion_mp3(ruta)
            palabras = len(texto.split())
            # Comprobación conservadora: detecta fragmentos muy cortos, no valida el habla.
            if segundos < max(1.0, palabras * 0.10):
                raise RuntimeError(
                    f'Fragmento {indice} sospechosamente corto: {segundos:.1f}s para {palabras} palabras')
            rutas.append(ruta)
            print(f'Fragmento {indice}/{len(partes)}: {segundos:.1f}s')

        lista = carpeta / 'fragmentos.txt'
        lista.write_text(''.join(f"file '{ruta.name}'\n" for ruta in rutas), encoding='utf-8')
        combinado = carpeta / 'periodico_completo.mp3'
        subprocess.run(
            ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
             '-f', 'concat', '-safe', '0', '-i', str(lista), '-c:a', 'libmp3lame',
             '-b:a', '48k', str(combinado)], check=True)
        if not combinado.exists() or combinado.stat().st_size < 1000:
            raise RuntimeError('MP3 final vacío')
        duracion = duracion_mp3(combinado)
        if duracion < 10:
            raise RuntimeError('Duración del MP3 final anormalmente corta')
        # Solo sustituir el MP3 publicado después de comprobar todos los fragmentos.
        temporal = Path('periodico_nuevo.mp3')
        shutil.copyfile(combinado, temporal)
        temporal.replace('periodico.mp3')
        print(f'Audio completo: {duracion/60:.1f} minutos.')

    pagina = Path('index.html')
    contenido = pagina.read_text(encoding='utf-8')
    reproductor = '''<section class="audio-paper" aria-label="Escuchar el periódico">
<style>.audio-paper{max-width:900px;margin:18px auto;padding:18px 22px;background:#eaf0ee;border:1px solid #c8d7d2;border-radius:12px;color:#183b40;font-family:Arial,sans-serif}.audio-paper h2{font-size:20px;margin:0 0 8px}.audio-paper p{font-size:14px;line-height:1.5}.audio-paper audio{width:100%}</style>
<h2>🎧 Escucha El café de la actualidad</h2>
<p>Noticias narradas con voz femenina española. Reproducción continua; puedes pausar o cambiar la velocidad desde el reproductor.</p>
<audio controls preload="none" src="periodico.mp3?v=__VERSION__">Tu navegador no admite audio HTML5.</audio>
<p><a href="periodico.mp3?v=__VERSION__" download="El_cafe_de_la_actualidad.mp3">Descargar el audio MP3</a></p></section>'''
    version = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    reproductor = reproductor.replace('__VERSION__', version)
    if '<main>' not in contenido:
        raise RuntimeError('No se encuentra la sección principal HTML')
    pagina.write_text(contenido.replace('<main>', reproductor + '<main>', 1), encoding='utf-8')
    print('Audio MP3 y reproductor creados correctamente.')


if __name__ == '__main__':
    asyncio.run(main())
