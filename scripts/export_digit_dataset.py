"""Export eight labelled roller images per approved register for local training."""
import json
from pathlib import Path
import random
import sqlite3
import sys

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gasphoto.digits import split_register_digits


def main(db_path, output):
    output = Path(output)
    with sqlite3.connect(db_path) as db:
        rows = db.execute('''select p.id,p.archive_path,t.window_quad_json,t.value_digits
            from training_examples t join photos p on p.id=t.photo_id order by p.id''').fetchall()
    if len(rows) < 40:
        raise SystemExit('Legalább 40 tanítópélda szükséges.')
    shuffled = rows[:]
    random.Random(20260908).shuffle(shuffled)
    train_end, val_end = round(len(rows) * .8), round(len(rows) * .9)
    for index, (photo_id, archive_path, quad_json, digits) in enumerate(shuffled):
        split = 'train' if index < train_end else 'val' if index < val_end else 'test'
        points = json.loads(quad_json)['points']
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        with Image.open(archive_path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            register = image.crop((round(min(xs) * image.width), round(min(ys) * image.height), round(max(xs) * image.width), round(max(ys) * image.height)))
        for digit_index, (patch, digit) in enumerate(zip(split_register_digits(register), digits, strict=True)):
            destination = output / split / digit
            destination.mkdir(parents=True, exist_ok=True)
            patch.save(destination / f'{photo_id}-{digit_index}.jpg', quality=95)
    print(json.dumps({'examples': len(rows), 'digits': len(rows) * 8, 'output': str(output.resolve())}))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
