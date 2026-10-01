"""Run the shipped action through a fake Codex/MCP boundary, without network or Tana writes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
log=Path(os.environ['FAKE_CALLS'])
def record(value):
    with log.open('a') as f:f.write(value+'\n')
if sys.argv[1]=='exec':
    schema=Path(sys.argv[sys.argv.index('--output-schema')+1]).name
    stage='context' if 'context' in schema else 'draft'
    record(stage)
    data={'event_context':'Test meeting','destination_context':'Test space','type_definition':'Digel Meeting Note'} if stage=='context' else {'note_title':'Test note','blocks':['Decision: run the tests.'],'fields_json':'{}','destination_context':'Test space','owner_uri':'top-level'}
    Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(data))
else:
    for line in sys.stdin:
        req=json.loads(line)
        if 'id' not in req:continue
        method=req['method']
        result={}
        if method=='thread/start':result={'thread':{'id':'test-thread'}}
        if method=='mcpServer/tool/call':
            tool=req['params']['tool']; record(tool)
            if tool=='searchItems':result={'structuredContent':{'items':[]}}
            elif tool=='createItems':
                if os.environ.get('FAKE_FAIL'):result={'isError':True}
                else:result={'structuredContent':{'items':[{'id':'tana:text:test','title':'Test note'}]}}
            else:raise RuntimeError('Unexpected tool '+tool)
        print(json.dumps({'id':req['id'],'result':result}),flush=True)
'''

class TanaFlowTests(unittest.TestCase):
    def fixture(self, root):
        # Copy only what the installer ships: this catches omitted runtime dependencies.
        shipped=root/'installed'
        shutil.copytree(ROOT/'integrations',shipped,ignore=shutil.ignore_patterns('__pycache__'))
        meeting=root/'meeting with spaces'; meeting.mkdir()
        (meeting/'test.meeting-recorder').write_text(json.dumps({'started_at':1790834400,'duration_secs':10,'title':'Test','speakers':['Speaker 1']}))
        (meeting/'audio.ogg').write_bytes(b'local test fixture')
        (meeting/'transcript.md').write_text('**[00:01] Speaker 1:** Run the tests.\n')
        fake=root/'fake-codex'; fake.write_text(FAKE); fake.chmod(0o700)
        env={**os.environ,'MR_CODEX':str(fake),'FAKE_CALLS':str(root/'calls')}
        command=[sys.executable,str(shipped/'meeting-to-tana.py'),str(meeting)]
        return meeting,env,command

    def test_complete_flow_and_receipt_prevent_repeat_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); meeting,env,command=self.fixture(root)
            first=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(first.returncode,0,first.stderr)
            self.assertIn('tana:text:test',first.stdout)
            calls=(root/'calls').read_text().splitlines()
            self.assertEqual(calls,['context','draft','searchItems','createItems'])
            second=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(second.returncode,0,second.stderr)
            self.assertEqual((root/'calls').read_text().splitlines(),calls)
            result=json.loads(next((meeting/'.tana').glob('*.tana.json')).read_text())
            self.assertTrue(result['delivery_confirmed'])

    def test_failed_delivery_keeps_draft_and_retry_skips_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); meeting,env,command=self.fixture(root)
            failed=subprocess.run(command,env={**env,'FAKE_FAIL':'1'},capture_output=True,text=True,timeout=20)
            self.assertNotEqual(failed.returncode,0)
            self.assertIn('Tana rejected createItems',failed.stderr)
            self.assertTrue(list((meeting/'.tana').glob('*.tana-draft.json')))
            self.assertFalse(list((meeting/'.tana').glob('*.tana-receipt.json')))
            retried=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(retried.returncode,0,retried.stderr)
            calls=(root/'calls').read_text().splitlines()
            self.assertEqual(calls.count('context'),1)
            self.assertEqual(calls.count('draft'),1)
            self.assertEqual(calls.count('createItems'),2)

if __name__=='__main__':unittest.main()
