# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The session: a machine served to the CyberiadaPro editor step by step
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

"""A driven session with the async logic (docs/API.md, Sessions): JSON-RPC 2.0
lines on stdin and stdout, the dispatcher on a virtual clock."""

import argparse
import json
import queue
import sys
import threading
import time

import hsmd
import hsmd_stream

SESSION_VERSION = 1
DEFAULT_PERIOD = 0.1
# the periods an event step or a run waits for an event before it gives up
IDLE_PERIODS = 1000
WAIT_SLICE_S = 0.05
# a run sends its state at most this often; the history goes out always
RUN_STATE_INTERVAL_S = 0.05
SPEEDS = [1, 10, 0]
UNITS = ['event', 'input', 'time']
TIME_DIGITS = 6
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

RUNNING = 'running'
PAUSED = 'paused'
WAITING = 'waiting'
FINISHED = 'finished'


class _NoInput:
    """The input of a Console: stdin is the channel, so it ends at once."""

    @staticmethod
    def read():
        return ''


class _LogWriter:
    """A text stream whose lines go out as log messages."""

    def __init__(self, send):
        self.send = send
        self.buffer = ''

    def write(self, text):
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self.send(line)
        return len(text)

    def flush(self):
        if self.buffer:
            line, self.buffer = self.buffer, ''
            self.send(line)


def element(ident):
    """The document element of a trace id: an internal transition <state>#<n>
    and an element of an inlined submachine <state>/<id> name their state."""
    return ident.split('#', 1)[0].split('/', 1)[0]


def unique(ids):
    seen = []
    for ident in ids:
        if ident not in seen:
            seen.append(ident)
    return seen


def json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


class Session:
    """make(**options) returns a new Dispatcher built with the options given
    (clock, calendar, trace, output, input, timers), at the start and at every
    restart; period is the step of the virtual clock in seconds; start(dispatcher)
    enters the initial states and returns the outcomes (dispatcher.start() by
    default); loop() runs at every period before the tick."""

    def __init__(self, make, period=DEFAULT_PERIOD, start=None, loop=None):
        self.make = make
        self.period = period
        self.start = start if start is not None else lambda dispatcher: dispatcher.start()
        self.loop = loop
        self.dispatcher = None
        self.now = 0.0
        self.base = 0.0
        self.stream = hsmd_stream.Stream()
        self.position = 0
        self.records = []
        self.origins = {}        # id(event) -> (event, origin) of the events the session posts
        self.inputs = []         # the items and the events posted, for save
        self.status = PAUSED
        self.text = ''
        self.out = None
        self.messages = queue.Queue()
        self.running = False
        self.speed = SPEEDS[0]
        self.run_wall = 0.0
        self.run_virtual = 0.0
        self.idle = 0
        self.last_state = 0.0
        self.done = False
        self.code = 0

    # ------------------------------------------------------------------------
    # the channel

    def serve(self, reader=None, writer=None):
        """Run the session until shutdown or the end of the input; the exit code."""
        reader = reader if reader is not None else sys.stdin
        self.out = writer if writer is not None else sys.stdout
        prints = _LogWriter(self.log)
        saved = sys.stdout
        # the prints of the code go out as log messages, the channel keeps its stream
        sys.stdout = prints
        threading.Thread(target=self._read, args=(reader,), daemon=True).start()
        try:
            while not self.done:
                if self.running:
                    while not self.messages.empty() and not self.done:
                        self.handle(self.messages.get())
                    if self.running and not self.done:
                        self.run_once()
                else:
                    self.handle(self.messages.get())
        finally:
            prints.flush()
            sys.stdout = saved
        return self.code

    def _read(self, reader):
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                self.messages.put(message)
        # the end of the input ends the session
        self.messages.put({'method': 'shutdown'})

    def send(self, message):
        message = dict(message, jsonrpc='2.0')
        self.out.write(json.dumps(message, ensure_ascii=False, separators=(',', ':')) + '\n')
        self.out.flush()

    def notify(self, method, params):
        self.send({'method': method, 'params': params})

    def reply(self, ident, result):
        if ident is not None:
            self.send({'id': ident, 'result': result})

    def reply_error(self, ident, code, text, data=None):
        error = {'code': code, 'message': text}
        if data is not None:
            error['data'] = data
        if ident is not None:
            self.send({'id': ident, 'error': error})

    def log(self, text, level=None):
        params = {'text': text}
        if level is not None:
            params['level'] = level
        self.notify('log', params)

    def handle(self, message):
        method = message.get('method')
        ident = message.get('id')
        params = message.get('params')
        params = params if isinstance(params, dict) else {}
        if method is None:
            return                   # a reply: the session asks nothing
        if method == 'initialize':
            self.initialize(ident)
        elif method == 'control':
            self.control(params)
        elif method == 'event':
            self.post_event(params)
        elif method == 'input':
            self.input(ident, params)
        elif method == 'save':
            self.save(ident, params)
        elif method == 'shutdown':
            self.reply(ident, {})
            self.done = True
        elif ident is not None:
            self.reply_error(ident, METHOD_NOT_FOUND, 'unknown method {}'.format(method))

    # ------------------------------------------------------------------------
    # the messages

    def initialize(self, ident):
        try:
            outcomes = self.restart()
        except hsmd.DocumentError as e:
            self.dispatcher = None
            outcomes = []
            problem = str(e)
        except Exception as e:  # pylint: disable=broad-except
            outcomes = []
            problem = self.failure(e)
        else:
            problem = None
        if self.dispatcher is None:
            # the document is refused: no model to offer
            self.reply_error(ident, INTERNAL_ERROR, problem)
            self.code = 1
            self.done = True
            return
        self.reply(ident, {'kind': 'driven', 'logic': 'async', 'steps': UNITS, 'speeds': SPEEDS,
                           'events': self.triggers(), 'stream': True, 'save': True})
        self.report(outcomes)

    def control(self, params):
        command = params.get('command')
        if command == 'run':
            speed = params.get('speed', SPEEDS[0])
            self.speed = speed if isinstance(speed, (int, float)) and speed >= 0 else SPEEDS[0]
            self.running = True
            self.status = RUNNING
            self.run_wall = time.monotonic()
            self.run_virtual = self.now
            self.idle = 0
            self.report([])
        elif command == 'pause':
            self.running = False
            self.status = PAUSED
            self.report([])
        elif command == 'restart':
            self.running = False
            self.report(self.guarded(self.restart))
        elif command == 'step':
            self.running = False
            unit = params.get('unit', UNITS[0])
            steps = {'event': self.step_event, 'input': self.step_input, 'time': self.step_time}
            self.status = PAUSED
            self.report(self.guarded(steps.get(unit, self.step_event)))

    def post_event(self, params):
        name = params.get('name')
        if not isinstance(name, str) or not name or self.dispatcher is None:
            return
        values = params.get('params') if isinstance(params.get('params'), dict) else {}
        values = {k: hsmd_stream.parse_value(v) if isinstance(v, str) else v for k, v in values.items()}
        self.guarded(lambda: self.post(name, values, 'user'))
        if not self.running:
            self.report([])

    def input(self, ident, params):
        text = params.get('text')
        if isinstance(params.get('path'), str):
            try:
                with open(params['path'], encoding='utf-8') as source:
                    text = source.read()
            except OSError as e:
                self.reply_error(ident, INVALID_PARAMS, 'the stream cannot be read: {}'.format(e))
                return
        try:
            stream = hsmd_stream.read(text if isinstance(text, str) else '')
        except hsmd_stream.StreamError as e:
            self.reply_error(ident, INVALID_PARAMS, 'the stream is not read',
                             [{'line': e.line, 'message': e.message}])
            return
        self.stream = stream
        items = []
        for item in stream.items:
            entry = {'event': item.name}
            if item.parameters:
                entry['params'] = {k: json_value(v) for k, v in item.parameters.items()}
            if item.time is not None:
                entry['time'] = round(item.time, TIME_DIGITS)
            items.append(entry)
        self.reply(ident, {'items': items})
        # the session starts again with the stream (docs/PLUGIN-API.md, Sessions)
        self.running = False
        self.report(self.guarded(self.restart))

    def save(self, ident, params):
        path = params.get('path')
        items = [hsmd_stream.Item(when, name, values)
                 for when, name, values in sorted(self.inputs, key=lambda entry: entry[0])]
        try:
            with open(path, 'w', encoding='utf-8') as target:
                target.write(hsmd_stream.write(hsmd_stream.Stream(items, self.stream.timers)))
        except (OSError, TypeError) as e:
            self.reply_error(ident, INTERNAL_ERROR, 'the log cannot be written: {}'.format(e))
            return
        self.reply(ident, {})

    # ------------------------------------------------------------------------
    # the machine on the virtual clock

    def restart(self):
        """A new dispatcher, the clock at 0, the stream from its first item."""
        self.now = 0.0
        self.position = 0
        self.inputs = []
        self.origins = {}
        self.text = ''
        self.status = PAUSED
        self.base = self.stream.start if self.stream.start is not None else time.time()
        del self.records[:]
        self.dispatcher = self.make(
            clock=lambda: self.now, calendar=lambda: self.base + self.now,
            trace=self.records.append, output=_LogWriter(self.log), input=_NoInput(),
            timers=self.stream.timers != hsmd_stream.TIMERS_RECORDED)
        return self.stamp(self.start(self.dispatcher) or [])

    def stamp(self, outcomes):
        """The outcomes with the time they happened at, for the history."""
        return [(self.now, outcome) for outcome in outcomes]

    def guarded(self, operation):
        """The outcomes of an operation; an error stops the machine (finished)."""
        try:
            return operation()
        except Exception as e:  # pylint: disable=broad-except
            self.failure(e)
            return []

    def failure(self, error):
        self.running = False
        self.text = str(error)
        self.log(self.text, 'error')
        if self.dispatcher is not None:
            self.dispatcher.stopped = True
        return self.text

    def post(self, name, values, origin):
        event = self.dispatcher.post(name, **values)
        self.origins[id(event)] = (event, origin)
        self.inputs.append((self.now, name, dict(values)))
        return event

    def next_item(self):
        items = self.stream.items
        return items[self.position] if self.position < len(items) else None

    def post_item(self):
        item = self.next_item()
        self.position += 1
        self.post(item.name, item.parameters, 'input')

    def post_due(self):
        """The timed stream items whose time has come."""
        item = self.next_item()
        while item is not None and item.time is not None and item.time <= self.now:
            self.post_item()
            item = self.next_item()

    def tick(self, run):
        if self.loop is not None:
            self.loop()
        return self.stamp(self.dispatcher.tick(run=run))

    def advance(self, run, items=True):
        """One period of the virtual clock: at an instant the events of the model
        go first, the stream items after them."""
        self.now = round(self.now + self.period, TIME_DIGITS)
        outcomes = self.tick(run)
        if items:
            self.post_due()
            if run:
                outcomes += self.stamp(self.dispatcher.run())
        return outcomes

    def step_event(self):
        """One event of the queue; the clock goes on until there is one."""
        if not self.dispatcher.queued():
            item = self.next_item()
            if item is not None and item.time is None:
                self.post_item()
        idle = 0
        while not self.dispatcher.queued():
            if idle >= IDLE_PERIODS:
                self.status = WAITING
                return []
            self.advance(run=False)
            idle += 1
        return self.stamp([self.dispatcher.step()])

    def step_input(self):
        """The next stream item, after everything due before it."""
        item = self.next_item()
        if item is None:
            return self.step_event()
        outcomes = []
        if item.time is not None:
            while self.now + self.period <= item.time:
                outcomes += self.advance(run=True, items=False)
            if self.now < item.time:
                self.now = round(item.time, TIME_DIGITS)
                outcomes += self.tick(run=True)
        self.post_item()
        return outcomes + self.stamp(self.dispatcher.run())

    def step_time(self):
        return self.advance(run=True)

    def run_once(self):
        """One event or one period of a run."""
        if self.finished():
            self.running = False
            self.report([])
            return
        d = self.dispatcher
        if self.speed > 0 and not d.queued():
            # the virtual clock follows the wall clock times the speed
            allowed = self.run_virtual + (time.monotonic() - self.run_wall) * self.speed
            if self.now + self.period > allowed:
                time.sleep(min(WAIT_SLICE_S, (self.now + self.period - allowed) / self.speed))
                return
        if self.speed == 0 and not d.queued() and self.next_item() is None and \
                self.stream.items and self.position >= len(self.stream.items):
            # a replay as fast as possible ends with its stream
            self.running = False
            self.status = PAUSED
            self.report([])
            return
        outcomes = self.guarded(lambda: self.run_step(d))
        if not self.running:
            self.report(outcomes)
            return
        self.report(outcomes, throttled=True)

    def run_step(self, d):
        if d.queued():
            self.idle = 0
            return self.stamp([d.step()])
        item = self.next_item()
        if item is not None and item.time is None:
            self.post_item()
            return []
        outcomes = self.advance(run=False)
        if not d.queued():
            self.idle += 1
            if self.speed == 0 and self.idle >= IDLE_PERIODS:
                self.running = False
                self.status = WAITING
        return outcomes

    # ------------------------------------------------------------------------
    # the state and the history

    def finished(self):
        d = self.dispatcher
        return d is None or d.stopped or all(d.finished(m) for m in d.machines())

    def triggers(self):
        d = self.dispatcher
        return unique(t for m in d.machines() for t in d.triggers(m))

    def report(self, outcomes, throttled=False):
        """A history message per outcome, then the state."""
        for when, outcome in outcomes:
            if outcome is None:
                continue
            event = outcome.event
            row = {'event': event.name, 'time': round(when, TIME_DIGITS),
                   'origin': self.origins.get(id(event), (None, 'model'))[1],
                   'outcome': outcome.status,
                   'fired': unique(element(t) for t in outcome.transitions)}
            if event.parameters:
                row['params'] = {k: json_value(v) for k, v in event.parameters.items()}
            self.notify('history', row)
        if throttled and time.monotonic() - self.last_state < RUN_STATE_INTERVAL_S:
            return
        self.last_state = time.monotonic()
        d = self.dispatcher
        status = FINISHED if self.finished() else (RUNNING if self.running else self.status)
        params = {'status': status, 'text': self.text, 'time': round(self.now, TIME_DIGITS),
                  'fired': unique(element(r[2]) for r in self.records if r[0] == 'fire')}
        del self.records[:]
        if d is not None:
            params['active'] = unique(element(s) for m in d.machines() for s in d.states(m))
            params['events'] = self.triggers()
            params['queue'] = [e.name for e in d.queued()]
        if self.stream.items:
            params['position'] = self.position
        self.notify('state', params)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Serve a state machine diagram to the CyberiadaPro editor step by step.')
    parser.add_argument('document', help='the CyberiadaML document')
    parser.add_argument('--period', type=float, default=DEFAULT_PERIOD,
                        help='the step of the clock in seconds (default {})'.format(DEFAULT_PERIOD))
    parser.add_argument('--machines', help='the machines to run, A,B (default: all)')
    args = parser.parse_args(argv)
    machines = args.machines.split(',') if args.machines else None

    def make(**options):
        return hsmd.Dispatcher(args.document, period=args.period, machines=machines, **options)

    return Session(make, args.period).serve()


if __name__ == '__main__':
    sys.exit(main())
