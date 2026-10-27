#!/usr/bin/python3
# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The tests of the stream: the reading, the writing, the errors with their lines
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

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hsmd_stream  # pylint: disable=wrong-import-position

LOG = '''# timers: recorded
0.000   POWER_ON
0.512   button.CLICKED count=2 name='a b'
+0.788  sensor.VALUE value=23.5
SHOW
'''


def summary(stream):
    return [(item.time, item.name, item.parameters, item.line) for item in stream.items]


def rounded(stream):
    """The items at the precision of a written stream."""
    return [(None if item.time is None else round(item.time, 3), item.name, item.parameters)
            for item in stream.items]


def test_read():
    stream = hsmd_stream.read(LOG)
    expected = [(0.0, 'POWER_ON', {}, 2),
                (0.512, 'button.CLICKED', {'count': 2, 'name': 'a b'}, 3),
                (1.3, 'sensor.VALUE', {'value': 23.5}, 4),
                (None, 'SHOW', {}, 5)]
    got = summary(stream)
    got[2] = (round(got[2][0], 3),) + got[2][1:]
    if stream.timers != 'recorded' or stream.start is not None or got != expected:
        return '{} {} {}'.format(stream.timers, stream.start, got)
    return None


def test_round_trip():
    stream = hsmd_stream.read(LOG)
    text = hsmd_stream.write(stream)
    again = hsmd_stream.read(text)
    if rounded(again) != rounded(stream) or again.timers != stream.timers:
        return text
    return None


def test_iso():
    stream = hsmd_stream.read('2026-10-26T12:00:00 POWER_ON\n2026-10-26T12:00:01.250 OPEN\n')
    start = datetime.datetime(2026, 10, 26, 12, 0, 0).timestamp()
    if stream.start != start or [i.time for i in stream.items] != [0.0, 1.25]:
        return '{} {}'.format(stream.start, summary(stream))
    return None


def test_lone_word():
    # a lone word is an untimed item, even a number: a symbol of a tape
    stream = hsmd_stream.read('0\n1\n1\n0\n')
    if [(i.time, i.name) for i in stream.items] != [(None, '0'), (None, '1'), (None, '1'), (None, '0')]:
        return summary(stream)
    return None


ERRORS = [
    ('# timers: sometimes\nGO\n', 1, 'the timers'),
    ('GO\n# timers: model\n', 2, 'the header comes before'),
    ('1.0 GO\n0.5 BACK\n', 2, 'the time goes back'),
    ('1.0 GO\n2026-10-26T12:00:00 BACK\n', 2, 'all seconds or all ISO'),
    ('-1 GO\n', 1, 'negative'),
    ('1.0 GO speed\n', 1, 'is not name=value'),
    ('2026-13-40T00:00:00 GO\n', 1, 'is not an ISO time'),
    ("1.0 GO name='open\n", 1, 'quotation'),
]


def test_errors():
    for text, line, words in ERRORS:
        try:
            hsmd_stream.read(text)
        except hsmd_stream.StreamError as e:
            if e.line != line or words not in e.message:
                return '{!r}: line {} {!r}'.format(text, e.line, e.message)
            continue
        return '{!r}: no error'.format(text)
    return None


def main():
    failed = 0
    for name, case in [('read', test_read), ('round trip', test_round_trip), ('iso', test_iso),
                       ('lone word', test_lone_word), ('errors', test_errors)]:
        problem = case()
        if problem:
            print('FAIL {}: {}'.format(name, problem))
            failed += 1
        else:
            print('ok   {}'.format(name))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
