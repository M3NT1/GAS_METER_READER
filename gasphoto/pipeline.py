"""Bounded, immutable inbox ingestion and persistent review proposals."""
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
from .metadata import extract_metadata
from .imaging import image_bytes
from .digits import recognize_register_digits
from .ml import detect_register_window
from .recognition import recognize_image

MAX_BYTES = 30 * 1024 * 1024


class Pipeline:
    def __init__(self, store, data_dir: Path, inbox: Path, recognition_config: dict | None = None):
        self.store = store
        self.data_dir = Path(data_dir)
        self.inbox = Path(inbox)
        self.recognition_config = recognition_config or {}
        self._lock = threading.Lock()

    def scan(self):
        result = {'added': 0, 'duplicates': 0, 'skipped': 0, 'errors': []}
        with self._lock:
            if not self.inbox.is_dir():
                result['errors'].append('A bemeneti mappa nem található.')
                return result
            archive = self.data_dir / 'originals'
            archive.mkdir(parents=True, exist_ok=True)
            for path in self.inbox.iterdir():
                if path.suffix.lower() not in ('.jpg', '.jpeg', '.heic', '.heif'):
                    continue
                try:
                    before = path.lstat()
                    if not stat.S_ISREG(before.st_mode) or before.st_size == 0 or before.st_size > MAX_BYTES or getattr(before, 'st_flags', 0) & 0x40000000 or time.time() - before.st_mtime < 2:
                        result['skipped'] += 1
                        continue
                    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                    with os.fdopen(fd, 'rb') as source:
                        content = source.read(MAX_BYTES + 1)
                        after = os.fstat(source.fileno())
                    latest = path.lstat()
                    signature = lambda s: (s.st_ino, s.st_size, s.st_mtime_ns)
                    if signature(before) != signature(after) or signature(before) != signature(latest) or len(content) != before.st_size:
                        result['skipped'] += 1
                        continue
                    photo_id = hashlib.sha256(content).hexdigest()
                    if self.store.get_photo(photo_id):
                        result['duplicates'] += 1
                        continue
                    with tempfile.NamedTemporaryFile(dir=archive, suffix=path.suffix.lower(), delete=False) as tmp:
                        temporary = Path(tmp.name)
                        tmp.write(content)
                        tmp.flush()
                        os.fsync(tmp.fileno())
                    try:
                        metadata = extract_metadata(temporary)
                        image_bytes(temporary)  # A fully decodable image is required before archival.
                        if signature(path.lstat()) != signature(before):
                            result['skipped'] += 1
                            continue
                        destination = archive / (photo_id + path.suffix.lower())
                        try:
                            os.link(temporary, destination)
                        except FileExistsError:
                            if hashlib.sha256(destination.read_bytes()).hexdigest() != photo_id:
                                raise ValueError('Az archív fájl tartalma sérült.')
                        destination.chmod(0o444)
                        self.store.add_photo(photo_id, path.name, str(destination.absolute()), metadata['captured_at'], metadata, '; '.join(metadata['errors']) or None)
                        result['added'] += 1
                    finally:
                        temporary.unlink(missing_ok=True)
                except Exception:
                    result['errors'].append(f'{path.name}: a kép nem dolgozható fel.')
        return result

    def _photo(self, photo_id):
        photo = self.store.get_photo(photo_id)
        if not photo:
            raise ValueError('A fotó nem található.')
        return photo

    def preview_path(self, photo_id):
        photo = self._photo(photo_id)
        directory = self.data_dir / 'previews'
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (photo_id + '.jpg')
        if not target.exists():
            payload = image_bytes(photo['archive_path'])
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as tmp:
                temporary = Path(tmp.name)
                tmp.write(payload)
            os.replace(temporary, target)
        return target

    def discard(self, photo_id):
        photo = self._photo(photo_id)
        discarded = self.store.discard(photo_id)
        Path(photo['archive_path']).unlink(missing_ok=True)
        (self.data_dir / 'previews' / (photo_id + '.jpg')).unlink(missing_ok=True)
        return discarded

    def recognize(self, photo_id: str, crop: list[float] | None = None):
        photo = self._photo(photo_id)
        detector = None
        if crop is None:
            detector = detect_register_window(photo['archive_path'], self.data_dir)
            if detector:
                crop = detector['crop']
        proposal = recognize_register_digits(photo['archive_path'], crop, self.data_dir)
        if proposal is None:
            proposal = recognize_image(photo['archive_path'], crop=crop, config=self.recognition_config)
        if detector:
            proposal['detector'] = detector
            if proposal.get('value') is None:
                uncertain = proposal.get('uncertain_positions', [])
                predictions = proposal.get('digit_predictions', [])
                if uncertain and predictions:
                    rollers = ', '.join(str(index + 1) + '.' for index in uncertain)
                    suggested = ', '.join(predictions[index] for index in uncertain)
                    proposal['errors'] = [f'A számlálómodell a {rollers} görgőn bizonytalan (javaslat: {suggested}). Ellenőrizd vagy írd be kézzel az értéket.']
                else:
                    proposal['errors'] = ['A számlálóablakot megtaláltam. Ellenőrizd a zöld keretet; az értéket kézzel is megadhatod.']
        self.store.set_proposal(photo_id, proposal, error='; '.join(proposal['errors']) or None)
        return proposal
