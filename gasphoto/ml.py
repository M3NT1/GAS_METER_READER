"""Local learned register-window detection. It only proposes a crop."""
from io import BytesIO
from pathlib import Path

from PIL import Image

from .imaging import image_bytes


def detect_register_window(path, data_dir: Path, minimum_confidence: float = 0.55):
    """Return one normalized register crop, or None when the local model cannot decide."""
    model_path = Path(data_dir) / 'models' / 'window-detector' / 'weights' / 'best.onnx'
    if not model_path.is_file():
        return None
    try:
        from ultralytics import YOLO
        with Image.open(BytesIO(image_bytes(path))) as image:
            width, height = image.size
            result = YOLO(str(model_path))(image, verbose=False)[0]
        if result.boxes is None or len(result.boxes) != 1:
            return None
        confidence = float(result.boxes.conf[0])
        if confidence < minimum_confidence:
            return None
        left, top, right, bottom = [float(value) for value in result.boxes.xyxy[0].tolist()]
        crop = [max(0, left / width), max(0, top / height), min(1, right / width), min(1, bottom / height)]
        if crop[0] >= crop[2] or crop[1] >= crop[3]:
            return None
        return {'crop': crop, 'confidence': round(confidence, 3), 'model': 'window-v1'}
    except Exception:
        return None
