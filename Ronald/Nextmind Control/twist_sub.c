#include <ros/ros.h>
#include <unitree_legged_msgs/HighCmd.h>
#include <unitree_legged_msgs/HighState.h>
#include "unitree_legged_sdk/unitree_legged_sdk.h"
#include "convert.h"
#include <chrono>
#include <pthread.h>
#include <geometry_msgs/Twist.h>
#include <std_msgs/Float32.h>
#include <std_msgs/Float32MultiArray.h>

using namespace UNITREE_LEGGED_SDK;
class Custom
{
public:
    UDP high_udp;

    HighCmd high_cmd = {0};
    HighState high_state = {0};

public:
    Custom()
        :
        high_udp(8090, "192.168.12.1", 8082, sizeof(HighCmd), sizeof(HighState))
    {
        high_udp.InitCmdData(high_cmd);
    }

    void highUdpSend()
    {
        high_udp.SetSend(high_cmd);
        high_udp.Send();
    }

    void highUdpRecv()
    {
        high_udp.Recv();
        high_udp.GetRecv(high_state);
    }
};

Custom custom;

ros::Subscriber sub_cmd_vel;
ros::Subscriber sub_body_orient;
ros::Publisher pub_high;

long cmd_vel_count = 0;
long body_orient_count = 0;

void cmdVelCallback(const geometry_msgs::Twist::ConstPtr &msg)
{
    printf("cmdVelCallback is running!\t%ld\n", cmd_vel_count++);

    custom.high_cmd = rosMsg2Cmd(msg);

    printf("cmd_x_vel = %f\n", custom.high_cmd.velocity[0]);
    printf("cmd_y_vel = %f\n", custom.high_cmd.velocity[1]);
    printf("cmd_yaw_vel = %f\n", custom.high_cmd.yawSpeed);

    unitree_legged_msgs::HighState high_state_ros;
    high_state_ros = state2rosMsg(custom.high_state);
    pub_high.publish(high_state_ros);
}

void bodyOrientCallback(const std_msgs::Float32MultiArray::ConstPtr &msg)
{
    printf("bodyOrientCallback is running!\t%ld\n", body_orient_count++);

    if (msg->data.size() == 3)
    {
        float x = msg->data[0];
        float y = msg->data[1];
        float z = msg->data[2];

        ROS_INFO("Received relative body orientation: x = %f, y = %f, z = %f", x, y, z);
        
        // Apply the relative orientation to the robot's body
        custom.high_cmd.bodyHeight = 0.0;      // Default height
        custom.high_cmd.roll = x;              // Roll - relative to initial position
        custom.high_cmd.pitch = y;             // Pitch - relative to initial position
        custom.high_cmd.yaw = z;               // Yaw - relative to initial position
    }

    unitree_legged_msgs::HighState high_state_ros;
    high_state_ros = state2rosMsg(custom.high_state);
    pub_high.publish(high_state_ros);
}

int main(int argc, char **argv)
{
    ros::init(argc, argv, "twist_sub");

    ros::NodeHandle nh;

    pub_high = nh.advertise<unitree_legged_msgs::HighState>("high_state", 1);

    sub_cmd_vel = nh.subscribe("cmd_vel", 1, cmdVelCallback);
    sub_body_orient = nh.subscribe("body_orient", 1, bodyOrientCallback);

    LoopFunc loop_udpSend("high_udp_send", 0.002, 3, boost::bind(&Custom::highUdpSend, &custom));
    LoopFunc loop_udpRecv("high_udp_recv", 0.002, 3, boost::bind(&Custom::highUdpRecv, &custom));

    loop_udpSend.start();
    loop_udpRecv.start();

    ros::spin();

    return 0;
}