"""Digit segmentation and local eight-roller classification."""
from io import BytesIO
from pathlib import Path

from PIL import Image

from .imaging import image_bytes


def split_register_digits(image):
    """Split an already tight register crop into its five black and three red rollers."""
    width, height = image.size
    if width < 8 or height < 1:
        raise ValueError('A számlálóablak túl kicsi.')
    return [image.crop((round(index * width / 8), 0, round((index + 1) * width / 8), height)) for index in range(8)]


def format_digits(digits):
    if not isinstance(digits, list) or len(digits) != 8 or any(not isinstance(digit, str) or len(digit) != 1 or digit not in '0123456789' for digit in digits):
        raise ValueError('A számlálóhoz pontosan nyolc számjegy szükséges.')
    return str(int(''.join(digits[:5]))) + '.' + ''.join(digits[5:])


def recognize_register_digits(path, crop, data_dir: Path, minimum_confidence: float = .75, minimum_decimal_confidence: float = .50):
    """Classify a detected register. Return None whenever any roller is uncertain."""
    # Only a separately validated model is allowed to propose a meter value.
    # `best.onnx` may exist after an experimental training run.
    model_path = Path(data_dir) / 'models' / 'digit-classifier' / 'weights' / 'active.onnx'
    if not model_path.is_file() or crop is None:
        return None
    try:
        from ultralytics import YOLO
        with Image.open(BytesIO(image_bytes(path, crop))) as register:
            patches = split_register_digits(register)
        model = YOLO(str(model_path))
        # The local ONNX export has a fixed batch size of one. Invoke it for
        # each roller instead of passing an eight-image batch.
        predictions = [model(patch, verbose=False)[0] for patch in patches]
        digits, confidences = [], []
        for index, prediction in enumerate(predictions):
            confidence = float(prediction.probs.top1conf)
            digits.append(str(int(prediction.probs.top1)))
            confidences.append(round(confidence, 3))
        uncertain = [index for index, confidence in enumerate(confidences) if confidence < (minimum_confidence if index < 5 else minimum_decimal_confidence)]
        if uncertain:
            return {
                'integer_digits': None, 'decimal_digits': None, 'value': None,
                'needs_review': True, 'uncertain_positions': uncertain,
                'errors': ['A számjegymodell bizonytalan; ellenőrizd a jelzett görgőket.'],
                'method': 'digit-classifier', 'digit_predictions': digits,
                'digit_confidences': confidences,
            }
        value = format_digits(digits)
        decimal_review_positions = [index for index, confidence in enumerate(confidences) if index >= 5 and confidence < minimum_confidence]
        return {
            'integer_digits': ''.join(digits[:5]), 'decimal_digits': ''.join(digits[5:]),
            'value': value, 'needs_review': True, 'uncertain_positions': [],
            'errors': [], 'method': 'digit-classifier', 'digit_confidences': confidences,
            'decimal_review_positions': decimal_review_positions,
        }
    except Exception:
        return None
