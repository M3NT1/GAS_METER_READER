from PIL import Image
import sys
from types import SimpleNamespace

from gasphoto.digits import format_digits, recognize_register_digits, split_register_digits


def test_register_crop_is_split_into_eight_ordered_digit_images():
    image = Image.new('RGB', (800, 100))
    patches = split_register_digits(image)
    assert len(patches) == 8
    assert all(patch.size == (100, 100) for patch in patches)
    assert format_digits(['0', '1', '7', '8', '8', '1', '2', '7']) == '1788.127'


def test_register_requires_exactly_eight_digits():
    try:
        format_digits(['1'] * 7)
    except ValueError as error:
        assert 'nyolc' in str(error)
    else:
        raise AssertionError('Expected an invalid digit count to be rejected')


def test_onnx_digit_model_is_called_once_per_roller(tmp_path, monkeypatch):
    image_path = tmp_path / 'meter.jpg'
    Image.new('RGB', (800, 100)).save(image_path)
    model_path = tmp_path / 'models' / 'digit-classifier' / 'weights'
    model_path.mkdir(parents=True)
    (model_path / 'active.onnx').write_bytes(b'model')
    calls = []
    class Model:
        def __call__(self, patch, verbose=False):
            calls.append(patch.size)
            return [SimpleNamespace(probs=SimpleNamespace(top1=1, top1conf=.99))]
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=lambda _: Model()))

    result = recognize_register_digits(image_path, [0, 0, 1, 1], tmp_path)

    assert calls == [(100, 100)] * 8
    assert result['value'] == '11111.111'


def test_uncertain_roller_is_returned_as_a_reviewable_diagnostic(tmp_path, monkeypatch):
    image_path = tmp_path / 'meter.jpg'
    Image.new('RGB', (800, 100)).save(image_path)
    model_path = tmp_path / 'models' / 'digit-classifier' / 'weights'
    model_path.mkdir(parents=True)
    (model_path / 'active.onnx').write_bytes(b'model')
    calls = []
    class Model:
        def __call__(self, patch, verbose=False):
            calls.append(patch)
            confidence = .49 if len(calls) == 6 else .99
            return [SimpleNamespace(probs=SimpleNamespace(top1=5, top1conf=confidence))]
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=lambda _: Model()))

    result = recognize_register_digits(image_path, [0, 0, 1, 1], tmp_path)

    assert result['value'] is None
    assert result['uncertain_positions'] == [5]
    assert result['digit_predictions'] == ['5'] * 8


def test_red_decimal_roller_can_be_accepted_at_lower_confidence(tmp_path, monkeypatch):
    image_path = tmp_path / 'meter.jpg'
    Image.new('RGB', (800, 100)).save(image_path)
    model_path = tmp_path / 'models' / 'digit-classifier' / 'weights'
    model_path.mkdir(parents=True)
    (model_path / 'active.onnx').write_bytes(b'model')
    calls = []
    class Model:
        def __call__(self, patch, verbose=False):
            calls.append(patch)
            confidence = .51 if len(calls) == 6 else .99
            return [SimpleNamespace(probs=SimpleNamespace(top1=5, top1conf=confidence))]
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=lambda _: Model()))

    result = recognize_register_digits(image_path, [0, 0, 1, 1], tmp_path)

    assert result['value'] == '55555.555'
    assert result['decimal_review_positions'] == [5]
