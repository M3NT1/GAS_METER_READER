"""Original capture metadata; filesystem dates are deliberately never consulted."""
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import shutil
import subprocess
from PIL import Image
from .imaging import register_heif

TAGS = {36867: 'DateTimeOriginal', 36881: 'OffsetTimeOriginal', 37521: 'SubSecTimeOriginal', 271: 'Make', 272: 'Model'}


def parse_capture_time(raw: dict) -> dict:
    result = {'raw': raw, 'captured_at': None, 'captured_at_utc': None, 'errors': [], 'precision': None}
    try:
        date = raw.get('DateTimeOriginal', '')
        offset = raw.get('OffsetTimeOriginal', '')
        sub = str(raw.get('SubSecTimeOriginal', '')).strip()
        if not isinstance(date, str) or not re.fullmatch(r'\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}', date):
            raise ValueError('Hiányzó vagy hibás eredeti készítési idő.')
        if not isinstance(offset, str) or not re.fullmatch(r'[+-](?:0\d|1[0-4]):[0-5]\d', offset) or (offset[1:3] == '14' and offset[4:] != '00'):
            raise ValueError('Hiányzó vagy hibás eredeti időzóna; kézi ellenőrzés szükséges.')
        if sub and not re.fullmatch(r'[0-9]{1,9}', sub):
            raise ValueError('Hibás EXIF másodperctört.')
        base = datetime.strptime(date, '%Y:%m:%d %H:%M:%S').isoformat()
        iso = base + ('.' + sub if sub else '') + offset
        parsed = datetime.fromisoformat(iso)
        if parsed > datetime.now(timezone.utc):
            raise ValueError('Jövőbeli készítési idő; kézi ellenőrzés szükséges.')
        utc_base = parsed.astimezone(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S')
        result.update(captured_at=iso, captured_at_utc=utc_base + ('.' + sub if sub else '') + '+00:00', precision='fractional_second' if sub else 'second')
    except (ValueError, TypeError, OverflowError) as exc:
        result['errors'].append(str(exc) if str(exc).startswith(('Hiányzó', 'Hibás', 'Jövőbeli')) else 'Érvénytelen eredeti készítési idő.')
    return result


def extract_metadata(path: Path) -> dict:
    raw = {}
    source = 'pillow_exif'
    if shutil.which('exiftool'):
        try:
            completed = subprocess.run(['exiftool', '-j', '-s', '-DateTimeOriginal', '-OffsetTimeOriginal', '-SubSecTimeOriginal', '-Make', '-Model', str(Path(path).absolute())], capture_output=True, timeout=20, check=True)
            raw = {k: str(v) for k, v in json.loads(completed.stdout)[0].items() if k in TAGS.values()}
            source = 'exiftool'
        except (subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError):
            raw = {}
    if not raw:
        try:
            register_heif()
            with Image.open(path) as image:
                exif = image.getexif()
                nested = exif.get_ifd(34665) if 34665 in exif else {}
                for tag, name in TAGS.items():
                    value = nested.get(tag, exif.get(tag))
                    if value is not None:
                        raw[name] = value.decode('utf-8', errors='replace').strip('\x00') if isinstance(value, bytes) else str(value)
        except (OSError, ValueError, SyntaxError):
            result = parse_capture_time(raw)
            result['errors'].append('A kép metaadatai nem olvashatók.')
            result['source'] = source
            return result
    return dict(parse_capture_time(raw), source=source)
