---
name: tts-voice
description: Warm cloud answer playback for the MediX web UI; independent of the text LLM.
runtime: ui
expose_to_agent: false
---

# Answer playback

Use server-side edge-tts through the prepare ticket and native Audio.src stream endpoints (POST /api/voice/speech remains a streaming API adapter), with zh-CN-XiaoxiaoNeural and a slightly slower rate by default. Do not use browser speechSynthesis or forward text-model credentials to TTS.

Speak only complete answer bodies, excluding Markdown tables, source cards and tool traces. The current user requested automatic playback enabled initially; preserve their persisted preference and manual playback/stop controls. Do not stream partial medical answers. Stop or switch playback safely, cancel pending client fetches, and detach Audio.src/load to abort native downloads. Forward MP3 chunks as generated; never buffer the full response into a Blob before playback. Close the provider on disconnect, including before the first audio chunk. Cloud failures show a retry message while the answer remains readable and copyable.

See docs/VOICE.md for independent configuration, cloud processing, timeouts, and test procedure.
