import torch
import cv2
import numpy as np
import time
from torchvision import transforms
from PIL import Image
import yolov5
from torchvision.models import resnet50
import os
from typing import Dict, List, Tuple, Optional, Any

# Check for CUDA availability and set device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print("Using device: {}".format(device))

# Initialize YOLO model
yolo_model = yolov5.load('yolov5l.pt')
yolo_model.to(device)
yolo_model.eval()  # Set to evaluation mode

# Initialize ResNet model for feature extraction
resnet_model = resnet50(pretrained=True)
# Remove the final classification layer and set to eval mode
resnet_model = torch.nn.Sequential(*list(resnet_model.children())[:-1])
resnet_model.to(device)
resnet_model.eval()  # Ensure the model is in evaluation mode

# Initialize feature database and tracking states
feature_database = {}  # type: Dict[int, List[np.ndarray]]
tracking_states = {}  # type: Dict[int, str]
max_feature_history = 10

# Initialize transform for ResNet with ImageNet normalization
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],  # ImageNet mean
        std=[0.229, 0.224, 0.225]    # ImageNet std
    )
])

def extract_features(frame, bbox):
    """Extract features from detected persons using ResNet"""
    try:
        x1, y1, x2, y2 = map(int, bbox)
        person_roi = frame[y1:y2, x1:x2]
        if person_roi.size == 0:
            return None
        
        # Convert to PIL Image and apply transform
        pil_img = Image.fromarray(cv2.cvtColor(person_roi, cv2.COLOR_BGR2RGB))
        img_tensor = transform(pil_img).unsqueeze(0).to(device)
        
        # Extract features
        with torch.no_grad():
            features = resnet_model(img_tensor)
        features = features.squeeze().cpu().numpy()
        # Normalize features
        features = features / (np.linalg.norm(features) + 1e-6)
        return features
    except Exception as e:
        print("Error extracting features: {}".format(e))
        return None

def match_features(features, database, threshold=0.8):
    """Match features with existing tracks"""
    if not database or features is None:
        return None
    
    best_match = None
    best_similarity = -1
    
    for track_id, feature_history in database.items():
        for stored_features in feature_history:
            # Normalize stored features
            stored_features = stored_features / (np.linalg.norm(stored_features) + 1e-6)
            similarity = np.dot(features, stored_features)
            if similarity > threshold and similarity > best_similarity:
                best_similarity = similarity
                best_match = track_id
    
    return best_match

def main():
    # type: () -> None
    """Main function"""
    try:
        # Initialize video capture
        cap = cv2.VideoCapture(1)
        if not cap.isOpened():
            print("Error: Could not open camera")
            return
            
        # Initialize FPS counter
        fps = 0
        frame_count = 0
        start_time = time.time()
            
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Could not read frame")
                break
                
            current_time = time.time()
            
            # Update FPS
            frame_count += 1
            if current_time - start_time > 1:
                fps = frame_count / (current_time - start_time)
                frame_count = 0
                start_time = current_time
            
            # Run YOLO detection
            results = yolo_model(frame)
            
            # Process detections
            detections = results.pred[0]
            for det in detections:
                if det is not None and len(det) > 0:
                    x1, y1, x2, y2, conf, cls = det
                    if int(cls) == 0 and conf > 0.5:  # Person class with confidence threshold
                        x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
                        
                        # Extract features
                        features = extract_features(frame, (x1, y1, x2, y2))
                        if features is None:
                            continue
                        
                        # Match features with existing tracks
                        track_id = match_features(features, feature_database)
                        
                        if track_id is None:
                            # Create new track
                            track_id = len(feature_database)
                            feature_database[track_id] = [features]
                            tracking_states[track_id] = "normal"
                        else:
                            # Update existing track
                            feature_database[track_id].append(features)
                            if len(feature_database[track_id]) > max_feature_history:
                                feature_database[track_id].pop(0)
                        
                        # Draw bounding box with color based on state
                        color = (0, 255, 0)  # Green for normal
                        if track_id in tracking_states and tracking_states[track_id] == "tracking":
                            color = (0, 0, 255)  # Red for tracking
                        
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        
                        # Display ID and state
                        state_text = "Normal"
                        if track_id in tracking_states and tracking_states[track_id] == "tracking":
                            state_text = "Tracking"
                        
                        cv2.putText(frame, "ID: {} ({})".format(track_id, state_text),
                                  (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Display FPS
            cv2.putText(frame, "FPS: {:.1f}".format(fps), (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            # Display frame
            cv2.imshow('Person Detection', frame)
            
            # Break loop on 'q' key
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    except Exception as e:
        print("Error in main loop: {}".format(e))
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main() 