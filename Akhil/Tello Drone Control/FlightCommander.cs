using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;

public class FlightCommander : MonoBehaviour
{
    // UDP Configuration
    public string targetIP = "127.0.0.1";
    public int commandPort = 5015;

    // UI/Control options
    public KeyCode takeoffKey = KeyCode.T;
    public KeyCode landKey = KeyCode.L;
    public KeyCode emergencyKey = KeyCode.E;

    private UdpClient udpClient;
    private IPEndPoint endPoint;
    private bool hasStarted = false;

    void Start()
    {
        // Initialize UDP client
        try
        {
            udpClient = new UdpClient();
            endPoint = new IPEndPoint(IPAddress.Parse(targetIP), commandPort);
            hasStarted = true;
            Debug.Log($"Flight Commander initialized. Sending to {targetIP}:{commandPort}");
            Debug.Log($"Controls: {takeoffKey} = Takeoff, {landKey} = Land, {emergencyKey} = Emergency (hold Shift)");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Failed to initialize Flight Commander UDP client: {e.Message}");
        }
    }

    void Update()
    {
        if (!hasStarted || udpClient == null) return;

        // Takeoff command
        if (Input.GetKeyDown(takeoffKey))
        {
            SendFlightCommand("takeoff");
        }

        // Land command
        if (Input.GetKeyDown(landKey))
        {
            SendFlightCommand("land");
        }

        // Emergency stop (requires holding Shift for safety)
        if (Input.GetKeyDown(emergencyKey) && (Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift)))
        {
            Debug.LogWarning("EMERGENCY STOP ACTIVATED!");
            SendFlightCommand("emergency");
        }
    }

    void SendFlightCommand(int commandNumber, string commandName)
    {
        try
        {
            byte[] data = Encoding.UTF8.GetBytes(commandNumber.ToString());
            udpClient.Send(data, data.Length, endPoint);
            Debug.Log($"Flight command sent: {commandNumber} ({commandName})");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Failed to send flight command {commandNumber} ({commandName}): {e.Message}");
        }
    }

    // Public methods for UI buttons or programmatic control
    public void Takeoff()
    {
        SendFlightCommand(1, "TAKEOFF");
    }

    public void Land()
    {
        SendFlightCommand(2, "LAND");
    }

    public void Emergency()
    {
        Debug.LogWarning("Emergency stop requested!");
        SendFlightCommand(3, "EMERGENCY");
    }

    void OnDestroy()
    {
        if (udpClient != null)
        {
            udpClient.Close();
            Debug.Log("Flight Commander UDP client closed");
        }
    }

    void OnApplicationQuit()
    {
        if (udpClient != null)
        {
            udpClient.Close();
        }
    }

    // Optional: Draw debug info
    void OnGUI()
    {
        if (!Application.isPlaying || !hasStarted) return;

        string status = "Flight Commander\n";
        status += $"{takeoffKey} = Takeoff (1)\n";
        status += $"{landKey} = Land (2)\n";
        status += $"Shift+{emergencyKey} = Emergency (3)";

        GUI.Label(new Rect(10, 200, 300, 100), status);
    }
}
