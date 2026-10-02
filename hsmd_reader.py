# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The CyberiadaML document reader and the state machine model
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

import CyberiadaML


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

STATE_KINDS = (STATE, COMPOSITE)

# reserved names of the action text
EVENT_ANY = 'ANY'
EVENT_UNKNOWN = 'UNKNOWN'
GUARD_ELSE = 'else'

ACTION_FIRST = 'actionFirst'
EXIT_FIRST = 'exitFirst'

COMPONENT_PREFIX = 'CGML_COMPONENT '
PARAMETER_SEPARATOR = '/'
PARAMETER_TYPE = 'type'
PARAMETER_PRIORITY = 'priority'

_KINDS = {
    CyberiadaML.elementSimpleState: STATE,
    CyberiadaML.elementCompositeState: COMPOSITE,
    CyberiadaML.elementInitial: INITIAL,
    CyberiadaML.elementFinal: FINAL,
    CyberiadaML.elementChoice: CHOICE,
}

_IGNORED = (CyberiadaML.elementComment, CyberiadaML.elementFormalComment,
            CyberiadaML.elementTransition)

# the elements of the later stages
_UNSUPPORTED = {
    CyberiadaML.elementTerminate: 'terminate pseudostate',
    CyberiadaML.elementShallowHistory: 'shallow history pseudostate',
    CyberiadaML.elementDeepHistory: 'deep history pseudostate',
    CyberiadaML.elementSubmachineState: 'submachine state',
    CyberiadaML.elementEntryPoint: 'entry point',
    CyberiadaML.elementExitPoint: 'exit point',
}


class Block:
    """A piece of the behaviour text of a state: entry or exit."""

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


class ComponentDeclaration:

    def __init__(self, ident, ctype, priority, parameters):
        self.id = ident
        self.type = ctype
        self.priority = priority     # None: the default of the type
        self.parameters = parameters


class Machine:

    def __init__(self, ident, name):
        self.id = ident
        self.name = name
        self.root = Vertex(ident, name, ROOT, None)
        self.vertices = {}
        self.transition_order = ACTION_FIRST
        self.propagate = False
        self.components = []
        self.pool = set()

    def where(self):
        return "machine '{}'".format(self.id)


def parse_parameters(body):
    """The name/value blocks of a formal comment (PNST 1044, 6.9, 10.3.1)."""
    parameters = {}
    name = None
    for line in body.split('\n'):
        if not line.strip():
            name = None
            continue
        if name is None:
            if PARAMETER_SEPARATOR not in line:
                raise DocumentError("bad parameter line '{}'".format(line))
            name, value = line.split(PARAMETER_SEPARATOR, 1)
            name = name.strip()
            parameters[name] = value.strip()
        else:
            parameters[name] += '\n' + line
    return parameters


def _read_component(comment, machine):
    ident = comment.get_name()[len(COMPONENT_PREFIX):].strip()
    try:
        parameters = parse_parameters(comment.get_body())
    except DocumentError as e:
        raise DocumentError("{}, component '{}': {}".format(machine.where(), ident, e)) from e
    if PARAMETER_TYPE not in parameters:
        raise DocumentError("{}, component '{}': no type".format(machine.where(), ident))
    ctype = parameters.pop(PARAMETER_TYPE)
    priority = None
    if PARAMETER_PRIORITY in parameters:
        value = parameters.pop(PARAMETER_PRIORITY)
        try:
            priority = int(value)
        except ValueError:
            raise DocumentError("{}, component '{}': bad priority '{}'".format(
                machine.where(), ident, value)) from None
    machine.components.append(ComponentDeclaration(ident, ctype, priority, parameters))


def _set_action(reaction, action, machine):
    propagation = action.get_propagation()
    if propagation == CyberiadaML.eventPropagationDefer:
        raise DocumentError("{}: deferred events are not supported".format(reaction.where))
    if propagation == CyberiadaML.eventPropagationPropagate:
        reaction.propagation = True
    elif propagation == CyberiadaML.eventPropagationBlock:
        reaction.propagation = False
    reaction.trigger = action.get_trigger().strip()
    reaction.guard = action.get_guard().strip()
    reaction.behavior = action.get_behavior()
    if reaction.trigger and reaction.trigger not in (EVENT_ANY, EVENT_UNKNOWN):
        machine.pool.add(reaction.trigger)


def _read_state_actions(element, vertex, machine):
    where = "{}, state '{}'".format(machine.where(), vertex.id)
    internal = 0
    for action in element.get_actions():
        atype = action.get_type()
        if atype == CyberiadaML.actionEntry:
            vertex.entry.append(Block(action.get_behavior(), where + ', entry'))
        elif atype == CyberiadaML.actionExit:
            vertex.exit.append(Block(action.get_behavior(), where + ', exit'))
        else:
            internal += 1
            ident = '{}#{}'.format(vertex.id, internal)
            reaction = Reaction(ident, vertex, None,
                                "{}, internal transition {}".format(where, internal))
            _set_action(reaction, action, machine)
            if not reaction.trigger:
                raise DocumentError("{}: no event".format(reaction.where))
            vertex.reactions.append(reaction)


def _read_vertex(element, parent, machine):
    etype = element.get_type()
    if etype in _UNSUPPORTED:
        raise DocumentError("{}, element '{}': {} is not supported".format(
            machine.where(), element.get_id(), _UNSUPPORTED[etype]))
    if etype in _IGNORED:
        if (etype == CyberiadaML.elementFormalComment and
                element.get_name().startswith(COMPONENT_PREFIX)):
            _read_component(element, machine)
        return
    if etype not in _KINDS:
        raise DocumentError("{}, element '{}': unknown element type".format(
            machine.where(), element.get_id()))
    vertex = Vertex(element.get_id(), element.get_name(), _KINDS[etype], parent)
    machine.vertices[vertex.id] = vertex
    parent.children.append(vertex)
    if vertex.kind == INITIAL:
        if parent.initial is not None:
            raise DocumentError("{}, '{}': two initial pseudostates".format(
                machine.where(), parent.id))
        parent.initial = vertex
    if vertex.is_state():
        _read_state_actions(element, vertex, machine)
        for child in element.get_children():
            _read_vertex(child, vertex, machine)


def _owner(source, target):
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


def _read_transitions(sm, machine):
    for trans in sm.get_transitions():
        source = machine.vertices.get(trans.get_source_element_id())
        target = machine.vertices.get(trans.get_target_element_id())
        where = "{}, transition '{}'".format(machine.where(), trans.get_id())
        if source is None or target is None:
            raise DocumentError("{}: unknown source or target".format(where))
        reaction = Reaction(trans.get_id(), source, target, where)
        if trans.has_action():
            _set_action(reaction, trans.get_action(), machine)
        reaction.owner = _owner(source, target)
        source.reactions.append(reaction)


def _check(machine):
    if machine.root.initial is None:
        raise DocumentError("{}: no initial pseudostate".format(machine.where()))
    for vertex in machine.vertices.values():
        if vertex.kind == FINAL and vertex.reactions:
            raise DocumentError("{}, final state '{}': an outgoing transition".format(
                machine.where(), vertex.id))
        if vertex.kind == INITIAL:
            if len(vertex.reactions) != 1:
                raise DocumentError("{}, initial pseudostate '{}': one transition "
                                    "is required".format(machine.where(), vertex.id))
        if vertex.kind in (INITIAL, CHOICE):
            for reaction in vertex.reactions:
                if reaction.trigger:
                    raise DocumentError("{}: an event on a pseudostate transition".format(
                        reaction.where))
        if vertex.kind == CHOICE and not vertex.reactions:
            raise DocumentError("{}, choice '{}': no transitions".format(
                machine.where(), vertex.id))


def _read_machine(sm, meta):
    machine = Machine(sm.get_id(), sm.get_name())
    if meta.transition_order == CyberiadaML.transitionOrderExit:
        machine.transition_order = EXIT_FIRST
    machine.propagate = meta.event_propagation == CyberiadaML.docEventPropagationPropagate
    for child in sm.get_children():
        _read_vertex(child, machine.root, machine)
    _read_transitions(sm, machine)
    _check(machine)
    return machine


def load(path):
    """Read the document, return the list of its state machines."""
    doc = CyberiadaML.LocalDocument()
    try:
        doc.open(path, CyberiadaML.formatDetect, CyberiadaML.geometryFormatNone)
    except Exception as e:
        raise DocumentError(str(e)) from e
    machines = [_read_machine(sm, doc.get_meta()) for sm in doc.get_state_machines()]
    if not machines:
        raise DocumentError('the document contains no state machines')
    return machines
