# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The behaviour and guard text of the diagram: compilation and execution
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

import traceback

from hsmd_reader import DispatcherError, DocumentError

EVENT_NAME = 'event'


class ActionError(DispatcherError):
    """A failure of the text of the diagram at run time."""

    def __init__(self, where, line, error):
        DispatcherError.__init__(self, '{}, line {}: {}: {}'.format(
            where, line, type(error).__name__, error))
        self.where = where
        self.line = line
        self.error = error


def _compile(text, where, mode):
    try:
        return compile(text, where, mode)
    except SyntaxError as e:
        raise DocumentError('{}, line {}: {}'.format(where, e.lineno, e.msg)) from e


def compile_behavior(text, where):
    return _compile(text, where, 'exec') if text.strip() else None


def compile_guard(text, where):
    return _compile(text.strip(), where + ', guard', 'eval')


def _line(error, where):
    """The line of the text where the error was raised."""
    line = 0
    for frame in traceback.extract_tb(error.__traceback__):
        if frame.filename == where:
            line = frame.lineno
    return line


def _call(function, code, namespace):
    try:
        return function(code, namespace)
    except DispatcherError:
        raise
    except Exception as e:
        raise ActionError(code.co_filename, _line(e, code.co_filename), e) from e


def run(code, namespace):
    if code is not None:
        _call(exec, code, namespace)


def check(code, namespace):
    return bool(_call(eval, code, namespace))
