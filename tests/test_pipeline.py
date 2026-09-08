import os
from PIL import Image
from gasphoto.pipeline import Pipeline


class MemoryStore:
    def __init__(self): self.rows = {}
    def add_photo(self, id, filename, archive_path, captured_at, metadata, error=None):
        self.rows.setdefault(id, dict(id=id, filename=filename, archive_path=str(archive_path), captured_at=captured_at, metadata=metadata, error=error))
    def list_photos(self): return list(self.rows.values())
    def get_photo(self, id): return self.rows.get(id)
    def set_proposal(self, id, proposal, error=None): self.rows[id].update(proposal=proposal, error=error)
    def discard(self, id): return self.rows.pop(id)


def test_ingestion_deduplicates_archives_and_manual_proposal(tmp_path):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    path = inbox / 'first.jpg'
    Image.new('RGB', (80, 60)).save(path)
    original = path.read_bytes()
    os.utime(path, (1, 1))
    store = MemoryStore()
    pipeline = Pipeline(store, tmp_path / 'data', inbox)
    assert pipeline.scan()['added'] == 1
    assert pipeline.scan()['duplicates'] == 1
    row = store.list_photos()[0]
    assert __import__('pathlib').Path(row['archive_path']).read_bytes() == original
    assert row['captured_at'] is None
    assert pipeline.preview_path(row['id']).exists()
    assert pipeline.recognize(row['id'])['needs_review']


def test_symlink_incomplete_and_invalid_images_not_archived(tmp_path):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    target = tmp_path / 'outside.jpg'
    Image.new('RGB', (10, 10)).save(target)
    (inbox / 'link.jpg').symlink_to(target)
    (inbox / 'broken.jpg').write_bytes(b'broken')
    Image.new('RGB', (10, 10)).save(inbox / 'fresh.jpg')
    result = Pipeline(MemoryStore(), tmp_path / 'data', inbox).scan()
    assert result['added'] == 0
    assert result['skipped'] >= 2


def test_discard_removes_an_unreviewed_photo_and_its_archive(tmp_path):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    source = inbox / 'meter.jpg'
    Image.new('RGB', (80, 60)).save(source)
    os.utime(source, (1, 1))
    store = MemoryStore()
    pipeline = Pipeline(store, tmp_path / 'data', inbox)
    pipeline.scan()
    row = store.list_photos()[0]

    pipeline.discard(row['id'])

    assert store.get_photo(row['id']) is None
    assert not __import__('pathlib').Path(row['archive_path']).exists()


def test_recognize_uses_learned_window_when_user_has_not_drawn_crop(tmp_path, monkeypatch):
    """The learned detector supplies a crop, but never approves the reading."""
    source = tmp_path / 'meter.jpg'
    Image.new('RGB', (100, 100)).save(source)
    store = MemoryStore()
    store.add_photo('photo', 'meter.jpg', source, None, {})
    pipeline = Pipeline(store, tmp_path / 'data', tmp_path)
    detected = {'crop': [.2, .4, .8, .55], 'confidence': .91, 'model': 'window-v1'}
    monkeypatch.setattr('gasphoto.pipeline.detect_register_window', lambda path, data_dir: detected)
    seen = {}
    def recognize(path, crop, config):
        seen['crop'] = crop
        return {'value': None, 'needs_review': True, 'errors': [], 'method': 'local'}
    monkeypatch.setattr('gasphoto.pipeline.recognize_image', recognize)

    result = pipeline.recognize('photo')

    assert seen['crop'] == detected['crop']
    assert result['detector'] == detected
    assert result['needs_review'] is True


def test_detected_window_uses_a_position_review_message_not_generic_ocr_failure(tmp_path, monkeypatch):
    source = tmp_path / 'meter.jpg'
    Image.new('RGB', (100, 100)).save(source)
    store = MemoryStore()
    store.add_photo('photo', 'meter.jpg', source, None, {})
    pipeline = Pipeline(store, tmp_path / 'data', tmp_path)
    monkeypatch.setattr('gasphoto.pipeline.detect_register_window', lambda path, data_dir: {'crop': [.2, .4, .8, .55], 'confidence': .91, 'model': 'window-v1'})
    monkeypatch.setattr('gasphoto.pipeline.recognize_register_digits', lambda *args: None)
    monkeypatch.setattr('gasphoto.pipeline.recognize_image', lambda *args, **kwargs: {'value': None, 'needs_review': True, 'errors': ['Nincs egyértelmű mérőállás; jelöld ki szorosan a számlálóablakot, vagy olvasd le kézzel a képet.'], 'method': 'local'})

    result = pipeline.recognize('photo')

    assert result['errors'] == ['A számlálóablakot megtaláltam. Ellenőrizd a zöld keretet; az értéket kézzel is megadhatod.']


def test_uncertain_digit_diagnostic_is_preserved_after_window_detection(tmp_path, monkeypatch):
    source = tmp_path / 'meter.jpg'
    Image.new('RGB', (100, 100)).save(source)
    store = MemoryStore()
    store.add_photo('photo', 'meter.jpg', source, None, {})
    pipeline = Pipeline(store, tmp_path / 'data', tmp_path)
    monkeypatch.setattr('gasphoto.pipeline.detect_register_window', lambda *args: {'crop': [.2, .4, .8, .55], 'confidence': .91, 'model': 'window-v1'})
    monkeypatch.setattr('gasphoto.pipeline.recognize_register_digits', lambda *args: {'value': None, 'uncertain_positions': [5, 7], 'digit_predictions': ['0', '1', '6', '9', '8', '5', '5', '3'], 'errors': [], 'method': 'digit-classifier', 'needs_review': True})

    result = pipeline.recognize('photo')

    assert result['errors'] == ['A számlálómodell a 6., 8. görgőn bizonytalan (javaslat: 5, 3). Ellenőrizd vagy írd be kézzel az értéket.']


def test_recognize_prefers_the_digit_model_after_the_window_is_found(tmp_path, monkeypatch):
    source = tmp_path / 'meter.jpg'
    Image.new('RGB', (100, 100)).save(source)
    store = MemoryStore()
    store.add_photo('photo', 'meter.jpg', source, None, {})
    pipeline = Pipeline(store, tmp_path / 'data', tmp_path)
    monkeypatch.setattr('gasphoto.pipeline.detect_register_window', lambda path, data_dir: {'crop': [.2, .4, .8, .55], 'confidence': .91, 'model': 'window-v1'})
    monkeypatch.setattr('gasphoto.pipeline.recognize_register_digits', lambda path, crop, data_dir: {'value': '01817.759', 'method': 'digit-classifier', 'errors': [], 'needs_review': True})
    monkeypatch.setattr('gasphoto.pipeline.recognize_image', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Generic OCR should not run')))

    result = pipeline.recognize('photo')

    assert result['value'] == '01817.759'
    assert store.get_photo('photo')['proposal']['method'] == 'digit-classifier'
