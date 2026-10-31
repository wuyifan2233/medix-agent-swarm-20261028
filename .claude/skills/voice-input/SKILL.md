---
name: voice-input
description: Browser-first voice input for the MediX web composer. Speech is transcribed into an editable draft and is never submitted automatically.
runtime: ui
expose_to_agent: false
---

# Voice input

This is a web runtime capability, not a medical reasoning tool. The composer
uses the browser Web Speech API when available, with `zh-CN` and a live
interim transcript. Browser support and microphone access vary by browser and
origin. If browser dictation is unavailable and a compatible audio endpoint is
configured, the browser records a short WebM/MP4 clip and sends it to
`/api/voice/transcribe`.

Never submit speech automatically. Show the returned transcript in the
editable confirmation card, allow retry or cancel, and move it into the normal
composer only after the user clicks “放入输入框”. The user can still revise
the composer text before sending it through the existing `/api/chat` flow.

Do not claim that browser recognition is local: the browser or operating
system chooses how its recognition service processes audio. The optional
server ASR endpoint handles uploads in memory and does not persist audio.
