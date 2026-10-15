# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The declarations of a state machine written in Python
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

"""The declarations of a machine written in Python and the model built from them."""

# pylint: disable=redefined-builtin,too-few-public-methods,too-many-arguments
# pylint: disable=too-many-instance-attributes

from hsmd_model import (DocumentError, STATE, COMPOSITE, INITIAL, FINAL, CHOICE, SHALLOW, DEEP,
                        ENTRY, EXIT, TERMINATE, EVENT_ANY, EVENT_UNKNOWN, GUARD_ELSE,
                        ACTION_FIRST, EXIT_FIRST, Block, Reaction, Vertex, ComponentDeclaration,
                        add_vertex, check)
import hsmd_model

ELSE = GUARD_ELSE
# the identifiers the declarations leave out: <parent>.<kind>, <source>-<target>#<n>
KIND_SEPARATOR = '.'
ENDS_SEPARATOR = '-'
NUMBER_SEPARATOR = '#'


class _Vertex:
    """A vertex of the machine: its kind, identifier and name."""

    kind = None

    def __init__(self, id=None, name=''):
        self.id = id
        self.name = name

    def default_id(self, parent):
        """The identifier of a vertex declared without one."""
        return '{}{}{}'.format(parent.id, KIND_SEPARATOR, self.kind)


class State(_Vertex):
    """A state; composite when it has states."""

    kind = STATE

    def __init__(self, name, id=None, entry=None, exit=None, internal=(), states=()):
        _Vertex.__init__(self, id, name)
        self.entry = _pieces(entry)
        self.exit = _pieces(exit)
        self.internal = list(internal)
        self.states = list(states)

    def default_id(self, parent):
        return self.name


class Initial(_Vertex):
    """The initial pseudostate of its container."""

    kind = INITIAL


class Final(_Vertex):
    """A final state."""

    kind = FINAL


class Terminate(_Vertex):
    """The terminate pseudostate."""

    kind = TERMINATE


class Choice(_Vertex):
    """A choice pseudostate."""

    kind = CHOICE

    def __init__(self, id=None, name=''):
        _Vertex.__init__(self, id, name)


class History(_Vertex):
    """The shallow history, or the deep one."""

    def __init__(self, id=None, deep=False):
        _Vertex.__init__(self, id)
        self.kind = DEEP if deep else SHALLOW


class _Point(_Vertex):
    """An entry or exit point, named."""

    def __init__(self, name, id=None):
        _Vertex.__init__(self, id, name)

    def default_id(self, parent):
        return '{}{}{}'.format(parent.id, KIND_SEPARATOR, self.name)


class EntryPoint(_Point):
    """An entry point of a state or of the machine."""

    kind = ENTRY


class ExitPoint(_Point):
    """An exit point of a state or of the machine."""

    kind = EXIT


class On:
    """An internal transition of its state."""

    def __init__(self, event, guard=None, action=None, propagate=None, defer=False):
        self.event = event
        self.guard = guard
        self.action = action
        self.propagate = propagate
        self.defer = defer


class Transition(On):
    """A transition between the vertices named by their identifiers."""

    def __init__(self, source, target, event='', guard=None, action=None, propagate=None,
                 defer=False, id=None):
        On.__init__(self, event, guard, action, propagate, defer)
        self.source = source
        self.target = target
        self.id = id


class Declaration:
    """A component of the machine, as CGML_COMPONENT <id>."""

    def __init__(self, id, type, priority=None, shared=None, **parameters):
        self.id = id
        self.type = type
        self.priority = priority
        self.shared = shared
        self.parameters = parameters


class Machine:
    """A state machine: the vertices, the transitions, the components."""

    def __init__(self, name, id=None, states=(), transitions=(), components=(),
                 transition_order=ACTION_FIRST, propagate=False, comments=()):
        self.name = name
        self.id = id if id is not None else name
        self.states = list(states)
        self.transitions = list(transitions)
        self.components = list(components)
        self.comments = list(comments)
        self.transition_order = transition_order
        self.propagate = propagate


def _pieces(code):
    """The pieces of code of an entry or an exit: none, one or a list."""
    if code is None:
        return []
    return list(code) if isinstance(code, (list, tuple)) else [code]


def _code(code, where):
    if code is None or isinstance(code, str) or callable(code):
        return code
    raise DocumentError('{}: the code is neither text nor a function'.format(where))


def _set(reaction, declaration, machine):
    reaction.trigger = declaration.event.strip()
    guard = _code(declaration.guard, reaction.where + ', guard')
    reaction.guard = guard.strip() if isinstance(guard, str) else guard or ''
    reaction.behavior = _code(declaration.action, reaction.where) or ''
    reaction.propagation = declaration.propagate
    reaction.defer = bool(declaration.defer)
    if reaction.trigger and reaction.trigger not in (EVENT_ANY, EVENT_UNKNOWN):
        machine.pool.add(reaction.trigger)


def _vertex(declaration, parent, machine):
    if not isinstance(declaration, _Vertex):
        raise DocumentError("{}, '{}': not a vertex: {!r}".format(
            machine.where(), parent.id, declaration))
    ident = declaration.id if declaration.id is not None else declaration.default_id(parent)
    if ident in machine.vertices:
        raise DocumentError("{}: two vertices '{}'".format(machine.where(), ident))
    kind = declaration.kind
    if kind == STATE and declaration.states:
        kind = COMPOSITE
    vertex = Vertex(ident, declaration.name, kind, parent)
    add_vertex(vertex, parent, machine)
    if not isinstance(declaration, State):
        return
    where = "{}, state '{}'".format(machine.where(), ident)
    vertex.entry = [Block(_code(c, where + ', entry'), where + ', entry')
                    for c in declaration.entry]
    vertex.exit = [Block(_code(c, where + ', exit'), where + ', exit')
                   for c in declaration.exit]
    for number, internal in enumerate(declaration.internal, 1):
        if not isinstance(internal, On) or isinstance(internal, Transition):
            raise DocumentError('{}: not an internal transition: {!r}'.format(where, internal))
        reaction = Reaction('{}{}{}'.format(ident, NUMBER_SEPARATOR, number), vertex, None,
                            '{}, internal transition {}'.format(where, number))
        _set(reaction, internal, machine)
        if not reaction.trigger:
            raise DocumentError('{}: no event'.format(reaction.where))
        vertex.reactions.append(reaction)
    for child in declaration.states:
        _vertex(child, vertex, machine)


def _transition(declaration, machine, used):
    if not isinstance(declaration, Transition):
        raise DocumentError('{}: not a transition: {!r}'.format(machine.where(), declaration))
    ident = declaration.id
    if ident is None:
        ident = base = '{}{}{}'.format(declaration.source, ENDS_SEPARATOR, declaration.target)
        number = 1
        while ident in used:
            number += 1
            ident = '{}{}{}'.format(base, NUMBER_SEPARATOR, number)
    where = "{}, transition '{}'".format(machine.where(), ident)
    if ident in used:
        raise DocumentError('{}: declared twice'.format(where))
    used.add(ident)
    source = machine.vertices.get(declaration.source)
    target = machine.vertices.get(declaration.target)
    if source is None or target is None:
        raise DocumentError('{}: unknown source or target'.format(where))
    reaction = Reaction(ident, source, target, where)
    _set(reaction, declaration, machine)
    source.reactions.append(reaction)


def _component(declaration, machine):
    if not isinstance(declaration, Declaration):
        raise DocumentError('{}: not a component declaration: {!r}'.format(
            machine.where(), declaration))
    where = "{}, component '{}'".format(machine.where(), declaration.id)
    if machine.component(declaration.id) is not None:
        raise DocumentError('{}: declared twice'.format(where))
    machine.components.append(ComponentDeclaration(
        declaration.id, declaration.type, declaration.priority, declaration.shared,
        dict(declaration.parameters), machine.id))


def build(declaration):
    """The model of a machine written in Python, checked by the rules of a document."""
    if not isinstance(declaration, Machine):
        raise DocumentError('not a machine: {!r}'.format(declaration))
    machine = hsmd_model.Machine(declaration.id, declaration.name)
    if declaration.transition_order not in (ACTION_FIRST, EXIT_FIRST):
        raise DocumentError("{}: bad transition order '{}'".format(
            machine.where(), declaration.transition_order))
    machine.transition_order = declaration.transition_order
    machine.propagate = bool(declaration.propagate)
    for child in declaration.states:
        _vertex(child, machine.root, machine)
    used = set()
    for transition in declaration.transitions:
        _transition(transition, machine, used)
    for component in declaration.components:
        _component(component, machine)
    for name, body in declaration.comments:
        if name:
            machine.comments.append((name, body))
        else:
            machine.informal.append(body)
    check(machine)
    return machine
