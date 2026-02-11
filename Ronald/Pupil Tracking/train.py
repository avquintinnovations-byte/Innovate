from ultralytics import YOLO

if __name__ == '__main__':
    model = YOLO("yolo11m-seg.pt")
    
    model.train(data="custom_dataset.yaml", imgsz=640, device=0, batch=8, epochs=100, workers=3)

