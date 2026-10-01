#!/usr/bin/env python3
"""Private, atomic transcript rendering and whole-recording speaker alignment."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.speakers-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dump(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')


def timing(item):
    a, b = item['start'], item['end']
    if (type(a) not in (int, float) or type(b) not in (int, float)
            or not math.isfinite(a) or not math.isfinite(b) or not 0 <= a <= b):
        raise ValueError('Invalid timestamp')
    return a, b


def validate(segments):
    if not isinstance(segments, list):
        raise ValueError('Missing speaker segments')
    for segment in segments:
        timing(segment)
        if type(segment['speaker']) is not int or not 1 <= segment['speaker'] <= 8:
            raise ValueError('Invalid speaker ID')
    return sorted(segments, key=lambda item: item['start'])


def cached(transcript, sidecar, model_hash):
    data = read(sidecar)
    if (data.get('schema_version') != 1 or data.get('source_sha256') != transcript['source']['sha256']
            or data.get('model_sha256') != model_hash or data.get('preset') != 'v3-offline'):
        raise ValueError('Speaker cache is stale')
    validate(data['segments'])
    return data


def clear(transcript):
    for chunk in transcript['chunks']:
        for item in chunk.get('words', []) + chunk.get('segments', []):
            for key in ('speaker', 'speaker_id', 'speaker_ambiguous'):
                item.pop(key, None)
    for key in ('speaker_turns', 'speaker_diarization'):
        transcript.pop(key, None)
    transcript.update(diarization=False, speaker_scope='none')


def align(transcript, segments):
    turns = []
    for chunk in transcript['chunks']:
        # Segment fallback preserves text when a provider omits word timestamps.
        items = chunk.get('words') or chunk.get('segments') or [
            dict(start=chunk['start_seconds'], end=chunk['start_seconds'], text=chunk['text'])]
        for item in items:
            a, b = timing(item)
            overlaps = {}
            for segment in segments:
                if segment['start'] >= b:
                    break
                overlap = min(b, segment['end']) - max(a, segment['start'])
                if overlap > 0:
                    speaker = segment['speaker']
                    overlaps[speaker] = overlaps.get(speaker, 0) + overlap
            ranked = sorted(overlaps, key=lambda speaker: (-overlaps[speaker], speaker))
            speaker = ranked[0] if ranked else None
            ambiguous = len(ranked) > 1 and overlaps[ranked[1]] >= overlaps[speaker] * 0.5
            # Segment-level fallback cannot reliably identify internal speaker switches.
            if not chunk.get('words'):
                speaker = None
            item.update(speaker=speaker, speaker_ambiguous=ambiguous)
            text = item.get('word', item.get('text', '')).strip()
            if not text:
                continue
            if turns and turns[-1]['speaker'] == speaker and 0 <= a - turns[-1]['end'] <= 1.5:
                turns[-1]['text'] += ' ' + text
                turns[-1]['end'] = max(turns[-1]['end'], b)
            else:
                turns.append(dict(start=a, end=b, speaker=speaker, text=text))
    transcript.update(diarization=True, speaker_scope='recording', speaker_turns=turns)


def render(path, transcript):
    lines = ['# Meeting transcript', '', '- Source recording: `' + transcript['source']['source_name'] + '`', '']
    if transcript.get('speaker_scope') == 'recording':
        lines += ['Speaker numbers are consistent within this recording; they are not identified names.', '']
        for turn in transcript['speaker_turns']:
            seconds = int(turn['start'])
            stamp = f'{seconds // 3600:02}:{seconds % 3600 // 60:02}:{seconds % 60:02}'
            lines += [f"[{stamp}] Speaker {turn['speaker'] if turn['speaker'] is not None else 'unknown'}: {turn['text']}", '']
    else:
        lines += [transcript['text'].strip(), '']
    dump(path, transcript)
    atomic(str(path).removesuffix('.json') + '.md', '\n'.join(lines))


def main():
    action, path, *args = sys.argv[1:]
    transcript = read(path)
    if action == 'plain':
        clear(transcript)
        render(path, transcript)
    elif action == 'import':
        sidecar, model_hash, raw = args
        dump(sidecar, dict(schema_version=1, source_sha256=transcript['source']['sha256'],
                           model_sha256=model_hash, preset='v3-offline', segments=validate(read(raw)['segments'])))
    elif action in ('cached', 'align'):
        data = cached(transcript, *args)
        if action == 'align':
            clear(transcript)
            align(transcript, validate(data['segments']))
            transcript['speaker_diarization'] = dict(provider='local-nemotron', model_sha256=args[1], preset='v3-offline', alignment_version=1)
            render(path, transcript)
    else:
        raise ValueError('Unknown operation')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Speaker processing: {error}', file=sys.stderr)
        sys.exit(1)
