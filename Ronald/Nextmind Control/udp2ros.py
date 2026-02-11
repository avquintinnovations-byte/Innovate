#!/usr/bin/env python3

import rospy
import socket
from geometry_msgs.msg import Twist

def udp_to_cmd_vel():
    rospy.init_node('udp_to_cmd_vel')

    # Publisher for the cmd_vel topic
    cmd_vel_pub = rospy.Publisher('cmd_vel', Twist, queue_size=10)

    # UDP socket setup
    udp_ip = "192.168.12.1"  # Listen on all available interfaces
    udp_port = 5005     # Port to listen on
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((udp_ip, udp_port))

    rospy.loginfo("Listening for UDP data on port %d", udp_port)

    rate = rospy.Rate(10)  # Adjust the rate as necessary

    while not rospy.is_shutdown():
        data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
        try:
            # Assuming data is a comma-separated string of linear and angular velocities
            linear_x, angular_z = map(float, data.decode('utf-8').split(','))

            twist_msg = Twist()
            twist_msg.linear.x = linear_x
            twist_msg.angular.z = angular_z

            # Publish the Twist message
            cmd_vel_pub.publish(twist_msg)
            rospy.loginfo("Published Twist: linear.x=%f, angular.z=%f", linear_x, angular_z)

        except ValueError:
            rospy.logwarn("Received invalid data: %s", data)

        rate.sleep()

if __name__ == '__main__':
    try:
        udp_to_cmd_vel()
    except rospy.ROSInterruptException:
        pass