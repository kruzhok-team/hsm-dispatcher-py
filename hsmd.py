# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The dispatcher: the event queue and the public interface
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

import collections
import heapq
import sys
import time

import hsmd_components
import hsmd_reader
from hsmd_actions import ActionError, EVENT_NAME
from hsmd_components import Component, register
from hsmd_reader import DispatcherError, DocumentError
from hsmd_step import (MachineRun, ExecutionError, FIRED, REJECTED, DROPPED)

__all__ = ['Dispatcher', 'Event', 'Outcome', 'Component', 'register',
           'DispatcherError', 'DocumentError', 'ActionError', 'ExecutionError',
           'StoppedError', 'FIRED', 'REJECTED', 'DROPPED']

SNAPSHOT_VERSION = 1
SIGNAL_SEPARATOR = '.'


class StoppedError(DispatcherError):
    """The dispatcher was stopped by an error and was not restored."""


class Event:
    """An event: the name, the priority and the named parameters, which are
    visible as attributes."""

    def __init__(self, name, priority=0, parameters=None):
        self.name = name
        self.priority = priority
        self.parameters = dict(parameters or {})
        self.run = None          # completion events: the machine
        self.vertex = None       # completion events: the completed state

    def __getattr__(self, name):
        try:
            return self.__dict__['parameters'][name]
        except KeyError:
            raise AttributeError("the event '{}' has no parameter '{}'".format(
                self.__dict__.get('name'), name)) from None


class Outcome:
    """What an event has caused: one result for each machine."""

    def __init__(self, event, results):
        self.event = event
        self.results = results

    @property
    def status(self):
        statuses = [r.status for r in self.results]
        for status in (FIRED, REJECTED):
            if status in statuses:
                return status
        return DROPPED

    @property
    def transitions(self):
        return [t for r in self.results for t in r.transitions]


class Dispatcher:

    def __init__(self, path, clock=None, trace=None, output=None):
        self.clock = clock if clock is not None else time.monotonic
        self.output = output if output is not None else sys.stderr
        self.stopped = False
        self._trace = trace
        self._queue = []
        self._completions = collections.deque()
        self._sequence = 0
        self._runs = []
        self._components = {}
        for machine in hsmd_reader.load(path):
            components = self._create_components(machine)
            self._components[machine.id] = components
            self._runs.append(MachineRun(machine, dict(components), self))

    def _create_components(self, machine):
        components = {}
        for declaration in machine.components:
            where = "{}, component '{}'".format(machine.where(), declaration.id)
            cls = hsmd_components.find(declaration.type)
            if cls is None:
                raise DocumentError("{}: unknown type '{}'".format(where, declaration.type))
            if declaration.id in components:
                raise DocumentError("{}: declared twice".format(where))
            if declaration.id == EVENT_NAME:
                raise DocumentError("{}: the name is reserved".format(where))
            try:
                component = cls(declaration.id, self, **declaration.parameters)
            except TypeError as e:
                raise DocumentError("{}: {}".format(where, e)) from e
            if declaration.priority is not None:
                component.priority = declaration.priority
            components[declaration.id] = component
        return components

    # ------------------------------------------------------------------------
    # the interface of the application

    def start(self):
        """Enter the initial configuration of every machine."""
        self._check()
        self._guarded(lambda: [run.start() for run in self._runs])
        return self.run()

    def post(self, name, priority=0, **parameters):
        """Put an event into the queue."""
        self._check()
        return self._post(Event(name, priority, parameters))

    def run(self):
        """Process the queue until it is empty, return the outcomes."""
        self._check()
        outcomes = []
        while True:
            event = self._take()
            if event is None:
                return outcomes
            outcomes.append(self._guarded(lambda e=event: self._process(e)))

    def send(self, name, **parameters):
        """Post one event, process the queue, return the outcome of the event."""
        event = self.post(name, **parameters)
        for outcome in self.run():
            if outcome.event is event:
                return outcome
        return None

    def tick(self):
        """Let the components check the clock, then process the queue."""
        self._check()
        now = self.clock()
        for components in self._components.values():
            for component in components.values():
                self._guarded(lambda c=component: c.tick(now))
        return self.run()

    def states(self, machine=None):
        return self._run(machine).states()

    def finished(self, machine=None):
        return self._run(machine).finished

    def triggers(self, machine=None):
        return self._run(machine).triggers()

    def snapshot(self):
        return {
            'version': SNAPSHOT_VERSION,
            'machines': {run.machine.id: run.snapshot() for run in self._runs},
            'queue': [self._event_data(item[2]) for item in sorted(self._queue)],
            'completions': [{'machine': e.run.machine.id, 'vertex': e.vertex.id}
                            for e in self._completions],
            'components': {mid: {cid: c.snapshot() for cid, c in components.items()}
                           for mid, components in self._components.items()},
        }

    def restore(self, data):
        if data.get('version') != SNAPSHOT_VERSION:
            raise DispatcherError('unknown snapshot version')
        self._queue = []
        self._completions.clear()
        self._sequence = 0
        for run in self._runs:
            run.restore(data['machines'][run.machine.id])
        for item in data['queue']:
            self._post(Event(item['name'], item['priority'], item['parameters']))
        for item in data['completions']:
            run = self._run(item['machine'])
            self.complete(run, run.machine.vertices[item['vertex']])
        for mid, components in self._components.items():
            for cid, component in components.items():
                component.restore(data['components'][mid][cid])
        self.stopped = False

    # ------------------------------------------------------------------------
    # the interface of the components and of the machines

    def signal(self, component, name, parameters):
        self._post(Event(component.id + SIGNAL_SEPARATOR + name,
                         component.priority, parameters))

    def message(self, component, text):
        self.trace('print', component.id, text)
        self.output.write(text + '\n')

    def complete(self, run, vertex):
        event = Event('')
        event.run = run
        event.vertex = vertex
        self._completions.append(event)
        self.trace('completion', run.machine.id, vertex.id)

    def trace(self, *record):
        if self._trace is not None:
            self._trace(record)

    # ------------------------------------------------------------------------

    def _check(self):
        if self.stopped:
            raise StoppedError('the dispatcher is stopped')

    def _guarded(self, function):
        try:
            return function()
        except Exception as e:
            self.stopped = True
            self.trace('error', str(e))
            raise

    def _run(self, machine):
        if machine is None:
            return self._runs[0]
        for run in self._runs:
            if machine in (run.machine.id, run.machine.name):
                return run
        raise DispatcherError("no machine '{}'".format(machine))

    def _post(self, event):
        # the highest priority first, then the order of arrival
        self._sequence += 1
        heapq.heappush(self._queue, (-event.priority, self._sequence, event))
        self.trace('post', event.name, event.priority)
        return event

    def _take(self):
        if self._completions:
            return self._completions.popleft()
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def _process(self, event):
        if event.vertex is not None:
            runs = [event.run]
        else:
            runs = self._runs
            self.trace('event', event.name)
        results = []
        for run in runs:
            result = run.step(event)
            self.trace('outcome', result.machine, result.status, *result.transitions)
            results.append(result)
        return Outcome(event, results)

    @staticmethod
    def _event_data(event):
        return {'name': event.name, 'priority': event.priority,
                'parameters': event.parameters}
