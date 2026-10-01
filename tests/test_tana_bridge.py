import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bridge', Path(__file__).parents[1] / 'integrations/meeting-to-tana.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class BridgeTests(unittest.TestCase):
    def meeting(self, root):
        root = Path(root)
        (root/'test.meeting-recorder').write_text(json.dumps({'started_at':1790834400,'duration_secs':60,'title':'Edited meeting','model':'microsoft/mai-transcribe-2','speakers':['Lars','Remote 1']}))
        (root/'audio.ogg').write_bytes(b'test-audio')
        (root/'transcript.md').write_text('# Test\n\n**[00:01] Lars:** Edited text.\nContinued line.\n\n**[00:30] Remote 1:** Agreed.\n')
        return root

    def test_edited_text_and_real_start_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            folder=self.meeting(root)
            source, transcript=bridge.prepare(folder)
            data=json.loads(source.with_suffix('.transcript.json').read_text())
            self.assertEqual(transcript.read_text(),(folder/'transcript.md').read_text())
            self.assertEqual(data['recording']['started_at'],1790834400)
            self.assertEqual(data['chunks'][0]['segments'][0]['text'],'Edited text.\nContinued line.')
            self.assertEqual(data['chunks'][0]['segments'][0]['end'],30)
            self.assertTrue(data['chunks'][0]['segments'][0]['speaker_ambiguous'])
            receipt=source.with_suffix('.tana-receipt.json'); receipt.write_text('keep')
            self.assertEqual(bridge.prepare(folder)[0],source)
            self.assertEqual(receipt.read_text(),'keep')

    def test_bad_timeline_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            folder=self.meeting(root)
            (folder/'transcript.md').write_text('**[02:00] Lars:** Wrong time.\n')
            with self.assertRaisesRegex(ValueError,'timestamps'):bridge.prepare(folder)

    def test_dual_audio_mixed_once(self):
        with tempfile.TemporaryDirectory() as root:
            folder=self.meeting(root); (folder/'audio.ogg').unlink()
            (folder/'mic.ogg').write_bytes(b'mic'); (folder/'computer.ogg').write_bytes(b'remote')
            def convert(args, **kwargs):Path(args[-1]).write_bytes(b'mix')
            with patch.object(bridge.subprocess,'run',side_effect=convert) as run:
                bridge.prepare(folder); bridge.prepare(folder)
                self.assertEqual(run.call_count,1)

if __name__=='__main__':unittest.main()
