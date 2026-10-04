# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The execution of one state machine: the step for one event
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

import hsmd_actions
from hsmd_reader import (DispatcherError, ROOT, STATE, COMPOSITE, INITIAL, FINAL, CHOICE,
                         SHALLOW, ENTRY, EXIT, TERMINATE, HISTORY_KINDS,
                         ACTION_FIRST, EVENT_ANY, EVENT_UNKNOWN)

# outcome statuses
FIRED = 'fired'
REJECTED = 'rejected'
DROPPED = 'dropped'
DEFERRED = 'deferred'


class ExecutionError(DispatcherError):
    """A diagram that cannot be executed further."""


class MachineOutcome:

    def __init__(self, machine, status, transitions=()):
        self.machine = machine
        self.status = status
        self.transitions = list(transitions)


class MachineRun:
    """The execution state of one machine. The host provides trace(*record)
    and complete(run, vertex)."""

    def __init__(self, machine, namespace, host):
        self.machine = machine
        self.namespace = namespace
        self.host = host
        self.active = None
        self.finished = False
        self.history = {}        # container id -> (last child id, last leaf id)
        self._fired = []
        for vertex in machine.vertices.values():
            for block in vertex.entry + vertex.exit:
                block.code = hsmd_actions.compile_behavior(block.text, block.where)
            for reaction in vertex.reactions:
                reaction.code = hsmd_actions.compile_behavior(reaction.behavior,
                                                              reaction.where)
                if reaction.guard and not reaction.is_else():
                    reaction.guard_code = hsmd_actions.compile_guard(reaction.guard,
                                                                     reaction.where)

    # ------------------------------------------------------------------------
    # queries

    def states(self):
        if self.active is None:
            return []
        return [v.id for v in reversed(self.active.chain()) if v.is_state()]

    def triggers(self):
        result = []
        state = self._state()
        while state is not None and state.kind != ROOT:
            for reaction in state.reactions:
                if reaction.trigger and reaction.trigger not in result:
                    result.append(reaction.trigger)
            state = state.parent
        return result

    def snapshot(self):
        return {'active': self._ident(self.active), 'finished': self.finished,
                'history': {k: list(v) for k, v in self.history.items()}}

    def restore(self, data):
        self.active = self._vertex(data['active'])
        self.finished = data['finished']
        self.history = {k: tuple(v) for k, v in data['history'].items()}

    @staticmethod
    def _ident(vertex):
        return vertex.id if vertex is not None else None

    def _vertex(self, ident):
        if ident is None:
            return None
        if ident == self.machine.root.id:
            return self.machine.root
        return self.machine.vertices[ident]

    # ------------------------------------------------------------------------
    # execution

    def start(self):
        self.namespace[hsmd_actions.EVENT_NAME] = None
        self.active = self.machine.root
        self._enter_default(self.machine.root)

    def step(self, event):
        self.namespace[hsmd_actions.EVENT_NAME] = event
        if self.active is None or self.finished:
            return MachineOutcome(self.machine.id, DROPPED)
        if event.vertex is not None:
            return self._complete(event.vertex)
        self._fired = []
        matched = False
        state = self._state()
        while state is not None and state.kind != ROOT:
            reaction, found = self._select(state, event)
            matched = matched or found
            parent = state.parent
            if reaction is not None and reaction.defer:
                # the inner state keeps the event for a later configuration
                self.host.trace('defer', self.machine.id, reaction.id)
                return MachineOutcome(self.machine.id, DEFERRED)
            if reaction is not None:
                self._fire(reaction)
                propagate = reaction.propagation
                if propagate is None:
                    propagate = self.machine.propagate
                # a passed event goes on while the enclosing state is active
                if not propagate or self.finished or not self._is_active(parent):
                    break
            state = parent
        if self._fired:
            return MachineOutcome(self.machine.id, FIRED, self._fired)
        return MachineOutcome(self.machine.id, REJECTED if matched else DROPPED)

    def _complete(self, vertex):
        if vertex.kind == COMPOSITE:
            active = self.active.kind == FINAL and self.active.parent is vertex
        else:
            active = self.active is vertex
        if not active:
            return MachineOutcome(self.machine.id, DROPPED)
        reaction = self._pick([r for r in vertex.reactions if not r.trigger])
        if reaction is None:
            return MachineOutcome(self.machine.id, REJECTED)
        self._fired = []
        self._fire(reaction)
        return MachineOutcome(self.machine.id, FIRED, self._fired)

    def _state(self):
        """The innermost active state."""
        vertex = self.active
        while vertex is not None and vertex.kind != ROOT and not vertex.is_state():
            vertex = vertex.parent
        return vertex

    def _is_active(self, vertex):
        return vertex.kind == ROOT or vertex in self.active.chain()

    def _select(self, state, event):
        named = [r for r in state.reactions if r.trigger == event.name]
        special = EVENT_ANY if event.name in self.machine.pool else EVENT_UNKNOWN
        other = [r for r in state.reactions if r.trigger == special]
        for group in (named, other):
            reaction = self._pick(group)
            if reaction is not None:
                return reaction, True
        return None, bool(named or other)

    def _pick(self, candidates):
        """The first enabled candidate in the document order, [else] last."""
        chosen = None
        also = []
        for reaction in candidates:
            if reaction.is_else():
                continue
            if self._guard(reaction):
                if chosen is None:
                    chosen = reaction
                else:
                    also.append(reaction.id)
        if also:
            self.host.trace('ambiguous', self.machine.id, chosen.id, *also)
        if chosen is None:
            for reaction in candidates:
                if reaction.is_else():
                    return reaction
        return chosen

    def _guard(self, reaction):
        if reaction.guard_code is None:
            return True
        value = hsmd_actions.check(reaction.guard_code, self.namespace)
        self.host.trace('guard', self.machine.id, reaction.id, reaction.guard, value)
        return value

    def _fire(self, reaction):
        self.host.trace('fire', self.machine.id, reaction.id)
        if reaction.source.kind != INITIAL:
            self._fired.append(reaction.id)
        if reaction.target is None:
            hsmd_actions.run(reaction.code, self.namespace)
            return
        if reaction.target.kind == TERMINATE:
            # no state is left, no exit action runs (PNST 984, 7.10.6)
            hsmd_actions.run(reaction.code, self.namespace)
            self.active = reaction.target
            self.finished = True
            self.host.trace('terminated', self.machine.id)
            return
        if self.machine.transition_order == ACTION_FIRST:
            hsmd_actions.run(reaction.code, self.namespace)
            self._exit_to(reaction.owner)
        else:
            self._exit_to(reaction.owner)
            hsmd_actions.run(reaction.code, self.namespace)
        self._arrive(reaction.target, reaction.owner)

    def _exit_to(self, owner):
        vertex = self.active
        leaf = vertex
        while vertex is not owner and vertex.kind != ROOT:
            if vertex.is_state():
                self.host.trace('exit', self.machine.id, vertex.id)
                for block in vertex.exit:
                    hsmd_actions.run(block.code, self.namespace)
            # the history of the container: its last child and the last leaf
            self.history[vertex.parent.id] = (vertex.id, leaf.id)
            vertex = vertex.parent
        self.active = vertex

    def _arrive(self, target, owner):
        path = []
        for vertex in target.chain():
            if vertex is owner:
                break
            if vertex.is_state():
                path.append(vertex)
        for vertex in reversed(path):
            self.host.trace('enter', self.machine.id, vertex.id)
            self.active = vertex
            for block in vertex.entry:
                hsmd_actions.run(block.code, self.namespace)
        if target.kind == STATE:
            if any(not r.trigger for r in target.reactions):
                self.host.complete(self, target)
        elif target.kind == COMPOSITE:
            self._enter_default(target)
        elif target.kind == FINAL:
            self._finish(target)
        elif target.kind == CHOICE:
            reaction = self._pick(target.reactions)
            if reaction is None:
                raise ExecutionError("{}, choice '{}': no true branch".format(
                    self.machine.where(), target.id))
            self._fire(reaction)
        elif target.kind in HISTORY_KINDS:
            self._enter_history(target)
        elif target.kind == ENTRY:
            # the container is entered, then the segment from the point
            self._fire(target.reactions[0])
        elif target.kind == EXIT:
            self._leave_through(target)
        else:
            raise ExecutionError("{}: a transition to the pseudostate '{}'".format(
                self.machine.where(), target.id))

    def _enter_history(self, history):
        container = history.parent
        record = self.history.get(container.id)
        if record is not None and self.machine.vertices[record[0]].kind != FINAL:
            last = record[0] if history.kind == SHALLOW else record[1]
            self.host.trace('history', self.machine.id, history.id, last)
            self._arrive(self.machine.vertices[last], container)
        elif history.reactions:
            self._fire(history.reactions[0])
        else:
            self._enter_default(container)

    def _leave_through(self, point):
        container = point.parent
        if container.kind == ROOT:
            self.active = point
            self.finished = True
            self.host.trace('finished', self.machine.id)
            return
        self._exit_to(container.parent)
        if point.reactions:
            self._fire(point.reactions[0])
        elif container.parent.kind == ROOT:
            self.finished = True
            self.host.trace('finished', self.machine.id)

    def _enter_default(self, container):
        if container.initial is None:
            raise ExecutionError("{}, '{}': no initial pseudostate".format(
                self.machine.where(), container.id))
        self._fire(container.initial.reactions[0])

    def _finish(self, final):
        self.active = final
        parent = final.parent
        if parent.kind == ROOT:
            self.finished = True
            self.host.trace('finished', self.machine.id)
        elif any(not r.trigger for r in parent.reactions):
            self.host.complete(self, parent)
