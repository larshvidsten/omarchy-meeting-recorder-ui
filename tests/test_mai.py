import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location('mai', Path(__file__).parents[1] / 'integrations/mai-transcribe.py')
mai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mai)


def response(text='Hei', start=0.1, end=0.5):
    return {'text': text, 'language': 'no', 'words': [{'word': text, 'start': start, 'end': end}]}


class MaiTests(unittest.TestCase):
    def test_real_times_not_speaker_guesses(self):
        data = response(); data['words'][0]['speaker'] = 5
        self.assertEqual(mai.normalize(data, 1)['words'], [{'text': 'Hei', 'start_ms': 100, 'end_ms': 500}])

    def test_missing_and_invalid_timestamps_fail(self):
        for data in [{'text': 'hei'}, response(start=-1), response(end=float('nan')), response(end=10), response(start=0.7, end=0.5)]:
            with self.subTest(data=data), self.assertRaises(ValueError):mai.normalize(data, 1)

    def test_silence_can_return_empty(self):
        self.assertEqual(mai.normalize({'text': '', 'words': []}, 1)['words'], [])

    def test_invalid_config_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'omarchy-meeting-recorder/config.toml'
            path.parent.mkdir(); path.write_text('openrouter = "wrong"')
            with patch.dict(mai.os.environ, {'XDG_CONFIG_HOME':root}):
                with self.assertRaisesRegex(ValueError,'TOML table'):mai.configuration()

    def test_keyring_missing_is_actionable(self):
        with patch.dict(mai.os.environ, {'OPENROUTER_API_KEY': ''}), patch.object(mai.subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, 'key missing'):mai.credential()

    def test_request_is_bounded_and_has_word_times(self):
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(response()).encode()
        with patch.object(mai.urllib.request, 'urlopen', return_value=Reply()) as call:
            mai.request(b'audio', 'no', ['Digel'], 'test-key')
        req = call.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(body['language'], 'no')
        self.assertEqual(body['timestamp_granularities'], ['word', 'segment'])
        self.assertFalse(body['provider']['options']['azure']['diarization']['enabled'])
        self.assertEqual(call.call_args.kwargs['timeout'], 180)

    def test_http_error_does_not_leak_body_or_key(self):
        error = urllib.error.HTTPError(mai.ENDPOINT, 401, 'secret', {}, None)
        with patch.object(mai.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaisesRegex(ValueError, 'HTTP 401') as caught:mai.request(b'audio','auto',[],'secret')
        self.assertNotIn('secret',str(caught.exception))

    def test_chunk_offsets_and_retry_cache(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            args = SimpleNamespace(input=root/'input.f32', output=root/'out.json', progress=root/'progress.json', language='no')
            args.input.write_bytes(b'\0' * (16000 * 4 * 2))
            def convert(cmd, **kwargs):Path(cmd[-1]).write_bytes(cmd[cmd.index('-ss')+1].encode())
            with patch.dict(mai.os.environ, {'XDG_CACHE_HOME':str(root)}), patch.object(mai,'CHUNK_SECONDS',1), patch.object(mai,'credential',return_value='key'), patch.object(mai,'configuration',return_value={}), patch.object(mai.subprocess,'run',side_effect=convert), patch.object(mai,'request',return_value=response()) as request:
                mai.transcribe(args)
                self.assertEqual([w['start_ms'] for w in json.loads(args.output.read_text())['words']], [100,1100])
                self.assertEqual(request.call_count,2)
                mai.transcribe(args)
                self.assertEqual(request.call_count,2)
                self.assertEqual(json.loads(args.progress.read_text())['progress'],1)

if __name__ == '__main__':unittest.main()
