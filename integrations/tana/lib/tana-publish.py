#!/usr/bin/env python3
"""Send a prepared note through Codex's authenticated MCP client, with no model turn."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
from importlib.machinery import SourceFileLoader
state = SourceFileLoader('tana_state', str(Path(__file__).with_name('tana-state.py'))).load_module()


class Client:
    def __init__(self, cwd):
        self.process = subprocess.Popen([os.environ.get('MR_CODEX', 'codex'), 'app-server'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)
        self.messages = queue.Queue()
        self.sequence = 0
        def read():
            try:
                for line in self.process.stdout:
                    self.messages.put(json.loads(line))
            except (ValueError, OSError):
                pass
            finally:
                self.messages.put(None)
        threading.Thread(target=read, daemon=True).start()
        try:
            self.request('initialize', {'clientInfo': {'name':'meeting_recorder', 'version':'1.0'},
                                        'capabilities': {'experimentalApi':True}})
            self.send({'method':'initialized'})
            result = self.request('thread/start', {'ephemeral':True, 'cwd':str(cwd),
                                                  'sandbox':'read-only', 'approvalPolicy':'never'})
            self.thread = result['thread']['id']
        except Exception:
            self.close()
            raise

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def request(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.send({'id':request_id, 'method':method, 'params':params})
        deadline = time.monotonic() + 180
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError('Codex MCP request timed out; saved draft retained') from None
            if message is None:
                raise RuntimeError('Codex MCP connection closed; saved draft retained')
            if message.get('id') == request_id and 'method' not in message:
                if 'error' in message:
                    raise RuntimeError('Codex MCP request failed: ' + str(message['error'].get('message','unknown error')))
                return message['result']
            if 'id' in message and 'method' in message:
                self.send({'id':message['id'], 'error':{'code':-32601,'message':'Interactive requests are not supported by the recorder'}})

    def call(self, tool, arguments):
        result = self.request('mcpServer/tool/call', {'threadId':self.thread, 'server':'tana',
                                                    'tool':tool, 'arguments':arguments})
        if result.get('isError'):
            raise RuntimeError('Tana rejected ' + tool + '; saved draft retained')
        if isinstance(result.get('structuredContent'), dict):
            return result['structuredContent']
        for block in result.get('content', []):
            if block.get('type') == 'text':
                try:
                    value = json.loads(block['text'])
                    if isinstance(value, dict):
                        return value
                except ValueError:
                    continue
        raise RuntimeError('Tana returned an unreadable ' + tool + ' result')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()



def documents(value):
    """Find document references in structured MCP results, deduplicated by URI."""
    found = {}
    def visit(node):
        if isinstance(node, dict):
            uri = node.get('id', node.get('uri', ''))
            if isinstance(uri, str) and uri.startswith('tana:text:'):
                found[uri] = node
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return found


def body_text(item):
    def flatten(blocks):
        lines = []
        for block in blocks:
            if isinstance(block, list) and len(block) >= 2:
                if isinstance(block[1], str):
                    lines.append(block[1])
                if len(block) >= 3 and isinstance(block[2], list):
                    lines.extend(flatten(block[2]))
        return lines
    if isinstance(item.get('editableBlocks'), list):
        return '\n'.join(flatten(item['editableBlocks']))
    if isinstance(item.get('content'), str):
        return item['content']
    raise ValueError('Tana did not return readable note content for duplicate search')


def payload_for(draft):
    fields = json.loads(draft['fields_json'] or '{}')
    if isinstance(fields, dict) and 'fields' in fields and isinstance(fields['fields'], dict):
        fields = fields['fields']  # Compatibility with older saved drafts.
    if not isinstance(fields, dict):
        raise ValueError('Draft fields must be an object')
    owner = draft.get('owner_uri')
    if not owner:
        owners = set(re.findall(r'tana:space:[a-zA-Z0-9]+', draft['destination_context']))
        if len(owners) != 1:
            raise ValueError('Draft is missing its destination space')
        owner = owners.pop()
    if owner != 'top-level' and not re.fullmatch(r'tana:space:[a-zA-Z0-9]+', owner):
        raise ValueError('Invalid Tana destination space')
    return {'autoApprove': True, 'ownerUri':owner,
            'recap':'Lagrer møteoppsummeringen med beslutninger og oppfølginger.',
            'items':[{'title':draft['note_title'], 'type':'Digel Meeting Note',
                      'content':'\n\n'.join(draft['blocks']), 'fields':fields}]}


def existing_note(client, fingerprint, basename, title):
    result = client.call('searchItems', {'queries':[fingerprint, basename, title],
                         'targets':[{'target':'text','type':'Digel Meeting Note'}], 'limit':100})
    if not isinstance(result.get('items'), list):
        raise ValueError('Tana search failed; cannot safely create another note')
    hits = documents(result)
    if len(hits) >= 100:
        raise ValueError('Tana search is truncated; cannot safely create another note')
    if not hits:
        return None
    notes = client.call('readItems', {'ids':list(hits), 'forEditing':True})
    matches = []
    for uri, note in documents(notes).items():
        body = body_text(note)
        if 'Source recording SHA256: ' + fingerprint in body or 'Source recording: ' + basename in body:
            matches.append((uri, note.get('title', title)))
    if len(matches) > 1:
        raise ValueError('Multiple notes already exist for this recording; no new note created')
    if matches:
        return matches[0]
    if any(hit.get('title') == title for hit in hits.values()):
        raise ValueError('A different note already uses this title; no new note created')
    return None


def publish(draft_path, receipt_path, fingerprint, basename, client_factory=Client):
    cached = state.helpers.read(draft_path)
    draft = state.validate('draft', cached['result'])
    payload = payload_for(draft)
    payload_path = str(receipt_path).replace('.tana-receipt.json', '.tana-payload.json')
    if payload_path == str(receipt_path):
        payload_path += '.payload.json'
    state.helpers.dump(payload_path, payload)
    client = client_factory(Path(draft_path).parent)
    try:
        existing = existing_note(client, fingerprint, basename, draft['note_title'])
        if existing:
            uri, title = existing
            status = 'already_exists'
        else:
            response = client.call('createItems', payload)
            # Keep the server response even if its shape changes after the write.
            state.helpers.dump(str(receipt_path) + '.response.json', response)
            refs = documents(response)
            if len(refs) == 1:
                uri, note = next(iter(refs.items()))
                title = note.get('title', draft['note_title'])
            else:
                existing = existing_note(client, fingerprint, basename, draft['note_title'])
                if not existing:
                    raise ValueError('Tana returned no note URI; response saved. Retry lookup without rewriting the summary')
                uri, title = existing
            status = 'created'
        receipt = dict(status=status, note_title=title, session_uri=uri,
                       message='Møtenotatet er lagret i Tana.' if status == 'created' else 'Møtenotatet finnes allerede i Tana.')
        state.validate('publish', receipt)
        state.helpers.dump(receipt_path, dict(schema_version=2, source_sha256=fingerprint,
                                              cache_key=cached.get('cache_key'), result=receipt))
    finally:
        client.close()


if __name__ == '__main__':
    try:
        publish(*sys.argv[1:])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f'Tana delivery: {error}', file=sys.stderr)
        sys.exit(1)
