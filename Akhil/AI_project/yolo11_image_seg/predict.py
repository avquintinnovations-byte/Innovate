from ultralytics import YOLO 
  
model =YOLO("yolo11m-seg-custom.pt")

model.predict(source="2.jpg",show=True,save=True,conf=0.7,line_width=2,save_crop=True,save_txt=True,show_labels=True,show_conf=True,classes=[0,1])