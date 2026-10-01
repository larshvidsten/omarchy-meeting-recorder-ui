#!/usr/bin/env python3
"""Install a tested personal build alongside system packages, retaining rollback files."""
import argparse
import datetime
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import tomllib


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary',type=Path)
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]
    binary=args.binary.resolve()
    subprocess.run([str(binary),'--version'],check=True)
    revision=subprocess.check_output(['git','rev-parse','--short','HEAD'],cwd=source,text=True).strip()
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    home=Path.home()
    root=home/'.local/share/meeting-recorder-mai'
    release=root/'releases'/f'{stamp}-{revision}'
    backup=root/'backups'/stamp
    backup.mkdir(parents=True,mode=0o700)
    def preserve(path):
        if path.exists() or path.is_symlink():
            target=backup/path.relative_to(home)
            target.parent.mkdir(parents=True,exist_ok=True)
            if path.is_symlink(): target.symlink_to(os.readlink(path))
            else: shutil.copy2(path,target)
    # Validate config before installing anything.
    config=home/'.config/omarchy-meeting-recorder/config.toml'
    old=config.read_text() if config.exists() else ''
    parsed=tomllib.loads(old)
    settings=home/'.local/state/omarchy-meeting-recorder/settings.json'
    prefs=json.loads(settings.read_text()) if settings.exists() else {}
    plugin=home/'.config/omarchy/plugins/jankeesvw.meeting-recorder'
    if plugin.exists() and not plugin.is_symlink():
        raise SystemExit('An existing plugin directory needs to be reconciled before installation: '+str(plugin))
    if 'phrases' in parsed.get('openrouter', {}) and 'provider_options' in parsed.get('openrouter', {}):
        raise SystemExit('Both phrases and provider_options exist; reconcile them before installation')
    if not any(a.get('name')=='Summarize to Tana' for a in parsed.get('action',[])):
        old+='\n[[action]]\nname = "Summarize to Tana"\ncommand = \'python3 "$HOME/.local/share/meeting-recorder-mai/current/integrations/meeting-to-tana.py" "$1"\'\n'
    if 'openrouter' not in parsed:
        old+='\n[openrouter]\n'
        parsed['openrouter'] = {'phrases': ['Digel']}
    if 'backend' not in parsed:
        backend = prefs.get('backend', 'mai')
        if backend not in ('mai', 'openrouter', 'whisper'): backend = 'whisper'
        old = f'backend = "{backend}"\n\n' + old
    old = re.sub(r'(?m)^backend\s*=\s*["\']mai["\']\s*$', 'backend = "openrouter"', old)
    router = parsed.get('openrouter', {})
    if 'phrases' in router:
        if 'provider_options' in router:
            raise SystemExit('Both phrases and provider_options exist; reconcile them before installation')
        options = json.dumps({'azure': {'diarization': {'enabled': False}, 'phraseList': {'phrases': router['phrases']}}})
        lines = old.splitlines(keepends=True)
        inside = False
        migrated = []
        for line in lines:
            if line.strip().startswith('['): inside = line.strip() == '[openrouter]'
            if inside and line.lstrip().startswith('phrases'):
                continue
            migrated.append(line)
            if line.strip() == '[openrouter]':
                migrated.append('provider_options = ' + json.dumps(options) + '\n')
        old = ''.join(migrated)
    tomllib.loads(old)
    (release/'bin').mkdir(parents=True)
    shutil.copy2(binary,release/'bin/omarchy-meeting-recorder')
    shutil.copytree(source/'integrations',release/'integrations',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(source/'plugin',release/'plugin')
    shutil.copytree(source/'docs',release/'docs')
    shutil.copy2(source/'LICENSE',release/'LICENSE')
    (release/'revision.txt').write_text(subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True))
    for path in (config,settings,home/'.config/omarchy/shell.json',root/'current',plugin):preserve(path)
    next_link=root/'current.next'
    if next_link.is_symlink():next_link.unlink()
    next_link.symlink_to(release)
    next_link.replace(root/'current')
    launcher=home/'.local/bin/omarchy-meeting-recorder'
    preserve(launcher); launcher.parent.mkdir(parents=True,exist_ok=True)
    if launcher.exists() or launcher.is_symlink():launcher.unlink()
    launcher.symlink_to(root/'current/bin/omarchy-meeting-recorder')
    plugin.parent.mkdir(parents=True,exist_ok=True)
    if plugin.is_symlink():plugin.unlink()
    plugin.symlink_to(root/'current/plugin')
    desktop=home/'.local/share/applications/omarchy-meeting-recorder.desktop'
    preserve(desktop); desktop.parent.mkdir(parents=True,exist_ok=True)
    text=(source/'data/omarchy-meeting-recorder.desktop').read_text()
    text=text.replace('Exec=omarchy-meeting-recorder', 'Exec='+str(launcher))
    text=text.replace('Comment=Record a meeting in two tracks and transcribe it on this computer','Comment=Record meetings and transcribe with MAI or local Whisper')
    desktop.write_text(text)
    mime=home/'.local/share/mime/packages/omarchy-meeting-recorder.xml'
    preserve(mime); mime.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source/'data/omarchy-meeting-recorder.xml',mime)
    config.parent.mkdir(parents=True,exist_ok=True); config.write_text(old)
    prefs.pop('backend', None)
    prefs.setdefault('language','auto')
    prefs.setdefault('your_name','Lars'); prefs['bar_widget_offered']='yes'
    settings.parent.mkdir(parents=True,exist_ok=True); settings.write_text(json.dumps(prefs))
    for command in (['update-desktop-database',str(desktop.parent)],['update-mime-database',str(mime.parent.parent)]):
        subprocess.run(command,check=True)
    print('Installed:',release)
    print('Rollback files:',backup)
    print('Enable jankeesvw.meeting-recorder and disable lars.meeting-recorder after verifying the app.')

if __name__=='__main__':main()
