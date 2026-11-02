"""The Mac's microphone settings, asked of macOS (osascript, system_profiler): what a saved recording notes of its
input (recordings.Folder.finish)."""
import json
import subprocess


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def state():
    """The Mac's microphone settings now: {"inputVolume": 0..100 or None, "device": {...} or None}. The input volume
    (System Settings, Sound, Input) moves speech and room noise up or down together."""
    volume = _run(["osascript", "-e", "input volume of (get volume settings)"], 5)
    profile = _run(["system_profiler", "SPAudioDataType", "-json"], 10)
    device = None
    try:
        items = json.loads(profile)["SPAudioDataType"][0].get("_items") or []
        d = next((i for i in items if i.get("coreaudio_default_audio_input_device") == "spaudio_yes"), None)
        if d:
            device = {"name": d.get("_name"), "sampleRate": d.get("coreaudio_device_srate"),
                      "inputChannels": d.get("coreaudio_device_input"),
                      "transport": str(d.get("coreaudio_device_transport") or "").replace("coreaudio_device_type_", ""),
                      "manufacturer": d.get("coreaudio_device_manufacturer")}
    except (TypeError, ValueError, KeyError, IndexError):
        pass
    try:
        volume = float(volume)
        volume = int(volume) if volume.is_integer() else volume
    except (TypeError, ValueError):
        volume = None
    return {"inputVolume": volume, "device": device}
