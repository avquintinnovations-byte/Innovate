using UnityEngine;

public class NeuromarkerDebug : MonoBehaviour
{
    // Hook this up to the NextMind "On Trigger" event in the Inspector
    public void OnNeuromarkerTriggered()
    {
        Debug.Log("NextMind neuromarker was triggered!");
    }
}
