"""EXIF-aware decoding and metadata-free JPEG crops."""
from io import BytesIO
import math
from PIL import Image, ImageOps


def register_heif():
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass


def image_bytes(path, crop=None, max_size=2000):
    register_heif()
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        if crop is not None:
            if not isinstance(crop, (list, tuple)) or len(crop) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in crop):
                raise ValueError('Érvénytelen kivágás.')
            left, top, right, bottom = crop
            if left >= right or top >= bottom:
                raise ValueError('Érvénytelen kivágás.')
            bounds = (int(left * image.width), int(top * image.height), int(right * image.width), int(bottom * image.height))
            if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                raise ValueError('Túl kicsi kivágás.')
            image = image.crop(bounds)
        image.thumbnail((max_size, max_size))
        result = BytesIO()
        image.save(result, format='JPEG', quality=92, exif=b'')
        return result.getvalue()
