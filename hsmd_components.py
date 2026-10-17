# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The components: the base class, the registry and the standard types
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

import codecs
import datetime
import inspect
import os
import select
import time

if os.name == 'nt':
    import msvcrt  # pylint: disable=import-error

MS_IN_SECOND = 1000
# the time events of Dispatcher.tick(): the name and the period in seconds,
# None for the period of the dispatcher
TIME_EVENTS = (('TIME_TICK', None), ('TIME_TICK_1S', 1), ('TIME_TICK_1M', 60),
               ('TIME_TICK_1H', 3600))
# the methods of Component the dispatcher calls, not the text
SERVICE_METHODS = ('signal', 'tick', 'snapshot', 'restore')

_registry = {}


def register(ctype, cls):
    """Add a component type; the name is the `type` of a declaration."""
    _registry[ctype] = cls


def find(ctype):
    return _registry.get(ctype)


class Component:
    """The base of the component types. A subclass adds the methods and the
    variables the text of the diagram uses and raises the signals."""

    priority = 0
    shared = False       # one instance per document, signals to every machine
    signals = None       # signal -> the names of its parameters; None: not declared
    variables = ()       # the names the text reads

    def __init__(self, ident, dispatcher, **parameters):
        self.id = ident
        self.dispatcher = dispatcher
        self.parameters = parameters     # of the declaration, as strings
        self.machine = None              # the owning machine of a local component

    def signal(self, name, **parameters):
        """Raise the event <id>.<name>."""
        self.dispatcher.signal(self, name, parameters)

    def tick(self, now):
        """Called from Dispatcher.tick() with the clock value."""

    def snapshot(self):
        return None

    def restore(self, data):
        pass


class Timer(Component):
    """The periodic timer; the time is counted in whole milliseconds."""

    SIGNAL_TIMEOUT = 'TIMEOUT'
    signals = {SIGNAL_TIMEOUT: ()}
    variables = ('interval', 'enabled', 'difference')

    def __init__(self, ident, dispatcher, **parameters):
        Component.__init__(self, ident, dispatcher, **parameters)
        self.interval = 0
        self.enabled = False
        self.deadline = 0
        self.remaining = 0       # the time left while disabled
        self.single = False      # once(): disabled after the next TIMEOUT

    def _now(self):
        return round(self.dispatcher.clock() * MS_IN_SECOND)

    def start(self, interval):
        self.interval = int(interval)
        self.enabled = True
        self.single = False
        self.deadline = self._now() + self.interval

    def once(self, interval):
        """One TIMEOUT after the interval, then the timer is disabled."""
        self.start(interval)
        self.single = True

    def reset(self):
        self.deadline = self._now() + self.interval

    def enable(self):
        self.enabled = True
        self.deadline = self._now() + self.interval

    def disable(self):
        self.remaining = self.difference
        self.enabled = False

    @property
    def difference(self):
        """The time left before the next TIMEOUT."""
        if not self.enabled:
            return self.remaining
        return max(0, self.deadline - self._now())

    def tick(self, now):
        now = round(now * MS_IN_SECOND)
        if self.enabled and self.interval > 0 and now >= self.deadline:
            self.deadline = now + self.interval
            if self.single:
                self.enabled = False
                self.remaining = 0
            self.signal(self.SIGNAL_TIMEOUT)

    def snapshot(self):
        return {'interval': self.interval, 'enabled': self.enabled,
                'remaining': self.difference, 'once': self.single}

    def restore(self, data):
        self.interval = data['interval']
        self.enabled = data['enabled']
        self.remaining = data['remaining']
        self.single = data.get('once', False)
        self.deadline = self._now() + self.remaining


class Log(Component):
    """The messages of the diagram: the trace and the output stream."""

    signals = {}

    def print(self, *values):
        self.dispatcher.message(self, ' '.join(str(v) for v in values))


class Clock(Component):
    """The calendar time in the local time, and the alarm: ALARM at every
    local time with the fields given to alarm(), None for any value."""

    SIGNAL_ALARM = 'ALARM'
    signals = {SIGNAL_ALARM: ()}
    variables = ('now', 'hour', 'minute', 'second', 'weekday')

    def __init__(self, ident, dispatcher, **parameters):
        Component.__init__(self, ident, dispatcher, **parameters)
        self.fields = None       # (hour, minute, second) of the alarm, None: no alarm
        self.next = None         # the calendar time of the next ring

    @property
    def now(self):
        """The local time, a datetime."""
        return datetime.datetime.fromtimestamp(self.dispatcher.calendar())

    @property
    def hour(self):
        """The hour of the local time."""
        return self.now.hour

    @property
    def minute(self):
        """The minute of the local time."""
        return self.now.minute

    @property
    def second(self):
        """The second of the local time."""
        return self.now.second

    @property
    def weekday(self):
        """0 for Monday."""
        return self.now.weekday()

    def alarm(self, hour=None, minute=0, second=0):
        """Ring at every local time with these fields, None for any value."""
        for value, limit in ((hour, 24), (minute, 60), (second, 60)):
            if value is not None and not 0 <= int(value) < limit:
                raise ValueError('the alarm field {} is out of 0..{}'.format(value, limit - 1))
        self.fields = tuple(None if v is None else int(v) for v in (hour, minute, second))
        self.next = self._after(self.dispatcher.calendar())

    def cancel(self):
        """Stop the alarm."""
        self.fields = None
        self.next = None

    def _after(self, calendar):
        """The calendar time of the first local time after the given second
        that has the fields of the alarm."""
        hour, minute, second = self.fields
        moment = datetime.datetime.fromtimestamp(int(calendar)) + datetime.timedelta(seconds=1)
        while True:
            if hour is not None and moment.hour != hour:
                moment = (moment + datetime.timedelta(hours=1)).replace(minute=0, second=0)
            elif minute is not None and moment.minute != minute:
                moment = (moment + datetime.timedelta(minutes=1)).replace(second=0)
            elif second is not None and moment.second != second:
                moment += datetime.timedelta(seconds=1)
            else:
                return time.mktime(moment.timetuple())

    def tick(self, now):
        if self.next is None:
            return
        calendar = self.dispatcher.calendar()
        if calendar >= self.next:
            self.next = self._after(calendar)       # once, the next one from now
            self.signal(self.SIGNAL_ALARM)

    def snapshot(self):
        return {'alarm': None if self.fields is None else list(self.fields)}

    def restore(self, data):
        if data and data.get('alarm') is not None:
            self.fields = tuple(data['alarm'])
            self.next = self._after(self.dispatcher.calendar())
        else:
            self.cancel()


class Console(Component):
    """The lines of the input of the dispatcher: LINE(text) for each, then
    EOF; polled in tick() without blocking."""

    SIGNAL_LINE = 'LINE'
    SIGNAL_EOF = 'EOF'
    READ_SIZE = 4096
    signals = {SIGNAL_LINE: ('text',), SIGNAL_EOF: ()}
    variables = ('last',)
    shared = True                # one input for the machines of the document

    def __init__(self, ident, dispatcher, **parameters):
        Component.__init__(self, ident, dispatcher, **parameters)
        self.last = ''
        self._buffer = ''
        self._decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self._ended = False

    def _read(self):
        """The text the input has now, '' when none; None at its end."""
        stream = self.dispatcher.input
        if not hasattr(stream, 'fileno'):
            text = stream.read()
            return text or None
        if os.name == 'nt':
            # the keyboard of the console; a piped input is not supported
            text = ''
            while stream.isatty() and msvcrt.kbhit():
                text += msvcrt.getwche()
            return text.replace('\r', '\n')
        descriptor = stream.fileno()
        if not select.select([descriptor], [], [], 0)[0]:
            return ''
        data = os.read(descriptor, self.READ_SIZE)
        return self._decoder.decode(data) if data else None

    def _line(self, text):
        self.last = text
        self.signal(self.SIGNAL_LINE, text=text)

    def tick(self, now):
        if self._ended:
            return
        text = self._read()
        if text is None:
            self._ended = True
            rest, self._buffer = self._buffer + self._decoder.decode(b'', final=True), ''
            if rest:
                self._line(rest)
            self.signal(self.SIGNAL_EOF)
            return
        self._buffer += text
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            self._line(line.rstrip('\r'))


register('Timer', Timer)
register('Log', Log)
register('Clock', Clock)
register('Console', Console)


def describe(cls):
    """The API of a component type: its methods with their parameters, its
    variables and its signals with theirs (None: not declared)."""
    methods = {}
    for name, member in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith('_') or name in SERVICE_METHODS:
            continue
        methods[name] = list(inspect.signature(member).parameters)[1:]
    signals = cls.signals
    return {'methods': methods, 'variables': list(cls.variables),
            'signals': None if signals is None else dict(signals)}
