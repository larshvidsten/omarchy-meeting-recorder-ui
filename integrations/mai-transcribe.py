#!/usr/bin/env python3
"""OpenRouter MAI adapter. Private files, timestamped words, no third-party Python packages."""
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request

MODEL = 'microsoft/mai-transcribe-2'
ENDPOINT = 'https://openrouter.ai/api/v1/audio/transcriptions'
RATE = 16000
CHUNK_SECONDS = 300


def atomic_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
        json.dump(value, out, ensure_ascii=False)
        temporary = Path(out.name)
    temporary.replace(path)


def configuration():
    root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    path = root / 'omarchy-meeting-recorder/config.toml'
    if not path.exists():
        return {}
    with path.open('rb') as f:
        config = tomllib.load(f).get('openrouter', {})
    if not isinstance(config, dict):
        raise ValueError('openrouter must be a TOML table')
    return config


def credential():
    key = os.environ.get('OPENROUTER_API_KEY', '').strip()
    if not key:
        try:
            result = subprocess.run(['secret-tool', 'lookup', 'service',
                                     'omarchy-meeting-recorder', 'credential',
                                     'openrouter-api-key'], capture_output=True, text=True, timeout=15)
            key = result.stdout.strip() if result.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not key:
        raise ValueError('OpenRouter key missing. Set OPENROUTER_API_KEY or store it in the system keyring; see docs/openrouter.md.')
    if any(c in key for c in '\r\n'):
        raise ValueError('Invalid OpenRouter key')
    return key


def normalize(response, duration):
    """Reject text without real word times: guessed times break the player and speakers."""
    if not isinstance(response, dict) or not isinstance(response.get('text'), str):
        raise ValueError('MAI returned no transcript text')
    raw = response.get('words', [])
    if not isinstance(raw, list):
        raise ValueError('MAI returned invalid word timestamps')
    words = []
    previous = -1.0
    for word in raw:
        if not isinstance(word, dict):
            raise ValueError('MAI returned an invalid word')
        text = word.get('word', word.get('text'))
        start, end = word.get('start'), word.get('end')
        if (not isinstance(text, str) or not isinstance(start, (float, int))
                or not isinstance(end, (float, int)) or isinstance(start, bool) or isinstance(end, bool)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end < start or start < previous or end > duration + 1):
            raise ValueError('MAI returned invalid word timestamps')
        previous = start
        if text.strip():
            words.append({'text': text.strip(), 'start_ms': round(min(start, duration) * 1000),
                          'end_ms': round(min(end, duration) * 1000)})
    if response['text'].strip() and not words:
        raise ValueError('MAI returned text without word timestamps; retry the transcription')
    language = response.get('language')
    if not isinstance(language, str):
        languages = response.get('languages', [])
        language = languages[0] if isinstance(languages, list) and languages and isinstance(languages[0], str) else None
    return {'words': words, 'language': language}


def request(audio, language, phrases, key):
    options = {'diarization': {'enabled': False}}
    if phrases:
        options['phraseList'] = {'phrases': phrases}
    payload = {'model': MODEL, 'input_audio': {'data': base64.b64encode(audio).decode(), 'format': 'mp3'},
               'response_format': 'verbose_json', 'timestamp_granularities': ['word', 'segment'],
               'provider': {'options': {'azure': options}}}
    if language != 'auto':
        payload['language'] = language
    body = json.dumps(payload).encode()
    req = urllib.request.Request(ENDPOINT, body, headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            # Never include a response body which might echo credentials or audio.
            raise ValueError(f'OpenRouter returned HTTP {error.code}; check the key, credit and service availability') from None
    raise ValueError('OpenRouter request failed')


def transcribe(args):
    config = configuration()
    phrases = config.get('phrases', [])
    if not isinstance(phrases, list) or not all(isinstance(p, str) for p in phrases):
        raise ValueError('openrouter.phrases must be a list of strings')
    key = credential()
    size = args.input.stat().st_size
    if size % 4:
        raise ValueError('Invalid f32 audio')
    duration = size / (RATE * 4)
    count = max(1, math.ceil(duration / CHUNK_SECONDS))
    cache_root = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'omarchy-meeting-recorder/mai-responses'
    cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    words = []
    detected = None
    with tempfile.TemporaryDirectory(prefix='upload-', dir=args.output.parent) as temporary:
        for index in range(count):
            offset = index * CHUNK_SECONDS
            length = min(CHUNK_SECONDS, duration - offset)
            atomic_json(args.progress, {'progress': index / count, 'stage': f'MAI: transcribing part {index + 1} of {count}'})
            audio = Path(temporary) / 'audio.mp3'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(RATE),
                            '-ac', '1', '-ss', str(offset), '-i', str(args.input), '-t', str(length),
                            '-c:a', 'libmp3lame', '-b:a', '64k', str(audio)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            encoded = audio.read_bytes()
            digest = hashlib.sha256(encoded + json.dumps([MODEL, args.language, phrases, 'v1']).encode()).hexdigest()
            cached = cache_root / (digest + '.json')
            response = None
            if cached.exists():
                try:
                    candidate = json.loads(cached.read_text())
                    normalize(candidate, length)
                    response = candidate
                except (ValueError, OSError, TypeError):
                    pass
            if response is None:
                response = request(encoded, args.language, phrases, key)
                normalize(response, length)
                atomic_json(cached, response)
            result = normalize(response, length)
            detected = detected or result['language']
            for word in result['words']:
                word['start_ms'] += offset * 1000
                word['end_ms'] += offset * 1000
                words.append(word)
    atomic_json(args.output, {'words': words, 'language': detected})
    atomic_json(args.progress, {'progress': 1.0, 'stage': 'MAI transcription ready'})


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--progress', type=Path, required=True)
    parser.add_argument('--language', default='auto')
    args = parser.parse_args()
    try:
        transcribe(args)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, ValueError) else 'MAI transcription failed; check network access and ffmpeg', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
