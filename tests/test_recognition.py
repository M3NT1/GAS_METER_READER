import pytest
from gasphoto.recognition import parse_digits, recognize_image
from gasphoto.imaging import image_bytes
from PIL import Image


def test_strict_digits_and_leading_zero():
    result = parse_digits({'integer_digits': '00123', 'decimal_digits': '456', 'uncertain_positions': [2]})
    assert result['value'] == '123.456'
    assert result['integer_digits'] == '00123'
    assert result['needs_review'] is True
    for digits in ['123456', '12?45', '１２３', 123]:
        with pytest.raises(ValueError):
            parse_digits({'integer_digits': digits, 'decimal_digits': '456'})


def test_manual_default_and_crop_validation(tmp_path):
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (100, 50)).save(path)
    assert recognize_image(path)['value'] is None
    for crop in [[0, 0, 2, 1], [0.8, 0, 0.2, 1], [0, float('nan'), 1, 1]]:
        with pytest.raises(ValueError):
            image_bytes(path, crop)


def test_preview_oriented_and_stripped(tmp_path):
    from io import BytesIO
    path = tmp_path / 'test.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (100, 50)).save(path, exif=exif)
    with Image.open(BytesIO(image_bytes(path))) as image:
        assert image.size == (50, 100)
        assert not image.getexif()


def test_apple_full_image_ignores_serial_and_accepts_decimal(tmp_path, monkeypatch):
    import subprocess
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (100, 50)).save(path)
    monkeypatch.setattr('gasphoto.recognition.shutil.which', lambda _: '/usr/bin/swift')
    monkeypatch.setattr('gasphoto.recognition.subprocess.run', lambda *a, **k: subprocess.CompletedProcess(a, 0, '["12345678"]', ''))
    assert recognize_image(path, config={'mode': 'apple'})['value'] is None
    monkeypatch.setattr('gasphoto.recognition.subprocess.run', lambda *a, **k: subprocess.CompletedProcess(a, 0, '["00123.456"]', ''))
    assert recognize_image(path, config={'mode': 'apple'})['value'] == '123.456'


def test_meter_specification_is_not_accepted_as_reading(tmp_path, monkeypatch):
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (100, 50)).save(path)
    import subprocess

    monkeypatch.setattr(
        'gasphoto.recognition.shutil.which', lambda _: '/usr/bin/swift'
    )
    monkeypatch.setattr(
        'gasphoto.recognition.subprocess.run',
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, '["Qt 0,600 m3/h", "00123.456"]', ''
        ),
    )
    assert recognize_image(path, config={'mode': 'apple'})['value'] == '123.456'

    monkeypatch.setattr(
        'gasphoto.recognition.subprocess.run',
        lambda *a, **k: subprocess.CompletedProcess(a, 0, '["Qt 0,600m/h"]', ''),
    )
    assert recognize_image(path, config={'mode': 'apple'})['value'] is None


def test_raw_eight_digit_serial_is_not_interpreted_as_a_reading(tmp_path, monkeypatch):
    import subprocess
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (100, 50)).save(path)
    monkeypatch.setattr('gasphoto.recognition.shutil.which', lambda _: '/usr/bin/swift')
    monkeypatch.setattr(
        'gasphoto.recognition.subprocess.run',
        lambda *a, **k: subprocess.CompletedProcess(a, 0, '["08434645"]', ''),
    )
    assert recognize_image(path, crop=[0.2, 0.4, 0.8, 0.7], config={'mode': 'apple'})['value'] is None

    monkeypatch.setattr(
        'gasphoto.recognition.subprocess.run',
        lambda *a, **k: subprocess.CompletedProcess(a, 0, '["Qt 0,600 m3/h"]', ''),
    )
    assert recognize_image(path, config={'mode': 'apple'})['value'] is None


def test_local_uses_tesseract_when_apple_has_no_reading(tmp_path, monkeypatch):
    import subprocess
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (100, 50)).save(path)
    monkeypatch.setattr('gasphoto.recognition.platform.system', lambda: 'Darwin')
    monkeypatch.setattr('gasphoto.recognition.shutil.which', lambda _: '/usr/bin/tool')

    def run(command, **kwargs):
        text = '["unreadable"]' if command[1] == '-module-cache-path' else '00123.456\n'
        return subprocess.CompletedProcess(command, 0, text, '')

    monkeypatch.setattr('gasphoto.recognition.subprocess.run', run)
    result = recognize_image(path, crop=[0.2, 0.2, 0.8, 0.8], config={'mode': 'local'})
    assert result['value'] == '123.456'
    assert result['method'] == 'local:tesseract'


def test_local_rejects_disagreeing_ocr_results(tmp_path, monkeypatch):
    import subprocess
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (100, 50)).save(path)
    monkeypatch.setattr('gasphoto.recognition.platform.system', lambda: 'Darwin')
    monkeypatch.setattr('gasphoto.recognition.shutil.which', lambda _: '/usr/bin/tool')

    def run(command, **kwargs):
        text = '["00123.456"]' if command[1] == '-module-cache-path' else '00124.456\n'
        return subprocess.CompletedProcess(command, 0, text, '')

    monkeypatch.setattr('gasphoto.recognition.subprocess.run', run)
    result = recognize_image(path, crop=[0.2, 0.2, 0.8, 0.8], config={'mode': 'local'})
    assert result['value'] is None


def test_invalid_provider_json_shape_is_review_error(tmp_path, monkeypatch):
    import httpx
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (10, 10)).save(path)
    def response(*args, **kwargs):
        return httpx.Response(200, request=httpx.Request('POST', 'https://example.invalid'), json={'choices': [{'message': {'content': '[]'}}]})
    monkeypatch.setattr(httpx.Client, 'post', response)
    result = recognize_image(path, config={'mode': 'vision', 'base_url': 'https://example.invalid/v1', 'model': 'test', 'api_key': 'test-secret'})
    assert result['value'] is None
    assert result['errors']
    assert 'test-secret' not in str(result)


def test_remote_vision_never_sends_full_photo_without_crop(tmp_path, monkeypatch):
    path = tmp_path / 'test.jpg'
    Image.new('RGB', (10, 10), color='red').save(path)
    calls = []

    def unexpected_post(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('A teljes fotót nem szabad távoli felismerőnek elküldeni.')

    monkeypatch.setattr('httpx.Client.post', unexpected_post)
    result = recognize_image(path, config={
        'mode': 'vision',
        'base_url': 'https://example.invalid/v1',
        'model': 'test',
        'api_key': 'test-secret',
    })
    assert result['value'] is None
    assert result['errors']
    assert calls == []
