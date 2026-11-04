# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The state machine model: the vertices, the reactions, the checks
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


class DispatcherError(Exception):
    pass


class DocumentError(DispatcherError):
    pass


# vertex kinds
ROOT = 'machine'
STATE = 'state'
COMPOSITE = 'composite'
INITIAL = 'initial'
FINAL = 'final'
CHOICE = 'choice'
SHALLOW = 'shallow'
DEEP = 'deep'
ENTRY = 'entry'
EXIT = 'exit'
TERMINATE = 'terminate'

STATE_KINDS = (STATE, COMPOSITE)
HISTORY_KINDS = (SHALLOW, DEEP)
POINT_KINDS = (ENTRY, EXIT)
# the pseudostates whose transitions carry no event
SILENT_KINDS = (INITIAL, CHOICE, SHALLOW, DEEP, ENTRY, EXIT)

# reserved names of the action text
EVENT_ANY = 'ANY'
EVENT_UNKNOWN = 'UNKNOWN'
GUARD_ELSE = 'else'

ACTION_FIRST = 'actionFirst'
EXIT_FIRST = 'exitFirst'


class Block:
    """A piece of the behaviour of a state, entry or exit: text or a function."""

    def __init__(self, text, where):
        self.text = text
        self.where = where
        self.code = None


class Reaction:
    """A transition or an internal transition (the target is None)."""

    def __init__(self, ident, source, target, where):
        self.id = ident
        self.source = source
        self.target = target
        self.where = where
        self.trigger = ''
        self.guard = ''
        self.behavior = ''
        self.propagation = None      # None: the default of the document
        self.defer = False
        self.owner = None
        self.guard_code = None
        self.code = None

    def is_else(self):
        return self.guard == GUARD_ELSE


class Vertex:

    def __init__(self, ident, name, kind, parent):
        self.id = ident
        self.name = name
        self.kind = kind
        self.parent = parent
        self.children = []
        self.entry = []
        self.exit = []
        self.reactions = []          # the internal ones first, the document order
        self.initial = None
        self.history = {}            # kind -> the history vertex of this container
        self.submachine = None       # the reference of a submachine state

    def is_state(self):
        return self.kind in STATE_KINDS

    def chain(self):
        """The vertex and its ancestors, the root excluded."""
        result = []
        vertex = self
        while vertex is not None and vertex.kind != ROOT:
            result.append(vertex)
            vertex = vertex.parent
        return result

    def points(self):
        return [v for v in self.children if v.kind in POINT_KINDS]


class ComponentDeclaration:

    def __init__(self, ident, ctype, priority, shared, parameters, machine):
        self.id = ident
        self.type = ctype
        self.priority = priority     # None: the default of the type
        self.shared = shared         # None: the default of the type
        self.parameters = parameters
        self.machine = machine       # the declaring machine

    def same(self, other):
        return (self.type == other.type and self.priority == other.priority
                and self.parameters == other.parameters)


class Machine:

    def __init__(self, ident, name):
        self.id = ident
        self.name = name
        self.root = Vertex(ident, name, ROOT, None)
        self.vertices = {}
        self.transition_order = ACTION_FIRST
        self.propagate = False
        self.components = []
        self.comments = []           # the other formal comments: (name, body)
        self.informal = []           # the informal comments: the bodies
        self.pool = set()

    def where(self):
        return "machine '{}'".format(self.id)

    def component(self, ident):
        for declaration in self.components:
            if declaration.id == ident:
                return declaration
        return None


def add_vertex(vertex, parent, machine):
    machine.vertices[vertex.id] = vertex
    parent.children.append(vertex)
    where = "{}, '{}'".format(machine.where(), parent.id)
    if vertex.kind == INITIAL:
        if parent.initial is not None:
            raise DocumentError("{}: two initial pseudostates".format(where))
        parent.initial = vertex
    elif vertex.kind in HISTORY_KINDS:
        if vertex.kind in parent.history:
            raise DocumentError("{}: two {} history pseudostates".format(where, vertex.kind))
        parent.history[vertex.kind] = vertex
    elif vertex.kind in POINT_KINDS:
        if not vertex.name:
            raise DocumentError("{}, point '{}': no name".format(machine.where(), vertex.id))
        for other in parent.points():
            if other is not vertex and other.name == vertex.name:
                raise DocumentError("{}: two points named '{}'".format(where, vertex.name))


def owner(source, target):
    """The nearest common ancestor; a transition between a composite state
    and its substate does not leave the composite state (PNST 1044, 6.3.2)."""
    if source is target:
        return source.parent
    ancestors = source.chain()
    if target in ancestors:
        return target
    vertex = target
    while vertex.kind != ROOT:
        if vertex in ancestors:
            return vertex
        vertex = vertex.parent
    return vertex


def _is_inside(vertex, container):
    return container.kind == ROOT or container in vertex.chain()[1:]


def _check_vertex(vertex, machine):
    where = "{}, {} '{}'".format(machine.where(), vertex.kind, vertex.id)
    count = len(vertex.reactions)
    if vertex.kind in SILENT_KINDS:
        for reaction in vertex.reactions:
            if reaction.trigger:
                raise DocumentError("{}: an event on a pseudostate transition".format(
                    reaction.where))
    if vertex.kind in (FINAL, TERMINATE) and count:
        raise DocumentError("{}: an outgoing transition".format(where))
    if vertex.kind in (INITIAL, ENTRY) and count != 1:
        raise DocumentError("{}: one transition is required".format(where))
    if vertex.kind in HISTORY_KINDS + (EXIT,) and count > 1:
        raise DocumentError("{}: at most one transition".format(where))
    if vertex.kind == CHOICE and not count:
        raise DocumentError("{}: no transitions".format(where))
    if vertex.kind == ENTRY and not _is_inside(vertex.reactions[0].target, vertex.parent):
        raise DocumentError("{}: the transition leads outside".format(where))
    if vertex.kind == EXIT and count:
        if vertex.parent.kind == ROOT:
            raise DocumentError("{}: a transition from the machine's exit point".format(where))
        if _is_inside(vertex.reactions[0].target, vertex.parent):
            raise DocumentError("{}: the transition stays inside".format(where))


def check(machine):
    if machine.root.initial is None:
        raise DocumentError("{}: no initial pseudostate".format(machine.where()))
    for vertex in machine.vertices.values():
        _check_vertex(vertex, machine)
        for reaction in vertex.reactions:
            if reaction.target is not None:
                reaction.owner = owner(reaction.source, reaction.target)
