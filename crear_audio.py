"""Genera audio de una edición RSS; falla sin impedir publicar el periódico."""
import asyncio
import html
from pathlib import Path
import re

import edge_tts

VOICE = 'es-ES-ElviraNeural'
RATE = '-5%'

async def main():
    script = Path('guion_audio.txt').read_text(encoding='utf-8').strip()
    if not script:
        raise RuntimeError('Guion vacío')
    # Edge TTS gestiona el texto como una única locución; si falla, no se publica MP3 parcial.
    temp = Path('periodico_nuevo.mp3')
    try:
        await edge_tts.Communicate(script, VOICE, rate=RATE).save(str(temp))
        if temp.stat().st_size < 1000:
            raise RuntimeError('Audio incompleto')
        temp.replace('periodico.mp3')
    finally:
        temp.unlink(missing_ok=True)
    page = Path('index.html')
    content = page.read_text(encoding='utf-8')
    player = '''<section class="audio-paper" aria-label="Escuchar el periódico">
<style>.audio-paper{max-width:900px;margin:18px auto;padding:18px 22px;background:#eaf0ee;border:1px solid #c8d7d2;border-radius:12px;color:#183b40;font-family:Arial,sans-serif}.audio-paper h2{font-size:20px;margin:0 0 8px}.audio-paper p{font-size:14px;line-height:1.5}.audio-paper audio{width:100%}</style>
<h2>🎧 Escucha El café de la actualidad</h2>
<p>Noticias narradas con voz femenina española. Reproducción continua; puedes pausar o cambiar la velocidad desde el reproductor.</p>
<audio controls preload="none" src="periodico.mp3?v=__VERSION__">Tu navegador no admite audio HTML5.</audio>
<p><a href="periodico.mp3?v=__VERSION__" download="El_cafe_de_la_actualidad.mp3">Descargar el audio MP3</a></p></section>'''
    import datetime
    version = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    player = player.replace('__VERSION__', version)
    if '<main>' not in content:
        raise RuntimeError('No se encuentra la sección principal HTML')
    page.write_text(content.replace('<main>', player + '<main>', 1), encoding='utf-8')
    print('Audio MP3 y reproductor creados correctamente.')

if __name__ == '__main__':
    asyncio.run(main())
