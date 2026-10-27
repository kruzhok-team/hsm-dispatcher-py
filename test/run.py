#!/usr/bin/python3
# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The test runner: plays the scenarios and compares the traces
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

import ast
import difflib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TEST_DIR))

# HSMD_BACKEND=cml runs the scenarios on the pure-Python interface even
# where the binding is installed
if os.environ.get('HSMD_BACKEND') == 'cml':
    from cyberiadaml_py import cml  # pylint: disable=wrong-import-position
    sys.modules['CyberiadaML'] = cml

import hsmd  # pylint: disable=wrong-import-position
import hsmd_components  # pylint: disable=wrong-import-position

GRAPHS_DIR = os.path.join(TEST_DIR, 'graphs')
MACHINES_DIR = os.path.join(TEST_DIR, 'machines')
SCRIPTS_DIR = os.path.join(TEST_DIR, 'scripts')
GOOD_DIR = os.path.join(TEST_DIR, 'good')
# the validator of the standard, used when the repository is found
VALIDATOR_DIR = os.path.join(TEST_DIR, '..', '..', 'cyberiadaml-compat-tests')

MS_IN_SECOND = 1000
# the calendar time of the scenarios at their clock 0: a local time far from the
# changes of the daylight saving time, 2026-06-15 08:59:00, a Monday
CALENDAR_START = time.mktime((2026, 6, 15, 8, 59, 0, 0, 0, -1))
# the diagrams that break the standard on purpose, each loaded with `error
# load` in a scenario: the file and the requirement the validator names
EXPECTED_FINDINGS = {'19-submachine-point.graphml': ('CGML-8.1-4',)}
ERROR_COMMAND = 'error'
# a line with its newline, a text without it, the end of the input
INPUT_COMMANDS = ('input', 'input-raw', 'input-close')
COMMENT = '#'


class Counter(hsmd.Component):
    """The test component: a number the diagram changes and reads."""

    def __init__(self, ident, dispatcher, **parameters):
        hsmd.Component.__init__(self, ident, dispatcher, **parameters)
        self.value = 0

    def add(self, amount):
        self.value += amount

    def snapshot(self):
        return self.value

    def restore(self, data):
        self.value = data


class Bus(hsmd.Component):
    """The test component shared by the machines: a signal with a text."""

    shared = True

    def ping(self, text=''):
        self.signal('PING', text=text)


hsmd.register('Counter', Counter)
hsmd.register('Bus', Bus)


def parse_value(text):
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def declare(machine):
    """The declarations of a machine read from a document, with its text:
    the round trip of --built."""
    def reaction(r):
        return {'guard': r.guard or None, 'action': r.behavior or None,
                'propagate': r.propagation, 'defer': r.defer}

    def vertex(v):
        if v.kind in ('state', 'composite'):
            return hsmd.State(v.name, id=v.id, entry=[b.text for b in v.entry],
                              exit=[b.text for b in v.exit],
                              internal=[hsmd.On(r.trigger, **reaction(r))
                                        for r in v.reactions if r.target is None],
                              states=[vertex(c) for c in v.children])
        if v.kind in ('shallow', 'deep'):
            return hsmd.History(id=v.id, deep=v.kind == 'deep')
        if v.kind in ('entry', 'exit'):
            return {'entry': hsmd.EntryPoint, 'exit': hsmd.ExitPoint}[v.kind](v.name, id=v.id)
        if v.kind == 'choice':
            return hsmd.Choice(id=v.id, name=v.name)
        return {'initial': hsmd.Initial, 'final': hsmd.Final,
                'terminate': hsmd.Terminate}[v.kind](id=v.id)

    return hsmd.Machine(
        machine.name, id=machine.id,
        states=[vertex(c) for c in machine.root.children],
        transitions=[hsmd.Transition(r.source.id, r.target.id, r.trigger, id=r.id, **reaction(r))
                     for v in machine.vertices.values() for r in v.reactions
                     if r.target is not None],
        components=[hsmd.Declaration(d.id, d.type, d.priority, d.shared, **d.parameters)
                    for d in machine.components],
        transition_order=machine.transition_order, propagate=machine.propagate,
        comments=machine.comments + [('', body) for body in machine.informal])


class Scenario:

    built = False            # --built: every document goes through declare()

    def __init__(self):
        self.lines = []
        self.now = 0             # milliseconds
        self.stream = io.StringIO()
        self.dispatcher = None
        self.saved = None
        self.names = {}          # the namespace given to the next dispatcher
        self.pipe = None         # the input of the consoles: (read file, write descriptor)

    def write(self, text):
        self.lines.append(text.rstrip())

    def trace(self, record):
        self.write('  ' + ' '.join(str(field) for field in record))

    def outcomes(self, outcomes):
        for outcome in outcomes:
            if outcome is None:
                continue
            name = outcome.event.name or 'completion'
            self.write('= {} {} {}'.format(name, outcome.status,
                                           ' '.join(outcome.transitions)).rstrip())

    def dispatch(self, source, machines=None, namespace=None, period=None, timers=True):
        """A new dispatcher with the clock, the trace and the output of the scenario."""
        self.dispatcher = hsmd.Dispatcher(source, clock=lambda: self.now / MS_IN_SECOND,
                                          trace=self.trace, output=self.stream,
                                          machines=machines, namespace=namespace,
                                          period=period, input=self.input(),
                                          calendar=lambda: CALENDAR_START +
                                          self.now / MS_IN_SECOND, timers=timers)
        self.names = {}

    def input(self):
        """The read end of the input pipe of the scenario."""
        if self.pipe is None:
            read, write = os.pipe()
            self.pipe = (os.fdopen(read, 'rb', buffering=0), write)
        return self.pipe[0]

    def feed(self, name, args):
        """input <text>, input-raw <text>, input-close: the input of the consoles."""
        self.input()
        text = None if name == 'input-close' else args[0] + ('\n' if name == 'input' else '')
        if text is None:
            os.close(self.pipe[1])
            self.pipe = (self.pipe[0], None)
        else:
            os.write(self.pipe[1], text.encode('utf-8'))

    def comments(self, args):
        """comments [<machine>] [formal|informal|all]: the comments kept for the application."""
        kinds = {'formal': True, 'informal': False, 'all': None}
        kind = kinds[args[-1]] if args and args[-1] in kinds else True
        machine = args[0] if args and args[0] not in kinds else None
        for comment, body in self.dispatcher.comments(machine, kind):
            self.write('= {}: {!r}'.format(comment, body))

    def describe(self, ctype):
        """describe <type>: the declared API of a component type."""
        api = hsmd.describe(hsmd_components.find(ctype))
        for key in ('signals', 'methods', 'variables'):
            self.write('= {} {}'.format(key, api[key]))

    def close(self):
        """Close the input pipe at the end of the scenario."""
        if self.pipe is not None:
            self.pipe[0].close()
            if self.pipe[1] is not None:
                os.close(self.pipe[1])
            self.pipe = None

    def load(self, args):
        """load <file> [machines=a,b] [period=ms] [timers=false]: the document."""
        options = dict(arg.split('=', 1) for arg in args[1:])
        machines = options['machines'].split(',') if 'machines' in options else None
        period = int(options['period']) / MS_IN_SECOND if 'period' in options else None
        source = args[0]
        if self.built:
            import hsmd_reader  # pylint: disable=import-outside-toplevel
            source = [declare(m) for m in hsmd_reader.load(source)]
        self.dispatch(source, machines, self.names or None, period,
                      options.get('timers', 'true') != 'false')

    def build(self, args):
        """build <module> [<name>]: the machine written in Python in
        machines/<module>.py, `machine` by default."""
        spec = importlib.util.spec_from_file_location(
            'machines_' + args[0], os.path.join(MACHINES_DIR, args[0] + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.dispatch(getattr(module, args[1] if len(args) > 1 else 'machine'),
                      namespace=vars(module))

    def command(self, words):
        name, args = words[0], words[1:]
        dispatcher = self.dispatcher
        if name == 'load':
            self.load(args)
        elif name == 'build':
            self.build(args)
        elif name in INPUT_COMMANDS:
            self.feed(name, args)
        elif name == 'describe':
            self.describe(args[0])
        elif name == 'let':
            self.names[args[0]] = parse_value(args[1])
        elif name == 'start':
            self.outcomes(dispatcher.start())
        elif name in ('post', 'send'):
            parameters = dict((k, parse_value(v)) for k, v in
                              (arg.split('=', 1) for arg in args[1:]))
            if name == 'post':
                dispatcher.post(args[0], **parameters)
            else:
                self.outcomes([dispatcher.send(args[0], **parameters)])
        elif name == 'run':
            self.outcomes(dispatcher.run())
        elif name == 'clock':
            self.now += int(args[0])
        elif name == 'tick':
            self.outcomes(dispatcher.tick())
        elif name == 'tick-queue':
            self.outcomes(dispatcher.tick(run=False))
        elif name == 'step':
            outcome = dispatcher.step()
            if outcome is None:
                self.write('= empty')
            self.outcomes([outcome])
        elif name == 'machines':
            self.write('= ' + ' '.join(dispatcher.machines()))
        elif name == 'queued':
            self.write('= ' + ' '.join(e.name or 'completion' for e in dispatcher.queued()))
        elif name == 'states':
            self.write('= ' + ' '.join(dispatcher.states(*args)))
        elif name == 'triggers':
            self.write('= ' + ' '.join(dispatcher.triggers(*args)))
        elif name == 'finished':
            self.write('= ' + str(dispatcher.finished(*args)))
        elif name == 'comments':
            self.comments(args)
        elif name == 'stopped':
            self.write('= ' + str(dispatcher.stopped))
        elif name == 'snapshot':
            self.saved = dispatcher.snapshot()
            self.write('= ' + repr(self.saved))
        elif name == 'restore':
            dispatcher.restore(self.saved)
        elif name == 'output':
            for line in self.stream.getvalue().splitlines():
                self.write('| ' + line)
            self.stream.seek(0)
            self.stream.truncate()
        else:
            raise ValueError("unknown command '{}'".format(name))

    def play(self, path):
        with open(path, encoding='utf-8') as script:
            for line in script:
                line = line.strip()
                if not line or line.startswith(COMMENT):
                    continue
                self.write('> ' + line)
                words = shlex.split(line)
                if words[0] != ERROR_COMMAND:
                    self.command(words)
                    continue
                try:
                    self.command(words[1:])
                except hsmd.DispatcherError as e:
                    self.write('! {}: {}'.format(type(e).__name__, e))
                else:
                    self.write('! no error')
        self.close()
        return '\n'.join(self.lines) + '\n'


def validate_graphs():
    """Check the test diagrams against the standard."""
    if not os.path.isdir(os.path.join(VALIDATOR_DIR, 'cgmlval')):
        print('the validator is not found, the diagrams are not checked')
        return True
    graphs = sorted(os.path.join(GRAPHS_DIR, name) for name in os.listdir(GRAPHS_DIR)
                    if name.endswith('.graphml'))
    graphs += sorted(os.path.join(GRAPHS_DIR, 'lib', name)
                     for name in os.listdir(os.path.join(GRAPHS_DIR, 'lib')))
    result = subprocess.run([sys.executable, '-m', 'cgmlval', 'validate', '--strict', '--json']
                            + graphs, cwd=VALIDATOR_DIR, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, universal_newlines=True, check=False)
    try:
        reports = json.loads(result.stdout)
    except ValueError:
        print(result.stdout)
        return False
    bad = 0
    for report in reports:
        expected = EXPECTED_FINDINGS.get(os.path.basename(report['file']), ())
        findings = [f for f in report['findings']
                    if f['severity'] == 'ERROR' and f['req'] not in expected]
        for finding in findings:
            print('{}:{}: {} {}'.format(os.path.basename(report['file']), finding['line'],
                                        finding['req'], finding['message']))
        bad += bool(findings)
    print('{} diagrams checked, {} invalid'.format(len(graphs), bad))
    return bad == 0


def check(name, regen):
    """Play the scenario, compare its output with the good one (or save it);
    return whether it has failed."""
    reason = ''
    try:
        output = Scenario().play(os.path.join(SCRIPTS_DIR, name + '.txt'))
    except Exception as e:  # a failure outside an `error` command
        output = None
        reason = '{}: {}'.format(type(e).__name__, e)
    good_path = os.path.join(GOOD_DIR, name + '.txt')
    if output is None:
        print('FAIL {}: {}'.format(name, reason))
        return True
    if regen:
        with open(good_path, 'w', encoding='utf-8') as good:
            good.write(output)
        print('SAVE {}'.format(name))
        return False
    good = ''
    if os.path.exists(good_path):
        with open(good_path, encoding='utf-8') as good_file:
            good = good_file.read()
    if output == good:
        print('ok   {}'.format(name))
        return False
    print('FAIL {}'.format(name))
    sys.stdout.writelines(difflib.unified_diff(
        good.splitlines(True), output.splitlines(True), 'good', 'output'))
    return True


WITHOUT_BINDING = '''
import importlib.util, sys
spec = importlib.util.spec_from_file_location('robot', sys.argv[1])
robot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(robot)
import hsmd
dispatcher = hsmd.Dispatcher(robot.machine, namespace=vars(robot))
dispatcher.start()
print(' '.join(dispatcher.states()), 'CyberiadaML' in sys.modules)
'''


def check_without_binding():
    """A machine written in Python runs where CyberiadaML cannot be imported."""
    with tempfile.TemporaryDirectory() as blocked:
        with open(os.path.join(blocked, 'CyberiadaML.py'), 'w', encoding='utf-8') as f:
            f.write("raise ImportError('CyberiadaML is blocked')\n")
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([blocked, os.path.dirname(TEST_DIR)]))
        result = subprocess.run([sys.executable, '-c', WITHOUT_BINDING,
                                 os.path.join(MACHINES_DIR, 'robot.py')],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, env=env, check=False)
    if result.returncode != 0 or result.stdout.split() != ['idle', 'False']:
        print('FAIL without CyberiadaML:\n{}{}'.format(result.stdout, result.stderr))
        return True
    print('ok   without CyberiadaML')
    return False


def main():
    args = sys.argv[1:]
    regen = '--regen' in args
    Scenario.built = '--built' in args
    names = [a for a in args if a not in ('--regen', '--built')]
    scripts = sorted(name[:-len('.txt')] for name in os.listdir(SCRIPTS_DIR)
                     if name.endswith('.txt'))
    failed = 0 if validate_graphs() else 1
    failed += check_without_binding()
    os.chdir(GRAPHS_DIR)     # the diagrams are named without a path
    for name in scripts:
        if names and name not in names:
            continue
        failed += check(name, regen)
    if failed:
        print('{} failed'.format(failed))
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
