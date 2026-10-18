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

import os

# the CyberiadaML module: the binding of libcyberiadamlpp-py when installed,
# else the pure-Python interface of cyberiadaml-py (1.8 and newer)
try:
    import CyberiadaML
except ImportError:
    from cyberiadaml_py import cml as CyberiadaML

from hsmd_model import (DocumentError, STATE, COMPOSITE, INITIAL, FINAL, CHOICE, SHALLOW,
                        DEEP, ENTRY, EXIT, TERMINATE, POINT_KINDS, EVENT_ANY, EVENT_UNKNOWN,
                        EXIT_FIRST, Block, Reaction, Vertex, ComponentDeclaration, Machine,
                        add_vertex, check)

COMPONENT_PREFIX = 'CGML_COMPONENT '
META_NAME = 'CGML_META'
PARAMETER_SEPARATOR = '/'
PARAMETER_TYPE = 'type'
PARAMETER_PRIORITY = 'priority'
PARAMETER_SHARED = 'shared'
SHARED_VALUES = {'yes': True, 'true': True, 'no': False, 'false': False}

# the identifiers of an inlined machine: <submachine state>/<identifier>
INLINE_SEPARATOR = '/'
# an external reference: <path>#<machine id>
REFERENCE_FRAGMENT = '#'

_KINDS = {
    CyberiadaML.elementSimpleState: STATE,
    CyberiadaML.elementCompositeState: COMPOSITE,
    CyberiadaML.elementSubmachineState: COMPOSITE,
    CyberiadaML.elementInitial: INITIAL,
    CyberiadaML.elementFinal: FINAL,
    CyberiadaML.elementChoice: CHOICE,
    CyberiadaML.elementShallowHistory: SHALLOW,
    CyberiadaML.elementDeepHistory: DEEP,
    CyberiadaML.elementEntryPoint: ENTRY,
    CyberiadaML.elementExitPoint: EXIT,
    CyberiadaML.elementTerminate: TERMINATE,
}

_IGNORED = (CyberiadaML.elementComment, CyberiadaML.elementFormalComment,
            CyberiadaML.elementTransition)


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
    where = "{}, component '{}'".format(machine.where(), ident)
    try:
        parameters = parse_parameters(comment.get_body())
    except DocumentError as e:
        raise DocumentError("{}: {}".format(where, e)) from e
    if PARAMETER_TYPE not in parameters:
        raise DocumentError("{}: no type".format(where))
    ctype = parameters.pop(PARAMETER_TYPE)
    priority = None
    if PARAMETER_PRIORITY in parameters:
        value = parameters.pop(PARAMETER_PRIORITY)
        try:
            priority = int(value)
        except ValueError:
            raise DocumentError("{}: bad priority '{}'".format(where, value)) from None
    shared = None
    if PARAMETER_SHARED in parameters:
        value = parameters.pop(PARAMETER_SHARED)
        if value.lower() not in SHARED_VALUES:
            raise DocumentError("{}: bad shared value '{}'".format(where, value))
        shared = SHARED_VALUES[value.lower()]
    if machine.component(ident) is not None:
        raise DocumentError("{}: declared twice".format(where))
    machine.components.append(ComponentDeclaration(ident, ctype, priority, shared,
                                                   parameters, machine.id))


def _set_action(reaction, action, machine):
    propagation = action.get_propagation()
    if propagation == CyberiadaML.eventPropagationDefer:
        reaction.defer = True
    elif propagation == CyberiadaML.eventPropagationPropagate:
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
        if vertex.submachine is not None:
            raise DocumentError("{}: a submachine state has no behaviour".format(where))
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
    if etype in _IGNORED:
        if etype == CyberiadaML.elementFormalComment:
            name = element.get_name()
            if name.startswith(COMPONENT_PREFIX):
                _read_component(element, machine)
            elif name != META_NAME:
                # kept for the application: prompts, settings, anything
                machine.comments.append((name, element.get_body()))
        elif etype == CyberiadaML.elementComment:
            machine.informal.append(element.get_body())
        return
    if etype not in _KINDS:
        raise DocumentError("{}, element '{}': unknown element type".format(
            machine.where(), element.get_id()))
    vertex = Vertex(element.get_id(), element.get_name(), _KINDS[etype], parent)
    if etype == CyberiadaML.elementSubmachineState:
        vertex.submachine = element.get_submachine_reference()
    add_vertex(vertex, parent, machine)
    if vertex.is_state():
        _read_state_actions(element, vertex, machine)
        for child in element.get_children():
            _read_vertex(child, vertex, machine)


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
        source.reactions.append(reaction)


def _read_machine(sm, meta):
    machine = Machine(sm.get_id(), sm.get_name())
    if meta.transition_order == CyberiadaML.transitionOrderExit:
        machine.transition_order = EXIT_FIRST
    machine.propagate = meta.event_propagation == CyberiadaML.docEventPropagationPropagate
    for child in sm.get_children():
        _read_vertex(child, machine.root, machine)
    _read_transitions(sm, machine)
    return machine


def _read_document(path):
    doc = CyberiadaML.LocalDocument()
    try:
        doc.open(path, CyberiadaML.formatDetect, CyberiadaML.geometryFormatNone)
    except Exception as e:
        raise DocumentError(str(e)) from e
    machines = [_read_machine(sm, doc.get_meta()) for sm in doc.get_state_machines()]
    if not machines:
        raise DocumentError("'{}': the document contains no state machines".format(path))
    return machines


# ----------------------------------------------------------------------------
# submachine states: the referenced machine is copied into the state


class _Documents:
    """The documents read so far, by path."""

    def __init__(self):
        self.machines = {}

    def get(self, path):
        if path not in self.machines:
            self.machines[path] = _read_document(path)
        return self.machines[path]


def _resolve(reference, path, documents):
    """The referenced machine and the path of its document: a machine of the
    same document, or <path>[#<machine id>] relative to the document."""
    file, fragment, ident = reference.partition(REFERENCE_FRAGMENT)
    if not fragment:
        for machine in documents.get(path):
            if machine.id == reference:
                return machine, path
        file, ident = reference, None
    if file:
        path = os.path.normpath(os.path.join(os.path.dirname(path), file))
    machines = documents.get(path)
    if not ident:
        return machines[0], path
    for machine in machines:
        if machine.id == ident:
            return machine, path
    raise DocumentError("'{}': no machine '{}'".format(path, ident))


def _copy_vertex(source, parent, prefix, machine, mapping):
    """Copy a vertex tree of the referenced machine under the parent."""
    ident = prefix + source.id
    vertex = Vertex(ident, source.name, source.kind, parent)
    vertex.submachine = source.submachine
    where = "{}, state '{}'".format(machine.where(), ident)
    vertex.entry = [Block(b.text, where + ', entry') for b in source.entry]
    vertex.exit = [Block(b.text, where + ', exit') for b in source.exit]
    mapping[source] = vertex
    add_vertex(vertex, parent, machine)
    for child in source.children:
        _copy_vertex(child, vertex, prefix, machine, mapping)
    return vertex


def _copy_reaction(reaction, prefix, machine, mapping):
    source = mapping[reaction.source]
    target = mapping[reaction.target] if reaction.target is not None else None
    ident = prefix + reaction.id
    copy = Reaction(ident, source, target, "{}, inlined {}".format(
        machine.where(), reaction.where.split(', ', 1)[1]))
    copy.trigger = reaction.trigger
    copy.guard = reaction.guard
    copy.behavior = reaction.behavior
    copy.propagation = reaction.propagation
    copy.defer = reaction.defer
    source.reactions.append(copy)


def _merge_components(host, referenced, where):
    for declaration in referenced.components:
        own = host.component(declaration.id)
        if own is None:
            host.components.append(ComponentDeclaration(
                declaration.id, declaration.type, declaration.priority, declaration.shared,
                declaration.parameters, host.id))
        elif own.type != declaration.type:
            raise DocumentError("{}: the component '{}' is a {} here and a {} in the "
                                "submachine".format(where, declaration.id, own.type,
                                                    declaration.type))


def _inline(state, machine, path, documents, chain):
    where = "{}, submachine state '{}'".format(machine.where(), state.id)
    referenced, ref_path = _resolve(state.submachine, path, documents)
    key = (ref_path, referenced.id)
    if key in chain:
        raise DocumentError("{}: the reference '{}' is circular".format(
            where, state.submachine))
    _inline_all(referenced, ref_path, documents, chain + [key])
    prefix = state.id + INLINE_SEPARATOR
    mapping = {}
    # the host's points stand for the referenced machine's points of the same name
    own_points = {point.name: point for point in state.points()}
    for child in referenced.root.children:
        if child.kind in POINT_KINDS and child.name in own_points:
            point = own_points.pop(child.name)
            if point.kind != child.kind:
                raise DocumentError("{}: the point '{}' is an {} point here and an {} "
                                    "point in the submachine".format(
                                        where, child.name, point.kind, child.kind))
            mapping[child] = point
        else:
            _copy_vertex(child, state, prefix, machine, mapping)
    if own_points:
        raise DocumentError("{}: no point '{}' in the submachine".format(
            where, sorted(own_points)[0]))
    for vertex in referenced.vertices.values():
        for reaction in vertex.reactions:
            _copy_reaction(reaction, prefix, machine, mapping)
    machine.pool |= referenced.pool
    _merge_components(machine, referenced, where)
    state.submachine = None


def _inline_all(machine, path, documents, chain):
    for vertex in list(machine.vertices.values()):
        if vertex.submachine is not None:
            _inline(vertex, machine, path, documents, chain)


def load(path):
    """Read the document, return the list of its state machines."""
    documents = _Documents()
    path = os.path.normpath(path)
    machines = documents.get(path)
    for machine in machines:
        _inline_all(machine, path, documents, [(path, machine.id)])
        check(machine)
    return machines
