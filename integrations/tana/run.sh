#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
audio=$1
transcript=$2
POSTPROCESS_LIB_DIR=$root/lib
MR_CODEX=${MR_CODEX:-codex}
mr_error() { printf '%s\n' "$*" >&2; }
mr_audio_fingerprint() { sha256sum -- "$1" | cut -d ' ' -f 1; }
mr_process_identity() { printf 'tana-action-%s\n' "$1"; }
mr_recording_metadata_file() { printf '%s.recording.json\n' "${1%.m4a}"; }
mr_transcript_json_file() { printf '%s.transcript.json\n' "${1%.m4a}"; }
mr_set_postprocess_status() { printf '%s\n' "$3" >&2; }
source "$POSTPROCESS_LIB_DIR/tana.sh"
result=$(mr_run_tana_agent "$audio" "$transcript")
python3 - "$result" <<'PY'
import json, sys
value=json.load(open(sys.argv[1]))
print(value.get('message', 'Saved to Tana'), value.get('session_uri', ''))
PY
