"""Runtime metadata for the browser text-to-speech capability."""


def tts_voice(mode: str = "server-then-browser"):
    """Describe the configured playback path without generating audio."""
    return {
        "success": True,
        "mode": mode,
        "manual_control": True,
        "auto_play_default": False,
    }
