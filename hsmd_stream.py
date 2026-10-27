# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The stream: the prepared input of a session, a scenario or a recorded log
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

"""The stream (docs/API.md, The stream): an item per line, a time in seconds,
+delta or ISO 8601 before the event, the header that names who brings the
timeouts."""

import ast
import datetime
import re
import shlex

COMMENT = '#'
HEADER = 'timers:'
TIMERS_MODEL = 'model'
TIMERS_RECORDED = 'recorded'
DELTA = '+'
TIME_FORMAT = '{:.3f}'
# a word that starts an ISO 8601 date
ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}')


class StreamError(Exception):
    """A line of the stream that cannot be read."""

    def __init__(self, message, line):
        Exception.__init__(self, 'line {}: {}'.format(line, message))
        self.message = message
        self.line = line


class Item:
    """An event of the stream: the seconds from the start (None: untimed, right
    after the previous item), the name, the parameters, the line."""

    def __init__(self, time, name, parameters=None, line=0):
        self.time = time
        self.name = name
        self.parameters = dict(parameters or {})
        self.line = line

    def __repr__(self):
        return 'Item({!r}, {!r}, {!r})'.format(self.time, self.name, self.parameters)


class Stream:
    """The items; who brings the timeouts (model or recorded); the epoch of
    the first ISO time, None for a stream in seconds."""

    def __init__(self, items=None, timers=TIMERS_MODEL, start=None):
        self.items = list(items or [])
        self.timers = timers
        self.start = start


def parse_value(text):
    """A Python literal, else the text, as in the scenarios of the tests."""
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _seconds(word):
    try:
        return float(word)
    except ValueError:
        return None


def read(text):
    """The stream of the text; a bad line is a StreamError."""
    items = []
    timers = TIMERS_MODEL
    start = None
    kind = None              # 'seconds' or 'iso': the absolute times of one stream
    previous = None          # the time of the last timed item
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(COMMENT):
            body = line[len(COMMENT):].strip()
            if body.startswith(HEADER):
                value = body[len(HEADER):].strip()
                if value not in (TIMERS_MODEL, TIMERS_RECORDED):
                    raise StreamError("the timers are '{}' or '{}', not '{}'".format(
                        TIMERS_MODEL, TIMERS_RECORDED, value), number)
                if items:
                    raise StreamError('the header comes before the items', number)
                timers = value
            continue
        try:
            words = shlex.split(line)
        except ValueError as e:
            raise StreamError(str(e), number) from e
        when = None
        # a time is a time only before an event: a lone word is an untimed item
        if len(words) > 1:
            first = words[0]
            if first.startswith(DELTA) and _seconds(first[len(DELTA):]) is not None:
                when = (previous or 0.0) + _seconds(first[len(DELTA):])
                words = words[1:]
            elif _seconds(first) is not None:
                kind = kind or 'seconds'
                if kind != 'seconds':
                    raise StreamError('the times are all seconds or all ISO', number)
                when = _seconds(first)
                words = words[1:]
            elif ISO_DATE.match(first):
                try:
                    epoch = datetime.datetime.fromisoformat(first).timestamp()
                except ValueError as e:
                    raise StreamError("'{}' is not an ISO time".format(first), number) from e
                kind = kind or 'iso'
                if kind != 'iso':
                    raise StreamError('the times are all seconds or all ISO', number)
                start = epoch if start is None else start
                when = epoch - start
                words = words[1:]
        if when is not None:
            if when < 0:
                raise StreamError('the time is negative', number)
            if previous is not None and when < previous:
                raise StreamError('the time goes back', number)
            previous = when
        name, parameters = words[0], {}
        for word in words[1:]:
            key, separator, value = word.partition('=')
            if not separator or not key:
                raise StreamError("'{}' is not name=value".format(word), number)
            parameters[key] = parse_value(value)
        items.append(Item(when, name, parameters, number))
    return Stream(items, timers, start)


def _value_text(value):
    """A parameter value the reading gives back."""
    text = value if isinstance(value, str) else repr(value)
    return shlex.quote(text)


def write(stream):
    """The text of the stream: the header, then an item per line."""
    lines = ['{} {} {}'.format(COMMENT, HEADER, stream.timers)]
    for item in stream.items:
        words = [] if item.time is None else [TIME_FORMAT.format(item.time)]
        words.append(item.name)
        words += ['{}={}'.format(key, _value_text(value)) for key, value in item.parameters.items()]
        lines.append(' '.join(words))
    return '\n'.join(lines) + '\n'
