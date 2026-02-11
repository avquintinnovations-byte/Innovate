#!/usr/bin/env python3

import rospy
import socket
from std_msgs.msg import Float32MultiArray

def body_orientation_publisher():
    rospy.init_node('body_orientation_publisher', anonymous=True)
    pub = rospy.Publisher('body_orient', Float32MultiArray, queue_size=10)
    rate = rospy.Rate(10) # 10hz

    # UDP socket setup
    udp_ip = "192.168.12.1"  # Listen on all available interfaces
    udp_port = 5006     # Port to listen on
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((udp_ip, udp_port))

    rospy.loginfo("Listening for UDP data on port %d", udp_port)

    orientation = [0.0, 0.0, 0.0]
    initial_orientation = None
    relative_orientation = [0.0, 0.0, 0.0]

    while not rospy.is_shutdown():
        data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
        try:
            # Assuming data is a comma-separated string of linear and angular velocities
            orient_x, orient_y, orient_z = map(float, data.decode('utf-8').split(','))

            orientation[0] = orient_x
            orientation[1] = orient_y
            orientation[2] = orient_z

            # Store initial orientation if this is the first data received
            if initial_orientation is None:
                initial_orientation = [orient_x, orient_y, orient_z]
                rospy.loginfo("Initial orientation set: x={}, y={}, z={}".format(
                    initial_orientation[0], initial_orientation[1], initial_orientation[2]))
            
            # Calculate relative orientation
            relative_orientation[0] = orientation[0] - initial_orientation[0]
            relative_orientation[1] = orientation[1] - initial_orientation[1]
            relative_orientation[2] = orientation[2] - initial_orientation[2]

            rospy.loginfo("Publishing relative: x={}, y={}, z={}".format(
                relative_orientation[0], relative_orientation[1], relative_orientation[2]))
            msg = Float32MultiArray(data=relative_orientation)
            pub.publish(msg)

        except ValueError:
            rospy.logwarn("Received invalid data: %s", data)

        rate.sleep()

if __name__ == '__main__':
    try:
        body_orientation_publisher()
    except rospy.ROSInterruptException:
        pass