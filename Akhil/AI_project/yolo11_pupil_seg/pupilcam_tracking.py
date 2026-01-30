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
    for box in results[0].boxes:
        x1, y1, x2, y2 = box.xyxy[0]
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)

        # Draw dot at centroid
        cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)
    # Draw results
    annotated_frame = results[0].plot()

    # Show window
    cv2.imshow("PUPIL detector", annotated_frame)

    # Press Q to close camera
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
