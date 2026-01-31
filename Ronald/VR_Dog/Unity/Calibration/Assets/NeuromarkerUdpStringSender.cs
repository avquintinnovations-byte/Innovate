using UnityEngine;
using System.Net.Sockets;
using System.Text;

public class NeuromarkerUdpStringSender : MonoBehaviour
{
    [Header("UDP Settings")]
    public string ipAddress = "192.168.12.1";
    public int port = 5005;

    [Header("Message To Send")]
    [TextArea]
    public string messageToSend = "Hello from Unity!";

    private UdpClient udpClient;

    void Awake()
    {
        udpClient = new UdpClient();
    }

    // Call this from the Inspector (e.g. NextMind On Trigger)
    public void OnNeuromarkerTriggered(string message)
    {
        if (string.IsNullOrEmpty(message))
        {
            Debug.LogWarning("[NeuromarkerUdpStringSender] messageToSend is empty, nothing sent.");
            return;
        }

        SendMessage(message);
        Debug.Log($"[NeuromarkerUdpStringSender] Sent UDP string \"{message}\" to {ipAddress}:{port}");
    }

    void SendMessage(string message)
    {
        byte[] data = Encoding.UTF8.GetBytes(message);
        udpClient.Send(data, data.Length, ipAddress, port);
    }

    void OnApplicationQuit()
    {
        if (udpClient != null)
        {
            udpClient.Close();
            udpClient = null;
        }
    }
}
