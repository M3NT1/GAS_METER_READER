"""Train a local 0–9 roller classifier and export the accepted ONNX runtime model."""
from pathlib import Path
import sys

from ultralytics import YOLO

dataset, output = map(Path, sys.argv[1:3])
model = YOLO('yolo11n-cls.pt')
result = model.train(data=str(dataset), epochs=80, imgsz=128, batch=32,
                     project=str(output), name='digit-classifier', exist_ok=True, patience=20)
best = Path(result.save_dir) / 'weights' / 'best.pt'
YOLO(str(best)).export(format='onnx', imgsz=128, simplify=True)
print(best)
