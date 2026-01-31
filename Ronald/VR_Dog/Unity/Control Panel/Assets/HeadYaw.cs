using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;

public class HeadYaw : MonoBehaviour
{
    // Drag your Main Camera (from under the XR Rig) here in the inspector
    public Transform headsetTransform;

    // UDP Configuration
    public string targetIP = "127.0.0.1";  // Change to drone's IP if needed
    public int targetPort = 5000;
    public float sendRate = 20f;  // Hz - matches the Python script's expected rate

    private UdpClient udpClient;
    private IPEndPoint endPoint;
    private float lastSendTime = 0f;

    void Start()
    {
        // Initialize UDP client
        try
        {
            udpClient = new UdpClient();
            endPoint = new IPEndPoint(IPAddress.Parse(targetIP), targetPort);
            Debug.Log($"UDP client initialized. Sending to {targetIP}:{targetPort}");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Failed to initialize UDP client: {e.Message}");
        }
    }

    void Update()
    {
        if (headsetTransform != null && udpClient != null)
        {
            // Get the rotation around the Y-axis (Yaw)
            float yaw = headsetTransform.localEulerAngles.y;

            // Optional: Rounding to 2 decimal places for cleaner logs
            float formattedYaw = Mathf.Round(yaw * 100f) / 100f;

            // Rate-limited UDP sending
            if (Time.time - lastSendTime >= 1f / sendRate)
            {
                SendYawValue(formattedYaw);
                lastSendTime = Time.time;
                Debug.Log($"Headset Yaw: {formattedYaw} (sent via UDP)");
            }
        }
    }

    void SendYawValue(float yaw)
    {
        try
        {
            // Convert yaw to string and then to bytes
            string message = yaw.ToString("F2");
            byte[] data = Encoding.UTF8.GetBytes(message);
            
            // Send via UDP
            udpClient.Send(data, data.Length, endPoint);
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Failed to send UDP data: {e.Message}");
        }
    }

    void OnDestroy()
    {
        // Clean up UDP client when destroyed
        if (udpClient != null)
        {
            udpClient.Close();
            Debug.Log("UDP client closed");
        }
    }

    void OnApplicationQuit()
    {
        // Clean up UDP client when application quits
        if (udpClient != null)
        {
            udpClient.Close();
        }
    }
}