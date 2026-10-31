---
name: medix-voice
description: Build or maintain MediX browser voice input and answer playback while preserving editable confirmation and the existing chat pipeline.
---

# MediX voice UI

Use this skill when changing voice input, transcription, text-to-speech, or their configuration in this repository.

- Keep voice as an input/output layer around the existing text chat and model routing. Do not change the configured text model to add ASR or TTS.
- Voice recognition must produce a visible, editable draft. The user explicitly moves it into the normal composer; never auto-submit a transcript.
- Prefer browser `SpeechRecognition` when available. Use `MediaRecorder` only when a configured server ASR endpoint is available. Explain provider processing accurately; do not promise browser recognition is local.
- Keep provider credentials server-side. The optional `/api/voice/transcribe` and `/api/voice/speech` adapters use the separate `MEDIX_AUDIO_*` configuration; provider-specific APIs need a server-side adapter.
- Keep manual answer playback and stop controls available. Automatic playback remains opt-in and starts only after the complete answer. Strip markdown decoration and source/tool UI before speech.
- Preserve the existing soft MediX visual style, accessible control labels, reduced-motion behavior, and narrow-screen layout.
- Run `node --check web/static/app.js` and `python -m unittest web.test_web -v` after meaningful changes. Update `docs/VOICE.md` when provider/model guidance or environment settings change.
