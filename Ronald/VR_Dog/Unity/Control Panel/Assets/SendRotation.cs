using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;

public class SendRotation : MonoBehaviour
{
    public GameObject target; // The GameObject whose rotation will be sent
    public GameObject visibilityObject; // The GameObject to show/hide based on rotation
    public string ipAddress = "192.168.12.1"; // IP address to send data to
    public int port = 5006; // Port to send data to

    private UdpClient udpClient;
    private Vector3 previousRotation;
    private bool isVisible; // Track the current visibility state of the object

    void Start()
    {
        udpClient = new UdpClient();
        if (target != null)
        {
            previousRotation = target.transform.eulerAngles;
        }
        isVisible = false; // Initial state is invisible
        if (visibilityObject != null)
        {
            visibilityObject.SetActive(isVisible);
        }
    }

    void Update()
    {
        if (target != null)
        {
            Vector3 currentRotation = target.transform.eulerAngles;

            // Calculate the absolute difference between the current and previous rotations
            float deltaX = Mathf.Abs(Mathf.DeltaAngle(previousRotation.x, currentRotation.x));
            float deltaY = Mathf.Abs(Mathf.DeltaAngle(previousRotation.y, currentRotation.y));
            float deltaZ = Mathf.Abs(Mathf.DeltaAngle(previousRotation.z, currentRotation.z));

            // Calculate the absolute value of the current rotation
            float absX = Mathf.Abs(NormalizeAngle(currentRotation.x));
            float absY = Mathf.Abs(NormalizeAngle(currentRotation.y));
            float absZ = Mathf.Abs(NormalizeAngle(currentRotation.z));

            // Check if the object should be visible or not
            bool shouldBeVisible = (absX < 20 && absY < 20 && absZ < 20);

            // Toggle visibility only if the state changes
            if (shouldBeVisible != isVisible)
            {
                isVisible = shouldBeVisible;
                if (visibilityObject != null)
                {
                    visibilityObject.SetActive(isVisible);
                }
            }

            // Send rotation only if any delta is above 5 degrees
            if (deltaX > 5 || deltaY > 5 || deltaZ > 5)
            {
                // Map rotation values from -45 to 45 onto -0.6 to 0.6
                float mappedX = MapRotation(currentRotation.x);
                float mappedY = MapRotation(currentRotation.y);
                float mappedZ = MapRotation(currentRotation.z);

                // Clamp values between -0.6 and 0.6
                mappedX = Mathf.Clamp(mappedX, -0.6f, 0.6f);
                mappedY = Mathf.Clamp(mappedY, -0.6f, 0.6f);
                mappedZ = Mathf.Clamp(mappedZ, -0.6f, 0.6f);

                // Create the message
                string message = $"{-mappedZ},{mappedX},{-mappedY}";

                // Send the message
                SendMessage(message);

                // Update the previous rotation to the current rotation
                previousRotation = currentRotation;
            }
        }
    }

    float NormalizeAngle(float angle)
    {
        if (angle > 180) angle -= 360; // Convert range from 0-360 to -180-180
        return angle;
    }

    float MapRotation(float value)
    {
        return (NormalizeAngle(value) / 45.0f) * 0.6f;
    }

    void SendMessage(string message)
    {
        byte[] data = Encoding.UTF8.GetBytes(message);
        udpClient.Send(data, data.Length, ipAddress, port);
    }

    void OnApplicationQuit()
    {
        udpClient.Close();
    }
}
