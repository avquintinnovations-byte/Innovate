#!/usr/bin/env python3

import cv2
import gi
import numpy as np
import rospy
import argparse
from cv_bridge import CvBridge
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import Bool
from std_msgs.msg import Float32
from geometry_msgs.msg import Point
import time
import torch
import threading
import yolov5

model = yolov5.load('yolov5l.pt')
model.to('cuda')

UNKNOWN = 'unknown'
DETECTED = 'detected'
CONFIRMED = 'confirmed'
NODETECTED = 'nodetected'

torch.cuda.set_device(0)
current_state = UNKNOWN


def Timerx(t, pub_obj:rospy.Publisher):
    global current_state
    i = 0
    while (current_state==DETECTED): 
        print(f"tik tik: ", i)
        i+=1
        time.sleep(1)
        if(i==t):
            print(f"5 seconds elapsed - go to Confirmed state")
            
            current_state = CONFIRMED
            pub_obj.publish(True)

def main():
    global current_state

    rospy.init_node('bic_detect_person', anonymous=True)
    pos_pub = rospy.Publisher('/bic/detect_person/position',Point, queue_size=10)
    bool_pub = rospy.Publisher('/bic/detect_person/bool',Bool, queue_size=10)
    conf_pub = rospy.Publisher('/bic/detect_person/conf',Bool, queue_size=10)
    confidence_pub = rospy.Publisher('/bic/detect_person/confidence',Float32, queue_size=10)
    width_pub = rospy.Publisher('/bic/detect_person/width',Float32, queue_size=10)
    rate = rospy.Rate(100)

    # Initialize video capture
    cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        rospy.logerr("Error: Could not open camera")
        return

    try:
        while not rospy.is_shutdown():
            # Read frame from camera
            ret, frame = cap.read()
            if not ret:
                rospy.logerr("Error: Could not read frame")
                continue
            
            height, width = frame.shape[:2]
            print("width:", width)

            pos = Point()

            # Run YOLOv5 detection
            results = model(frame)
            
            # Check if any person (class 0) was detected with confidence > 0.75
            detections = results.pred[0]
            person_detected = False
            
            for det in detections:
                if det is not None and len(det) > 0:
                    x1, y1, x2, y2, conf, cls = det
                    
                    # Check if it's a person (class 0) with high confidence
                    if int(cls) == 0 and conf > 0.75:
                        person_detected = True
                        
                        if current_state == NODETECTED or current_state == UNKNOWN: 
                            current_state = DETECTED
                            bool_pub.publish(True)
                            thread1 = threading.Thread(target=Timerx, args=(1,conf_pub,))
                            thread1.daemon = True
                            thread1.start()
                        
                        # Publish confidence
                        confidence_pub.publish(float(conf))
                        
                        # Get coordinates and dimensions
                        x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
                        w = x2 - x1
                        h = y2 - y1
                        x = (x1 + x2) / 2  # center x
                        y = (y1 + y2) / 2  # center y
                        
                        # Draw bounding box
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 3)
                        
                        # Calculate position relative to center and publish
                        print("position: ", width/2 - x)
                        pos.x = width/2 - x
                        pos_pub.publish(pos)
                        
                        # Publish width
                        print("detection width: ", w)
                        width_pub.publish(float(w))
                        
                        # Only process the first person detected
                        break
            
            # If no person was detected
            if not person_detected and (current_state == DETECTED or current_state == UNKNOWN or current_state == CONFIRMED):
                current_state = NODETECTED
                conf_pub.publish(False)
                bool_pub.publish(False)

            # Display the frame (optional)
            cv2.imshow('Person Detection', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            rate.sleep()
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    try:
        main()
    except rospy.ROSInterruptException:
        pass
    
        
        
