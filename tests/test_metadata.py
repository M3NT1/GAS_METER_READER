from datetime import datetime, timezone
from PIL import Image
from gasphoto.metadata import extract_metadata, parse_capture_time


def test_nested_original_preserves_offset_subseconds(tmp_path, monkeypatch):
    monkeypatch.setattr('gasphoto.metadata.shutil.which', lambda _: None)
    path = tmp_path / 'test.jpg'
    exif = Image.Exif()
    exif[34665] = {36867: '2026:03:18 22:43:42', 36881: '+01:00', 37521: '865'}
    Image.new('RGB', (12, 18)).save(path, exif=exif)
    result = extract_metadata(path)
    assert result['captured_at'] == '2026-03-18T22:43:42.865+01:00'
    assert result['captured_at_utc'] == '2026-03-18T21:43:42.865+00:00'
    assert result['raw']['SubSecTimeOriginal'] == '865'


def test_no_file_date_fallback(tmp_path):
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (12, 18)).save(path)
    assert extract_metadata(path)['captured_at'] is None


def test_invalid_missing_offset_and_future_time_blocked():
    for fields in [
        {'DateTimeOriginal': '2026:02:30 12:00:00', 'OffsetTimeOriginal': '+01:00'},
        {'DateTimeOriginal': '2026:03:18 22:43:42'},
        {'DateTimeOriginal': '2099:03:18 22:43:42', 'OffsetTimeOriginal': '+01:00'},
    ]:
        result = parse_capture_time(fields)
        assert result['captured_at'] is None
        assert result['errors']


def test_utc_underflow_is_invalid_metadata():
    result = parse_capture_time({'DateTimeOriginal': '0001:01:01 00:00:00', 'OffsetTimeOriginal': '+01:00'})
    assert result['captured_at'] is None
    assert result['errors']
