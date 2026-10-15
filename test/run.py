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
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TEST_DIR))

import hsmd  # pylint: disable=wrong-import-position

GRAPHS_DIR = os.path.join(TEST_DIR, 'graphs')
SCRIPTS_DIR = os.path.join(TEST_DIR, 'scripts')
GOOD_DIR = os.path.join(TEST_DIR, 'good')
# the validator of the standard, used when the repository is found
VALIDATOR_DIR = os.path.join(TEST_DIR, '..', '..', 'cyberiadaml-compat-tests')

MS_IN_SECOND = 1000
# the diagrams that break the standard on purpose, each loaded with `error
# load` in a scenario: the file and the requirement the validator names
EXPECTED_FINDINGS = {'19-submachine-point.graphml': ('CGML-8.1-4',)}
ERROR_COMMAND = 'error'
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


class Scenario:

    documents = None         # the texts every load decodes (--documents)

    def __init__(self):
        self.lines = []
        self.now = 0             # milliseconds
        self.stream = io.StringIO()
        self.dispatcher = None
        self.saved = None
        self.names = {}          # the namespace given to the next dispatcher
        self.texts = None        # the documents given to the next dispatcher

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

    def load(self, args):
        """load <file> [machines=a,b]: a new dispatcher."""
        options = dict(arg.split('=', 1) for arg in args[1:])
        machines = options['machines'].split(',') if 'machines' in options else None
        self.dispatcher = hsmd.Dispatcher(args[0], clock=lambda: self.now / MS_IN_SECOND,
                                          trace=self.trace, output=self.stream,
                                          machines=machines,
                                          namespace=self.names or None,
                                          documents=self.texts or self.documents)
        self.names = {}
        self.texts = None

    def read_documents(self, path):
        """documents <file>: the texts the next load decodes."""
        current = os.getcwd()
        os.chdir(GRAPHS_DIR)     # the files, also when --documents runs elsewhere
        try:
            self.texts = hsmd.read_documents(path)
        finally:
            os.chdir(current)
        self.write('= ' + ' '.join(self.texts))

    def command(self, words):
        name, args = words[0], words[1:]
        dispatcher = self.dispatcher
        if name == 'load':
            self.load(args)
        elif name == 'documents':
            self.read_documents(args[0])
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
        elif name == 'states':
            self.write('= ' + ' '.join(dispatcher.states(*args)))
        elif name == 'triggers':
            self.write('= ' + ' '.join(dispatcher.triggers(*args)))
        elif name == 'finished':
            self.write('= ' + str(dispatcher.finished(*args)))
        elif name == 'comments':
            kinds = {'formal': True, 'informal': False, 'all': None}
            kind = kinds[args[-1]] if args and args[-1] in kinds else True
            machine = args[0] if args and args[0] not in kinds else None
            for comment, body in dispatcher.comments(machine, kind):
                self.write('= {}: {!r}'.format(comment, body))
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


def read_graphs():
    """The texts of every test diagram, by the path in the diagrams directory."""
    texts = {}
    for folder, _, files in os.walk(GRAPHS_DIR):
        for name in files:
            if name.endswith('.graphml'):
                path = os.path.join(folder, name)
                with open(path, encoding='utf-8') as document:
                    texts[os.path.relpath(path, GRAPHS_DIR)] = document.read()
    return texts


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


def main():
    args = sys.argv[1:]
    regen = '--regen' in args
    names = [a for a in args if a not in ('--regen', '--documents')]
    scripts = sorted(name[:-len('.txt')] for name in os.listdir(SCRIPTS_DIR)
                     if name.endswith('.txt'))
    failed = 0 if validate_graphs() else 1
    with tempfile.TemporaryDirectory() as empty:
        if '--documents' in args:
            # every diagram is decoded from its text, none is on the disk
            Scenario.documents = read_graphs()
            os.chdir(empty)
        else:
            os.chdir(GRAPHS_DIR)     # the diagrams are named without a path
        for name in scripts:
            if not names or name in names:
                failed += check(name, regen)
        os.chdir(TEST_DIR)
    if failed:
        print('{} failed'.format(failed))
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
