"""Suggestion-only OCR adapters. Recognition never approves a reading."""
import base64
from decimal import Decimal
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import httpx
from .imaging import image_bytes


def parse_digits(data):
    if not isinstance(data, dict):
        raise ValueError('A felismerő válasza nem JSON objektum.')
    integer = data.get('integer_digits')
    decimal = data.get('decimal_digits')
    uncertain = data.get('uncertain_positions', [])
    if not isinstance(integer, str) or not re.fullmatch(r'[0-9]{1,5}', integer) or not isinstance(decimal, str) or not re.fullmatch(r'[0-9]{1,3}', decimal):
        raise ValueError('A felismerés nem adott érvényes egész és tizedes számjegysort.')
    if not isinstance(uncertain, list) or any(type(v) is not int or v < 0 or v >= len(integer) + len(decimal) for v in uncertain):
        raise ValueError('Érvénytelen bizonytalansági jelölés.')
    return {'integer_digits': integer, 'decimal_digits': decimal, 'value': str(Decimal(integer + '.' + decimal)), 'uncertain_positions': uncertain, 'needs_review': True, 'errors': []}


def recognize_image(path, crop=None, config=None):
    config = config or {}
    mode = config.get('mode', 'manual')
    result = {'integer_digits': None, 'decimal_digits': None, 'value': None, 'uncertain_positions': [], 'needs_review': True, 'crop': crop, 'method': mode, 'errors': []}
    payload = image_bytes(path, crop)
    if mode == 'manual':
        result['errors'] = ['Kézi leolvasás szükséges.']
        return result
    if mode == 'local':
        # On the Mac use both local OCR engines for a user-selected display.
        # A proposed value is returned only when one engine has a strict
        # reading and the other has none, or when the engines agree exactly.
        backends = ['apple'] if platform.system() == 'Darwin' else []
        if crop is not None and shutil.which('tesseract'):
            backends.append('tesseract')
        if not backends:
            backends = ['tesseract']
        proposals = [
            recognize_image(path, crop=crop, config={**config, 'mode': backend})
            for backend in backends
        ]
        accepted = [proposal for proposal in proposals if proposal['value'] is not None]
        if len(accepted) == 1:
            accepted[0]['method'] = 'local:' + accepted[0]['method']
            return accepted[0]
        if len(accepted) == 2 and accepted[0]['value'] == accepted[1]['value']:
            accepted[0]['method'] = 'local:consensus'
            return accepted[0]
        result['errors'] = ['Nincs egyértelmű mérőállás; jelöld ki szorosan a számlálóablakot, vagy olvasd le kézzel a képet.']
        return result
    try:
        if mode in ('apple', 'tesseract'):
            if crop is None and mode == 'tesseract':
                raise ValueError('Helyi felismeréshez jelölje ki a számlálóablakot; a gyári szám félrevezető lehet.')
            with tempfile.TemporaryDirectory(prefix='gasphoto-ocr-') as folder:
                input_path = Path(folder) / 'crop.jpg'
                input_path.write_bytes(payload)
                if mode == 'apple':
                    swift = shutil.which('swift')
                    if not swift:
                        raise ValueError('Az Apple helyi felismerő nem érhető el.')
                    command = [swift, '-module-cache-path', str(Path(folder) / 'cache'), str(Path(__file__).with_name('ocr.swift')), str(input_path)]
                else:
                    executable = shutil.which('tesseract')
                    if not executable:
                        raise ValueError('A Tesseract helyi felismerő nincs telepítve.')
                    command = [executable, str(input_path), 'stdout', '--psm', '7', '-c', 'tessedit_char_whitelist=0123456789.,']
                response = subprocess.run(command, capture_output=True, text=True, check=True, timeout=90)
                text = '\n'.join(json.loads(response.stdout)) if mode == 'apple' else response.stdout
            # Technical labels on the meter often contain a value such as
            # ``Qt 0,600 m³/h``.  Accept only an OCR line consisting solely
            # of a register-shaped number, never a number embedded in text.
            candidates = []
            for line in text.splitlines():
                match = re.fullmatch(r'\s*([0-9]{1,5})[.,]([0-9]{3})\s*', line)
                if match:
                    candidates.append(match.groups())
            # This meter has five black whole-metre rollers.  Requiring all
            # five also excludes labels such as Qt 0,600 m³/h.
            candidates = [candidate for candidate in candidates if len(candidate[0]) == 5]
            if len(candidates) != 1:
                raise ValueError('Nincs egyértelmű mérőállás; olvassa le kézzel a képet.')
            result.update(parse_digits({'integer_digits': candidates[0][0], 'decimal_digits': candidates[0][1]}))
        elif mode == 'vision':
            # A távoli vision szolgáltató csak a felhasználó által kijelölt
            # mérőablakot kaphatja meg. A teljes fotó gyári számot és egyéb
            # környezeti adatot is tartalmazhat; ilyen esetben kézi ellenőrzés.
            if crop is None:
                raise ValueError('Távoli felismeréshez előbb jelölje ki a számlálóablakot; teljes fotó nem tölthető fel.')
            base = config.get('base_url', '').rstrip('/')
            if not base or not config.get('model') or not config.get('api_key'):
                raise ValueError('A vision szolgáltató beállítása hiányos.')
            body = {'model': config['model'], 'temperature': 0, 'max_tokens': 250, 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Read only the mechanical gas meter register, never serial numbers. Return JSON only: {"integer_digits":"00000","decimal_digits":"000","uncertain_positions":[]}. Preserve leading zeroes. Mark ambiguous rolling digits by zero-based positions. If unreadable return null digit strings. Never infer digits from consumption.'}, {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(payload).decode()}}]}]}
            with httpx.Client(timeout=45, follow_redirects=False) as client:
                response = client.post(base + '/chat/completions', headers={'Authorization': 'Bearer ' + config['api_key']}, json=body)
                response.raise_for_status()
                content = response.json()['choices'][0]['message']['content']
                result.update(parse_digits(json.loads(content)))
        else:
            raise ValueError('Ismeretlen felismerési mód.')
    except ValueError as exc:
        result['errors'] = [str(exc) if str(exc).startswith(('A ', 'Az ', 'Helyi ', 'Nincs ', 'Érvénytelen ', 'Ismeretlen ')) else 'A felismerő válasza nem értelmezhető.']
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or '').strip()
        if mode == 'apple' and detail:
            result['errors'] = ['A Mac Apple Vision felismerője nem futott le; indítsd a start.command fájlt közvetlenül a Macen.']
        else:
            result['errors'] = ['A helyi felismerő nem futott le; ellenőrizd a telepítést vagy olvasd le kézzel.']
    except (OSError, subprocess.SubprocessError, httpx.HTTPError, KeyError, IndexError, TypeError):
        result['errors'] = ['A felismerés sikertelen; ellenőrizd a szolgáltató beállítását vagy olvasd le kézzel.']
    result['method'] = mode
    return result
