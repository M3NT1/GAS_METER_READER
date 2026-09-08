"""Train the first local register-window detector from exported labels."""
from pathlib import Path
import sys
from ultralytics import YOLO


dataset, output = map(Path, sys.argv[1:3])
model = YOLO('yolo11n.pt')
result = model.train(data=str(dataset / 'data.yaml'), epochs=60, imgsz=960, batch=4,
                     project=str(output), name='window-detector', exist_ok=True, patience=15)
best = Path(result.save_dir) / 'weights' / 'best.pt'
YOLO(str(best)).export(format='onnx', imgsz=960, simplify=True)
print(best)
