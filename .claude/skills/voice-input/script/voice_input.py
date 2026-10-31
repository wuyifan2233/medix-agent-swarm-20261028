"""Runtime metadata for the browser voice-input capability."""


def voice_input(mode: str = "browser-first"):
    """Describe the configured input path for diagnostics, without recording audio."""
    return {
        "success": True,
        "mode": mode,
        "editable_draft": True,
        "submit_automatically": False,
    }
