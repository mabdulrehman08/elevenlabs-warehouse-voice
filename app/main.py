import base64
import logging
import os
import re
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.agent import INVENTORY, answer

load_dotenv()
app = FastAPI(title='Northstar Floor Voice')
ROOT = Path(__file__).parent.parent
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
log = logging.getLogger('uvicorn.error')


class Query(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    context: dict = Field(default_factory=dict)
    speak: bool = True


async def eleven(path, **kwargs):
    key = os.getenv('ELEVENLABS_API_KEY')
    if not key:
        raise HTTPException(503, 'Voice is not configured. Set ELEVENLABS_API_KEY; typed inventory queries still work.')
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post('https://api.elevenlabs.io/v1/' + path, headers={'xi-api-key': key}, **kwargs)
        if response.status_code >= 400:
            messages = {401: 'ElevenLabs rejected the API key.', 403: 'ElevenLabs access denied. Check key permissions and voice access.', 429: 'ElevenLabs quota or rate limit reached. Wait and try again.'}
            raise HTTPException(502, messages.get(response.status_code, 'ElevenLabs is unavailable. Try again or use typed queries.'))
        return response
    except httpx.InvalidURL as exc:
        raise HTTPException(502, 'Voice connection configuration is invalid. Check server proxy settings.') from exc
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        raise HTTPException(502, 'Voice connection timed out or failed. Try again or use typed queries.') from exc


@app.get('/')
def home():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/api/status')
def status():
    return {'voice_configured': bool(os.getenv('ELEVENLABS_API_KEY')), 'warehouse': INVENTORY['warehouse'], 'snapshot': INVENTORY['snapshot']}


@app.post('/api/transcribe')
async def transcribe(file: UploadFile = File(...)):
    if file.content_type not in {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/mpeg'}:
        raise HTTPException(415, 'Use WebM, Ogg, MP4, WAV, or MP3 audio.')
    content = await file.read(4 * 1024 * 1024 + 1)
    if not content or len(content) > 4 * 1024 * 1024:
        raise HTTPException(413, 'Audio must be nonempty and under 4 MB. Keep queries under 12 seconds.')
    response = await eleven('speech-to-text', files={'file': ('query.' + file.content_type.split('/')[1], content, file.content_type)}, data={'model_id': os.getenv('ELEVENLABS_STT_MODEL', 'scribe_v2'), 'language_code': 'en', 'tag_audio_events': 'false'})
    try:
        text = response.json()['text'].strip()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(502, 'Transcription returned an invalid response. Please try again.')
    if not text:
        raise HTTPException(422, 'No speech detected. Move closer to the microphone and try again.')
    return {'text': text}


@app.post('/api/query')
async def query(body: Query):
    started = time.monotonic()
    result = answer(body.text, body.context)
    result['request_id'] = uuid.uuid4().hex[:12]
    result['audio'] = None
    if body.speak:
        voice = os.getenv('ELEVENLABS_VOICE_ID', 'JBFqnCBsd6RMkjVDRZzb')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', voice):
            result['voice_error'] = 'Invalid ELEVENLABS_VOICE_ID configuration.'
        else:
            # Spell identifiers to reduce swallowed SKU digits and bin punctuation.
            spoken = re.sub(r'SKU-(\d+)', lambda m: 'S K U ' + ' '.join(m[1]), result['reply'])
            spoken = re.sub(r'\b\d{2}-[A-Z]-\d{2}\b', lambda m: ' '.join(m[0].replace('-', ' ')), spoken)
            try:
                response = await eleven(f'text-to-speech/{voice}?output_format=mp3_44100_128', json={'text': spoken, 'model_id': os.getenv('ELEVENLABS_TTS_MODEL', 'eleven_flash_v2_5')})
                if not response.headers.get('content-type', '').startswith('audio/') or not response.content:
                    raise HTTPException(502, 'Speech service returned invalid audio.')
                result['audio'] = base64.b64encode(response.content).decode()
            except HTTPException as exc:
                result['voice_error'] = exc.detail
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    log.info('inventory_turn request_id=%s status=%s elapsed_ms=%s', result['request_id'], result['status'], result['elapsed_ms'])
    return result
