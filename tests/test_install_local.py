import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tomllib

spec=importlib.util.spec_from_file_location('installer',Path(__file__).parents[1]/'integrations/install-local.py')
installer=importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)

class InstallTests(unittest.TestCase):
    def test_install_preserves_preferences_and_backups(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root); binary=home/'testbinary'; binary.write_text('binary')
            prefs=home/'.local/state/omarchy-meeting-recorder/settings.json'
            prefs.parent.mkdir(parents=True); prefs.write_text('{"language":"no","backend":"whisper"}')
            config=home/'.config/omarchy-meeting-recorder/config.toml'
            config.parent.mkdir(parents=True); config.write_text('model = "tiny"\n')
            with patch.object(installer.Path,'home',return_value=home),patch.object(installer.sys if hasattr(installer,'sys') else __import__('sys'),'argv',['installer',str(binary)]),patch.object(installer.subprocess,'run'),patch.object(installer.subprocess,'check_output',return_value='abc123\n'):
                installer.main()
            self.assertNotIn('backend', json.loads(prefs.read_text()))
            self.assertEqual(tomllib.loads(config.read_text())['backend'], 'whisper')
            self.assertEqual(tomllib.loads(config.read_text())['model'],'tiny')
            self.assertEqual(tomllib.loads(config.read_text())['action'][0]['name'],'Summarize to Tana')
            self.assertTrue((home/'.local/bin/omarchy-meeting-recorder').is_file())
            # A later install must honor explicit config over legacy UI state.
            config.write_text(config.read_text().replace('backend = "whisper"', 'backend = "mai"'))
            prefs.write_text('{"backend":"whisper"}')
            with patch.object(installer.Path,'home',return_value=home),patch.object(__import__('sys'),'argv',['installer',str(binary)]),patch.object(installer.subprocess,'run'),patch.object(installer.subprocess,'check_output',return_value='abc123\n'),patch.object(installer.datetime,'datetime') as clock:
                clock.now.return_value.strftime.return_value='second-install'
                installer.main()
            self.assertEqual(tomllib.loads(config.read_text())['backend'], 'openrouter')
            self.assertIn('azure', json.loads(tomllib.loads(config.read_text())['openrouter']['provider_options']))
            backups=list((home/'.local/share/meeting-recorder-mai/backups').glob('*/.config/omarchy-meeting-recorder/config.toml'))
            self.assertIn('model = "tiny"\n', [p.read_text() for p in backups])

if __name__=='__main__':unittest.main()
