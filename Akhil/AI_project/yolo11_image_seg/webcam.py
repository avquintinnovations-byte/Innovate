from ultralytics import YOLO
import cv2

# Load your trained model
model = YOLO("yolo11m-seg-custom.pt")   # <-- change path if your best.pt is elsewhere

# Open webcam
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Camera not opening")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Run detection (CPU)
    results = model.predict(source=frame, device="cpu", conf=0.8)

    # Draw results
    annotated_frame = results[0].plot()

    # Show window
    cv2.imshow("Coca-Cola vs Pepsi Detector", annotated_frame)

    # Press Q to close camera
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
