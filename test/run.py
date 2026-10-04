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

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TEST_DIR))

import hsmd  # pylint: disable=wrong-import-position

GRAPHS_DIR = os.path.join(TEST_DIR, 'graphs')
SCRIPTS_DIR = os.path.join(TEST_DIR, 'scripts')
GOOD_DIR = os.path.join(TEST_DIR, 'good')
# the validator of the standard, used when the repository is found
VALIDATOR_DIR = os.path.join(TEST_DIR, '..', '..', 'cyberiadaml-compat-tests')

MS_IN_SECOND = 1000
# the validator still requires a component identifier unique in the whole
# document; the dispatcher reads PNST 1044, 10.3.2 per machine
IGNORED_RULES = ('CGML-10.3-1',)
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
        self.signal('ping', text=text)


hsmd.register('Counter', Counter)
hsmd.register('Bus', Bus)


def parse_value(text):
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


class Scenario:

    def __init__(self):
        self.lines = []
        self.now = 0             # milliseconds
        self.stream = io.StringIO()
        self.dispatcher = None
        self.saved = None

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

    def command(self, words):
        name, args = words[0], words[1:]
        dispatcher = self.dispatcher
        if name == 'load':
            self.dispatcher = hsmd.Dispatcher(args[0], clock=lambda: self.now / MS_IN_SECOND,
                                              trace=self.trace, output=self.stream)
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
        findings = [f for f in report['findings']
                    if f['severity'] == 'ERROR' and f['req'] not in IGNORED_RULES]
        for finding in findings:
            print('{}:{}: {} {}'.format(os.path.basename(report['file']), finding['line'],
                                        finding['req'], finding['message']))
        bad += bool(findings)
    print('{} diagrams checked, {} invalid'.format(len(graphs), bad))
    return bad == 0


def main():
    args = sys.argv[1:]
    regen = '--regen' in args
    names = [a for a in args if a != '--regen']
    scripts = sorted(name[:-len('.txt')] for name in os.listdir(SCRIPTS_DIR)
                     if name.endswith('.txt'))
    failed = 0 if validate_graphs() else 1
    os.chdir(GRAPHS_DIR)     # the diagrams are named without a path
    for name in scripts:
        if names and name not in names:
            continue
        reason = ''
        try:
            output = Scenario().play(os.path.join(SCRIPTS_DIR, name + '.txt'))
        except Exception as e:  # a failure outside an `error` command
            output = None
            reason = '{}: {}'.format(type(e).__name__, e)
        good_path = os.path.join(GOOD_DIR, name + '.txt')
        if output is None:
            print('FAIL {}: {}'.format(name, reason))
            failed += 1
        elif regen:
            with open(good_path, 'w', encoding='utf-8') as good:
                good.write(output)
            print('SAVE {}'.format(name))
        else:
            good = ''
            if os.path.exists(good_path):
                with open(good_path, encoding='utf-8') as good_file:
                    good = good_file.read()
            if output == good:
                print('ok   {}'.format(name))
            else:
                print('FAIL {}'.format(name))
                sys.stdout.writelines(difflib.unified_diff(
                    good.splitlines(True), output.splitlines(True), 'good', 'output'))
                failed += 1
    if failed:
        print('{} failed'.format(failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
