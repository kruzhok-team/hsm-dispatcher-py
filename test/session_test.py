#!/usr/bin/python3
# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The tests of the session: a scripted editor, the transcript against a good one
#
#  Copyright (C) 2026 Alexey Fedoseev <aleksey@fedoseev.net>
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program. If not, see https://www.gnu.org/licenses/
#
#  -----------------------------------------------------------------------------

import difflib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION = os.path.join(os.path.dirname(TEST_DIR), 'hsmd_session.py')
GRAPHS_DIR = os.path.join(TEST_DIR, 'graphs')
GOOD = os.path.join(TEST_DIR, 'good', 'session.txt')
WAIT_S = 30
# a request no session knows: its error reply closes the replies to a message
MARK = 'mark'
MARK_BASE = 1000
TMP = '<tmp>'

STREAM = '0.300 SHOW\n0.500 STOP\nRESUME\n'
RECORDED = '# timers: recorded\n0.050 t1.TIMEOUT\n0.150 SHOW\n'
BAD = '1.0 SHOW\n0.5 STOP\n'


def control(command, **params):
    return {'method': 'control', 'params': dict(params, command=command)}


def script(tmp):
    return [
        {'id': 1, 'method': 'initialize', 'params': {'session': 1, 'language': 'en'}},
        # both timers fall due at 0.1: one event a step, the priority first
        control('step', unit='event'),
        control('step', unit='event'),
        control('step', unit='time'),
        {'method': 'event', 'params': {'name': 'SHOW', 'params': {}}},
        control('step', unit='event'),
        # a stream: the timers due before a record come first
        {'id': 2, 'method': 'input', 'params': {'text': STREAM}},
        control('step', unit='input'),
        control('step', unit='input'),
        control('step', unit='input'),
        {'id': 3, 'method': 'save', 'params': {'path': os.path.join(tmp, 'session.log')}},
        control('restart'),
        # as fast as possible to the end of the stream
        control('run', speed=0),
        {'id': 4, 'method': 'input', 'params': {'text': BAD}},
        # the timeouts come from the log: the timers of the model are muted
        {'id': 5, 'method': 'input', 'params': {'text': RECORDED}},
        control('step', unit='input'),
        control('step', unit='input'),
        {'id': 6, 'method': 'shutdown'},
    ]


def canonical(message, tmp):
    message = dict(message)
    message.pop('jsonrpc', None)
    return json.dumps(message, sort_keys=True, separators=(',', ':')).replace(tmp, TMP)


class Client:
    """The editor's side: the lines of the session through a queue."""

    def __init__(self):
        # the process outlives the constructor: killed by transcript()
        self.process = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, '-B', SESSION, '10-timer.graphml', '--period', '0.05'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True,
            cwd=GRAPHS_DIR, bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.process.stdout:
            self.lines.put(json.loads(line))
        self.lines.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(dict(message, jsonrpc='2.0')) + '\n')
        self.process.stdin.flush()

    def until(self, done):
        """The messages up to the one done() accepts, without it."""
        received = []
        while True:
            message = self.lines.get(timeout=WAIT_S)
            if message is None or done(message):
                return received, message
            received.append(message)


def transcript(tmp):
    client = Client()
    lines = []
    try:
        for n, message in enumerate(script(tmp)):
            lines.append('-> ' + canonical(message, tmp))
            client.send(message)
            if message.get('method') == 'shutdown':
                received, last = client.until(lambda m, i=message['id']: m.get('id') == i)
                received.append(last)
            elif message.get('params', {}).get('command') == 'run':
                # a run: its states are paced by the wall clock, its history is not
                received, last = client.until(
                    lambda m: m.get('method') == 'state' and m['params']['status'] != 'running')
                received = [m for m in received if m.get('method') != 'state'] + [last]
            else:
                client.send({'id': MARK_BASE + n, 'method': MARK})
                received, _ = client.until(lambda m, n=n: m.get('id') == MARK_BASE + n)
            lines += ['<- ' + canonical(m, tmp) for m in received]
        code = client.process.wait(timeout=WAIT_S)
    finally:
        client.process.kill()
    lines.append('exit {}'.format(code))
    with open(os.path.join(tmp, 'session.log'), encoding='utf-8') as saved:
        lines += ['== saved'] + saved.read().splitlines()
    return '\n'.join(lines) + '\n'


def main():
    with tempfile.TemporaryDirectory() as tmp:
        output = transcript(tmp)
    if '--regen' in sys.argv:
        with open(GOOD, 'w', encoding='utf-8') as good:
            good.write(output)
        print('SAVE session')
        return 0
    with open(GOOD, encoding='utf-8') as good:
        expected = good.read()
    if output != expected:
        print('FAIL session')
        sys.stdout.writelines(difflib.unified_diff(expected.splitlines(True), output.splitlines(True),
                                                   'good', 'output'))
        return 1
    print('ok   session')
    return 0


if __name__ == '__main__':
    sys.exit(main())
