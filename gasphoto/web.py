"""Local review application. Provider credentials never reach the browser."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .store import Store
from .pipeline import Pipeline
from .ha_client import HAClient


class Approval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: str = Field(max_length=16)
    captured_at: str | None = Field(default=None, max_length=40)


class Recognition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    crop: list[float] | None = None


class TrainingExample(BaseModel):
    model_config = ConfigDict(extra='forbid')
    window_quad: list[list[float]]
    value: str = Field(max_length=16)
    decision: str = Field(pattern='^(approved|corrected)$')


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    inbox: str = Field(max_length=4096)


def create_app(data_dir: Path | str, *, watch=True):
    data = Path(data_dir).resolve()
    data.mkdir(parents=True, exist_ok=True)
    (data / 'inbox').mkdir(exist_ok=True)
    settings_file = data / 'settings.json'
    settings = {'inbox': str(data / 'inbox')}
    if settings_file.exists():
        settings.update(json.loads(settings_file.read_text()))
    store = Store(data / 'readings.sqlite3')
    recognition = {
        'mode': os.getenv('GASPHOTO_OCR', 'local'),
        'base_url': os.getenv('VISION_BASE_URL', ''),
        'api_key': os.getenv('VISION_API_KEY', ''),
        'model': os.getenv('VISION_MODEL', ''),
    }
    pipeline = Pipeline(store, data, Path(settings['inbox']), recognition_config=recognition)
    gate = threading.Lock()
    token = secrets.token_urlsafe(32)
    activity = {'busy': False, 'last_scan': None, 'error': None}
    training_activity = {'state': 'collecting', 'epoch': 0, 'epochs': 60, 'error': None, 'log': ''}
    training_lock = threading.Lock()
    digit_training_activity = {'state': 'collecting', 'epoch': 0, 'epochs': 80, 'error': None, 'log': ''}
    digit_training_lock = threading.Lock()

    def training_status():
        examples = len(store.training_examples())
        status = dict(training_activity)
        status.update({'examples': examples, 'minimum_examples': 40})
        if status['state'] == 'collecting' and examples >= 40:
            status['state'] = 'ready'
        return status

    def digit_training_status():
        examples = len(store.training_examples())
        status = dict(digit_training_activity)
        status.update({'examples': examples, 'minimum_examples': 40})
        if status['state'] == 'collecting' and examples >= 40:
            status['state'] = 'ready'
        evaluation_path = data / 'models' / 'digit-classifier' / 'evaluation.json'
        active_path = data / 'models' / 'digit-classifier' / 'weights' / 'active.onnx'
        if evaluation_path.exists():
            evaluation = json.loads(evaluation_path.read_text())
            status['evaluation'] = evaluation
            status['activated'] = active_path.exists()
        else:
            status['evaluation'] = None
            status['activated'] = False
        if status['state'] == 'ready' and status['activated']:
            status['state'] = 'completed'
        if status['state'] == 'ready' and status['evaluation'] and not status['activated']:
            status.update(state='rejected', error=f"A külön teszt pontossága {evaluation['top1']:.1%}; további tanítóképek szükségesek.")
        return status

    def run_training():
        root = Path(__file__).parent.parent
        dataset = data / 'training' / 'window-v1'
        model_dir = data / 'models'
        log_path = data / 'training' / 'window-training.log'
        try:
            training_activity.update(state='preparing', error=None, log='Tanítóhalmaz exportálása…', epoch=0)
            subprocess.run([sys.executable, str(root / 'scripts' / 'export_window_dataset.py'), str(store.db_path), str(dataset)], cwd=root, check=True, capture_output=True, text=True)
            training_activity.update(state='running', log='A számlálóablak-detektor tanítása elindult…')
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open('w') as log:
                process = subprocess.Popen([sys.executable, str(root / 'scripts' / 'train_window_detector.py'), str(dataset), str(model_dir)], cwd=root, stdout=log, stderr=subprocess.STDOUT, text=True)
                while process.poll() is None:
                    results = model_dir / 'window-detector' / 'results.csv'
                    if results.exists():
                        lines = results.read_text().strip().splitlines()
                        if len(lines) > 1:
                            training_activity['epoch'] = int(lines[-1].split(',')[0]) + 1
                    training_activity['log'] = log_path.read_text(errors='replace')[-5000:]
                    time.sleep(2)
                training_activity['log'] = log_path.read_text(errors='replace')[-5000:]
                if process.returncode:
                    raise RuntimeError('A tanító folyamat hibával állt le.')
            training_activity.update(state='completed', epoch=60)
        except Exception as exc:
            training_activity.update(state='failed', error=str(exc))
        finally:
            training_lock.release()

    def run_digit_training():
        root = Path(__file__).parent.parent
        dataset = data / 'training' / 'digit-v1'
        model_dir = data / 'models'
        log_path = data / 'training' / 'digit-training.log'
        try:
            digit_training_activity.update(state='preparing', error=None, log='Számjegytanító halmaz exportálása…', epoch=0)
            subprocess.run([sys.executable, str(root / 'scripts' / 'export_digit_dataset.py'), str(store.db_path), str(dataset)], cwd=root, check=True, capture_output=True, text=True)
            digit_training_activity.update(state='running', log='A számláló számjegyolvasó tanítása elindult…')
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open('w') as log:
                process = subprocess.Popen([sys.executable, str(root / 'scripts' / 'train_digit_classifier.py'), str(dataset), str(model_dir)], cwd=root, stdout=log, stderr=subprocess.STDOUT, text=True)
                while process.poll() is None:
                    results = model_dir / 'digit-classifier' / 'results.csv'
                    if results.exists():
                        lines = results.read_text().strip().splitlines()
                        if len(lines) > 1:
                            digit_training_activity['epoch'] = int(lines[-1].split(',')[0]) + 1
                    digit_training_activity['log'] = log_path.read_text(errors='replace')[-5000:]
                    time.sleep(2)
                digit_training_activity['log'] = log_path.read_text(errors='replace')[-5000:]
                if process.returncode:
                    raise RuntimeError('A számjegymodell tanítása hibával állt le.')
            from ultralytics import YOLO
            model_path = model_dir / 'digit-classifier' / 'weights' / 'best.onnx'
            evaluation = YOLO(str(model_path)).val(data=str(dataset), split='test', imgsz=128, batch=32)
            top1 = float(evaluation.results_dict.get('metrics/accuracy_top1', 0))
            evaluation_path = model_dir / 'digit-classifier' / 'evaluation.json'
            evaluation_path.write_text(json.dumps({'top1': top1}, ensure_ascii=False))
            if top1 < .90:
                digit_training_activity.update(state='rejected', epoch=80, error=f'A külön teszt pontossága {top1:.1%}; további tanítóképek szükségesek.')
            else:
                shutil.copy2(model_path, model_path.with_name('active.onnx'))
                digit_training_activity.update(state='completed', epoch=80)
        except Exception as exc:
            digit_training_activity.update(state='failed', error=str(exc))
        finally:
            digit_training_lock.release()

    def scan_and_propose():
        if not gate.acquire(blocking=False):
            return {'busy': True}
        activity['busy'] = True
        try:
            result = pipeline.scan()
            activity['last_scan'] = result
            activity['error'] = None
            for row in store.list_photos():
                if row.get('proposal') is None and row['status'] not in ('synced', 'pending_sync'):
                    try:
                        pipeline.recognize(row['id'])
                    except Exception:
                        store.set_proposal(row['id'], {'value': None, 'needs_review': True}, error='A felismerés nem sikerült. Jelöld ki a számlálót, vagy add meg az értéket.')
            return result
        except Exception:
            activity['error'] = 'A mappa feldolgozása nem sikerült. Ellenőrizd, hogy elérhető és olvasható.'
            return {'error': activity['error']}
        finally:
            activity['busy'] = False
            gate.release()

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()

        async def worker():
            while not stop.is_set():
                await asyncio.to_thread(scan_and_propose)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=20)
                except TimeoutError:
                    pass
        task = asyncio.create_task(worker()) if watch else None
        yield
        stop.set()
        if task:
            await task

    app = FastAPI(title='Gázóra · Fotónapló', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])
    app.state.store = store
    app.state.pipeline = pipeline

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Csak a helyi alkalmazásból használható.'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not secrets.compare_digest(request.headers.get('x-session-token', ''), token):
            return JSONResponse({'detail': 'Frissítsd az oldalt, majd próbáld újra.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def invalid_value(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    static = Path(__file__).parent / 'static'

    @app.get('/')
    def index():
        return FileResponse(static / 'index.html')

    @app.get('/api/status')
    def status():
        return {'session_token': token, 'inbox': settings['inbox'], 'ocr': recognition['mode'],
                'ha_configured': bool(os.getenv('HA_URL') and os.getenv('HA_TOKEN')),
                'auto_accept': False, 'watch': watch, 'activity': activity,
                'training': training_status(), 'digit_training': digit_training_status(),
                'tools': {'exiftool': bool(shutil.which('exiftool')), 'tesseract': bool(shutil.which('tesseract')), 'swift': bool(shutil.which('swift'))}}

    @app.get('/api/photos')
    def photos():
        return {'photos': store.list_photos()}

    @app.post('/api/scan')
    def scan():
        return scan_and_propose()

    @app.post('/api/settings')
    def update_settings(value: Settings):
        inbox = Path(value.inbox).expanduser().resolve()
        if not inbox.is_dir():
            raise ValueError('A kiválasztott mappa nem létezik.')
        if inbox == data or inbox in (data / 'archive', data / 'previews'):
            raise ValueError('Válassz külön bemeneti mappát, ne az alkalmazás archívumát.')
        with gate:
            settings['inbox'] = str(inbox)
            temporary = settings_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(settings, ensure_ascii=False))
            temporary.replace(settings_file)
            pipeline.inbox = inbox
        return {'inbox': str(inbox)}

    def require_photo(photo_id):
        if len(photo_id) != 64 or any(c not in '0123456789abcdef' for c in photo_id):
            raise HTTPException(404, 'Nincs ilyen fotó.')
        row = store.get_photo(photo_id)
        if row is None:
            raise HTTPException(404, 'Nincs ilyen fotó.')
        return row

    @app.get('/api/photos/{photo_id}/preview')
    def preview(photo_id: str):
        require_photo(photo_id)
        return FileResponse(pipeline.preview_path(photo_id), media_type='image/jpeg')

    @app.post('/api/photos/{photo_id}/recognize')
    def recognize(photo_id: str, value: Recognition):
        require_photo(photo_id)
        with gate:
            return pipeline.recognize(photo_id, crop=value.crop)

    @app.delete('/api/photos/{photo_id}')
    def discard_photo(photo_id: str):
        require_photo(photo_id)
        with gate:
            return pipeline.discard(photo_id)

    @app.post('/api/photos/{photo_id}/approve')
    def approve(photo_id: str, value: Approval):
        row = require_photo(photo_id)
        if row['status'] == 'synced' and value.captured_at and value.captured_at != row['captured_at']:
            raise ValueError('Már szinkronizált fotó időpontja itt nem módosítható.')
        with gate:
            return store.approve(photo_id, value.value, captured_at=value.captured_at)

    @app.get('/api/photos/{photo_id}/training-example')
    def training_example(photo_id: str):
        require_photo(photo_id)
        return store.training_example(photo_id) or {}

    @app.post('/api/photos/{photo_id}/training-example')
    def save_training_example(photo_id: str, value: TrainingExample):
        require_photo(photo_id)
        with gate:
            return store.record_training_example(
                photo_id, value.window_quad, value.value, value.decision
            )

    @app.post('/api/training/start')
    def start_training():
        status = training_status()
        if status['examples'] < 40:
            raise ValueError('A tanításhoz legalább 40 ellenőrzött fotó szükséges.')
        if not training_lock.acquire(blocking=False):
            raise ValueError('A modell tanítása már folyamatban van.')
        threading.Thread(target=run_training, daemon=True).start()
        return training_status()

    @app.post('/api/training/digits/start')
    def start_digit_training():
        status = digit_training_status()
        if status['examples'] < 40:
            raise ValueError('A tanításhoz legalább 40 ellenőrzött fotó szükséges.')
        if not digit_training_lock.acquire(blocking=False):
            raise ValueError('A számlálómodell tanítása már folyamatban van.')
        threading.Thread(target=run_digit_training, daemon=True).start()
        return digit_training_status()

    @app.post('/api/ha/check')
    def ha_check():
        with HAClient(os.getenv('HA_URL', ''), os.getenv('HA_TOKEN', '')) as client:
            return client.check()

    @app.post('/api/sync')
    def sync():
        if not os.getenv('HA_URL') or not os.getenv('HA_TOKEN'):
            raise ValueError('A HA-kapcsolat nincs beállítva. A jóváhagyott leolvasások biztonságban vannak a helyi várólistán.')
        with gate:
            pending = sorted(store.pending_readings(), key=lambda r: r['captured_at'])
            synced = 0
            with HAClient(os.environ['HA_URL'], os.environ['HA_TOKEN']) as client:
                for offset in range(0, len(pending), 100):
                    batch = pending[offset:offset + 100]
                    try:
                        accepted = client.send(batch)
                    except ValueError as exc:
                        for row in batch:
                            store.set_sync_error(row['id'], str(exc))
                        raise
                    for photo_id, revision in accepted:
                        if store.mark_synced(photo_id, revision):
                            synced += 1
            return {'synced': synced, 'statistics_status': 'Az órás statisztika a HA feldolgozási sorába kerül; a pontos napló visszaolvasva.'}

    app.mount('/static', StaticFiles(directory=static, check_dir=False), name='static')
    return app
