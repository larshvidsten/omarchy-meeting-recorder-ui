#!/usr/bin/env python3
"""Bridge the upstream editable meeting format to the existing personal Tana workflow."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def write_json(path, value):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        json.dump(value, f, ensure_ascii=False)
        temporary=Path(f.name)
    temporary.replace(path)


def fingerprint(path):
    with path.open('rb') as f:return hashlib.file_digest(f, 'sha256').hexdigest()


def prepare(folder):
    folder=folder.resolve()
    manifests=list(folder.glob('*.meeting-recorder'))
    if len(manifests)!=1:raise ValueError('Expected exactly one meeting manifest')
    manifest=json.loads(manifests[0].read_text())
    markdown=(folder/'transcript.md').read_text()
    duration=int(manifest['duration_secs'])
    started=int(manifest['started_at'])
    if duration<=0 or started<=0:raise ValueError('Meeting start time and duration are required')
    work=folder/'.tana'
    work.mkdir(mode=0o700, exist_ok=True)
    audio=folder/'audio.ogg'
    if not audio.is_file():
        sources=[folder/'mic.ogg',folder/'computer.ogg']
        if not all(p.is_file() for p in sources):raise ValueError('Meeting audio is missing')
        signature=hashlib.sha256(''.join(fingerprint(p) for p in sources).encode()).hexdigest()
        audio=work/f'mix-{signature}.m4a'
        if not audio.exists():
            temporary=audio.with_suffix('.partial.m4a')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(sources[0]),'-i',str(sources[1]),
                            '-filter_complex','amix=inputs=2:duration=longest','-c:a','aac','-b:a','96k',str(temporary)],check=True)
            temporary.replace(audio)
    sha=fingerprint(audio)
    base=work/f'meeting-{started}-{sha[:16]}'
    source=base.with_suffix('.m4a')
    if source.is_symlink():source.unlink()
    if not source.exists():source.symlink_to(audio)
    rows=[]
    for match in re.finditer(r'^\*\*\[([\d:]+)\] (.+?):\*\* (.*(?:\n(?!\n|\*\*\[|##).*)*)', markdown, re.M):
        stamp,speaker,text=match.groups()
        parts=[int(v) for v in stamp.split(':')]
        if len(parts) not in (2,3):raise ValueError('Invalid transcript timestamp')
        seconds=0
        for part in parts:seconds=seconds*60+part
        if seconds<0 or seconds>duration or rows and seconds<rows[-1]['start']:
            raise ValueError('Transcript timestamps are out of order')
        rows.append({'start':seconds,'text':text.strip(),'speaker_label':speaker,'speaker_ambiguous':True})
    if not rows:raise ValueError('No timestamped transcript paragraphs found')
    for i,row in enumerate(rows):row['end']=rows[i+1]['start'] if i+1<len(rows) else duration
    metadata={'schema_version':1,'audio_file':str(source),'source_name':source.name,'started_at':started,
              'ended_at':started+duration,'duration_seconds':duration,'size_bytes':source.stat().st_size,
              'title':manifest.get('title'),'original_meeting':str(folder)}
    data={'schema_version':3,'provider':'meeting-recorder','model':manifest.get('model'),'source':{'audio_file':str(source),'source_name':source.name,'sha256':sha},
          'recording':metadata,'speaker_scope':'recording','text':'\n'.join(r['text'] for r in rows),
          'speaker_names':manifest.get('speakers',[]),'chunks':[{'index':0,'start_seconds':0,'text':markdown,'segments':rows,'words':[]}]}
    write_json(Path(str(base)+'.recording.json'),metadata)
    write_json(Path(str(base)+'.transcript.json'),data)
    transcript=Path(str(base)+'.transcript.md')
    with tempfile.NamedTemporaryFile('w', dir=work, delete=False) as f:
        f.write(markdown); temporary=Path(f.name)
    temporary.replace(transcript)
    return source,transcript


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('meeting',type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    try:
        work=args.meeting.resolve()/'.tana'
        work.mkdir(mode=0o700, exist_ok=True)
        with (work/'action.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('A Tana action is already running for this meeting') from None
            source,transcript=prepare(args.meeting)
            if args.prepare_only:
                print('Prepared Tana input:',transcript)
                return 0
            return subprocess.call(['bash',str(Path(__file__).resolve().parent/'tana/run.sh'),str(source),str(transcript)], pass_fds=(lock.fileno(),))
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
        print('Could not prepare meeting for Tana:',error,file=sys.stderr)
        return 1

if __name__=='__main__':sys.exit(main())
