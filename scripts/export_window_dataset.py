"""Export approved window labels as a one-class YOLO dataset."""
import json
from pathlib import Path
import random
import sqlite3
import sys

from PIL import Image, ImageOps


def main(db_path, output):
    output = Path(output)
    with sqlite3.connect(db_path) as db:
        rows = db.execute('''select p.id,p.archive_path,t.window_quad_json
            from training_examples t join photos p on p.id=t.photo_id
            order by p.id''').fetchall()
    if len(rows) < 40:
        raise SystemExit('Legalább 40 tanítópélda szükséges.')
    shuffled = rows[:]
    random.Random(20260908).shuffle(shuffled)
    cuts = (round(len(shuffled) * .8), round(len(shuffled) * .9))
    for index, (photo_id, archive_path, quad_json) in enumerate(shuffled):
        split = 'train' if index < cuts[0] else 'val' if index < cuts[1] else 'test'
        image_dir, label_dir = output / 'images' / split, output / 'labels' / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(archive_path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            width, height = image.size
            image.save(image_dir / f'{photo_id}.jpg', quality=95)
        points = json.loads(quad_json)['points']
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
        cx, cy, box_w, box_h = (left + right) / 2, (top + bottom) / 2, right - left, bottom - top
        (label_dir / f'{photo_id}.txt').write_text(f'0 {cx:.8f} {cy:.8f} {box_w:.8f} {box_h:.8f}\n')
    (output / 'data.yaml').write_text('path: ' + str(output.resolve()) + '\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: register_window\n')
    print(json.dumps({'examples': len(rows), 'output': str(output.resolve())}))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
