# /// script
# requires-python = "==3.11.*"
# dependencies = ["ultralytics", "onnx", "onnxslim", "clip @ git+https://github.com/ultralytics/CLIP.git"]
# ///
import argparse
import json
import shutil
from pathlib import Path

from ultralytics import YOLOE

CLASSES = [
    "person", "cat", "dog", "robot vacuum",
    "chair", "office chair", "stool", "sofa", "armchair", "bed", "dining table", "coffee table", "desk",
    "nightstand", "tv stand", "low wooden cabinet", "wardrobe", "cabinet", "chest of drawers", "shelf", "bookshelf", "kitchen island",
    "refrigerator", "oven", "stove", "microwave", "kettle", "washing machine", "dishwasher", "sink", "toilet",
    "bathtub", "shower", "television", "computer monitor", "laptop", "lamp", "floor lamp", "potted plant",
    "door", "mirror", "radiator", "fan", "air conditioner", "trash can", "laundry basket", "box", "bag",
    "backpack", "suitcase", "shoe", "bottle", "cup", "pillow", "rug", "curtain", "picture frame", "clock",
]

parser = argparse.ArgumentParser(description="Export YOLOE with the apartment classes for the ZED SDK")
parser.add_argument("--model", default="yoloe-26m", choices=["yoloe-11s", "yoloe-11m", "yoloe-11l", "yoloe-26s", "yoloe-26m", "yoloe-26l"])
parser.add_argument("--imgsz", type=int, nargs=2, default=[384, 640], metavar=("H", "W"))
parser.add_argument("--out", type=Path, default=Path("detector"))
args = parser.parse_args()

seg = YOLOE(f"{args.model}-seg.pt")
embeddings = seg.get_text_pe(CLASSES)
model = YOLOE(f"{args.model}.yaml")
model.load(seg.model)
model.set_classes(CLASSES, embeddings)
exported = Path(model.export(format="onnx", imgsz=args.imgsz, opset=17, simplify=True, dynamic=False))

args.out.mkdir(parents=True, exist_ok=True)
shutil.move(exported, args.out / "detector.onnx")
(args.out / "detector.json").write_text(json.dumps({"model": args.model, "imgsz": args.imgsz, "names": CLASSES}, indent=2))
print(args.out.resolve())
