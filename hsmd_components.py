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

MS_IN_SECOND = 1000

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

    SIGNAL_TIMEOUT = 'timeout'

    def __init__(self, ident, dispatcher, **parameters):
        Component.__init__(self, ident, dispatcher, **parameters)
        self.interval = 0
        self.enabled = False
        self.deadline = 0
        self.remaining = 0       # the time left while disabled

    def _now(self):
        return round(self.dispatcher.clock() * MS_IN_SECOND)

    def start(self, interval):
        self.interval = int(interval)
        self.enabled = True
        self.deadline = self._now() + self.interval

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
        """The time left before the next timeout."""
        if not self.enabled:
            return self.remaining
        return max(0, self.deadline - self._now())

    def tick(self, now):
        now = round(now * MS_IN_SECOND)
        if self.enabled and self.interval > 0 and now >= self.deadline:
            self.deadline = now + self.interval
            self.signal(self.SIGNAL_TIMEOUT)

    def snapshot(self):
        return {'interval': self.interval, 'enabled': self.enabled,
                'remaining': self.difference}

    def restore(self, data):
        self.interval = data['interval']
        self.enabled = data['enabled']
        self.remaining = data['remaining']
        self.deadline = self._now() + self.remaining


class Log(Component):
    """The messages of the diagram: the trace and the output stream."""

    def print(self, *values):
        self.dispatcher.message(self, ' '.join(str(v) for v in values))


register('Timer', Timer)
register('Log', Log)
