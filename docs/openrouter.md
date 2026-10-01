# Optional MAI transcription

Whisper remains the default. Select MAI once in `~/.config/omarchy-meeting-recorder/config.toml`, before any `[section]` or `[[action]]` tables:

```toml
backend = "mai"
```

Use `backend = "whisper"` for local transcription. The app uses this choice for new recordings, imported audio and retranscription of existing meetings. There is no per-meeting backend selector. Editing the config takes effect on the next transcription; an existing transcript's model metadata does not override it.

MAI sends audio to OpenRouter and its Microsoft provider and incurs API charges. Speaker identification remains local. Store the key as described below; it is not part of the model selection.

The CLI uses the same config. Explicit `--backend mai` or `--backend whisper` overrides it on `transcribe` and `transcribe-file`. Example:

```sh
omarchy-meeting-recorder transcribe-file recording.wav --backend mai --language no --speakers 1
```

Python 3.11+, ffmpeg (MP3 encoder), and `secret-tool` are needed. Store the key in the system keyring without putting it on a command line:

```sh
secret-tool store --label='Meeting Recorder OpenRouter' service omarchy-meeting-recorder credential openrouter-api-key
```

Paste the key at the prompt. Alternatively set `OPENROUTER_API_KEY` in the process environment. Keys are never stored in the meeting or passed in process arguments.

Optional vocabulary hints in `~/.config/omarchy-meeting-recorder/config.toml`:

```toml
[openrouter]
phrases = ["Digel", "IoT"]
```

The model is `microsoft/mai-transcribe-2`. Audio is sent as 16 kHz mono MP3 in chunks of at most five minutes. Real word times are required; missing/malformed timestamps produce an error rather than guessed positions. Successful responses are cached privately under `~/.cache/omarchy-meeting-recorder/mai-responses` so retries reuse completed chunks. Deleting that directory clears the cache. Temporary raw audio is removed after success, failure or cancellation. Cancellation terminates the upload process; it cannot recall an upload already accepted by the provider.

The adapter feeds the existing speech-region mapping and speaker assignment. Mic and computer audio are processed separately as upstream does, so remote voices leaking into the mic can be suppressed. The displayed model in the meeting manifest records which backend produced the transcript.

Cloud failures do not silently switch providers or overwrite the previous transcript. Saved audio remains available for retry. Local diarization models may still download on first use; MAI does not load/download a Whisper model.
