# The Python HSM Dispatcher Architecture

Document version: 0.2 (2026-10-02)

The dispatcher executes Hierarchical State Machine (HSM) diagrams at run
time. The diagrams are stored in the CyberiadaML-GraphML format (CGML,
PNST 1044-2025) and are executed with the semantics of PNST 984-2024. The
dispatcher is a general purpose library: an application loads a diagram,
supplies the components the diagram works with, and feeds events.

The dispatcher is not a code generator (`hsm-to-python` stays the tool for
standalone programs). It has no event loop and no threads of its own, and it
contains nothing specific to a particular application. It depends on the
`CyberiadaML` binding (`libcyberiadamlpp-py`) and on the Python 3 standard
library only.

## Usage requirements

The requirements come from the first user of the dispatcher, the
`cybersphere-agents` framework, and are stated for any application.

| No | Requirement | Section |
|---|---|---|
| R1 | Load a CGML document with one or more state machines. | The model |
| R2 | Be embedded: the application posts the events and calls `tick()`; the dispatcher never blocks and starts nothing by itself. | Structure, Time |
| R3 | The diagram acts on the application only through components; the application adds its own component types. | Components |
| R4 | The action and guard text of the diagram is Python. | Actions |
| R5 | Every event has an outcome the application can read: the transitions fired, or the event was rejected by the guards, or dropped. | Outcomes |
| R6 | Answer the queries: the active states, whether a machine has finished, the triggers that can fire in the current configuration. | Interface |
| R7 | Events of some components are more urgent than the events of others. | Events and the queue |
| R8 | Provide time: timeouts and periodic events, reproducible under a test clock. | Time |
| R9 | Save the execution state and continue from it later. | The snapshot |
| R10 | Report every step in a trace usable by tests and diagnostics. | The trace |
| R11 | A mistake in the text of the diagram stops the machine and names the place. | Errors |

## Standards

What the dispatcher implements and where it is defined:

| Clause | Subject |
|---|---|
| PNST 984, 7.4.6.1 | the step: one event at a time, run to completion; an event that fires nothing is dropped |
| PNST 984, 7.4.6.3, 7.4.6.4, 7.4.6.5 | conflicting transitions, the priority of the inner state, the selection from the innermost state outwards |
| PNST 984, 7.4.6.6, 7.6.6.8 | passing a handled event to the enclosing states: the default of the machine, `propagate` and `block` on a transition |
| PNST 984, 7.4.6.7 | the special events `ANY` and `UNKNOWN` |
| PNST 984, 7.6.6.4 | transitions without a trigger and the completion event |
| PNST 984, 7.6.6.7 | the sequence of a transition and its alternative order |
| PNST 984, 7.6.7.4 | deferred events (stage 2) |
| PNST 984, 7.10.6 | the pseudostates: initial, choice, history, entry and exit points, terminate |
| PNST 1044, 6.1 | several state machines in a document |
| PNST 1044, 6.3.2 | a transition between a composite state and its substate is local: the composite state is not left |
| PNST 1044, 6.8 | the text of events, guards and behaviour: `entry/`, `exit/`, `Event [guard] propagate/ behaviour`, `[else]` |
| PNST 1044, 6.9 | the meta parameters `transitionOrder` (default `actionFirst`) and `eventPropagation` (default `block`) |
| PNST 1044, 8.1, 8.2, 8.3 | submachine states, history, entry and exit points (stage 2) |
| PNST 1044, 10.3 | the components: `CGML_COMPONENT <id>` with the `type` parameter |

The standards leave these points undefined. The dispatcher fixes them:

| Point | Rule of the dispatcher |
|---|---|
| the order of the event queue (984, 7.4.6.1) | by the priority of the component that raised the event, then by arrival |
| several enabled transitions of one state (984, 7.4.6.3) | the first in the document order fires; the ambiguity is reported in the trace |
| the priority of `ANY` (984, 7.4.6.7) | an ordinary trigger, tried after the named triggers of the same state |
| the event pool for `ANY` and `UNKNOWN` | the trigger names used in the machine |
| a propagated event after the inner state has reacted (984, 7.4.6.6) | offered to the next enclosing state while that state is still active |
| the parameters of an event in the text (984, 7.6.7.2) | the current event is visible as `event` |
| the communication of the machines of one document (1044, 6.1.2) | every event is offered to every machine |
| a failure of the action text | the machine stops, the error goes to the application |

## Structure

```
   hsmd_reader.py            hsmd_step.py            hsmd_actions.py
 +----------------+       +----------------+       +----------------+
 |                | model |                | text  |                |
 |     Reader     | ----> |  Interpreter   | ----> |    Actions     |
 |                |       |                | <---- |                |
 +----------------+       +----------------+ value +----------------+
         |                   ^          |             |          ^
    CyberiadaML        event |          | outcome     | calls    | variables
                             |          v             v          |
                              hsmd.py               hsmd_components.py
                          +----------------+       +----------------+
  application ----------> |                | <---- |   Component    |
   post, run, tick,       |   Dispatcher   | signal|   Timer        |
   queries, snapshot      |                |       |   user types   |
                          +----------------+       +----------------+
```

The modules are plain files in the repository root; there is no package.

| Module | Role |
|---|---|
| `hsmd.py` | The `Dispatcher`: the queue, the public interface, the snapshot, the trace. The only module an application imports besides the component base. |
| `hsmd_reader.py` | Opens the document with the binding and builds the model. |
| `hsmd_step.py` | The step of one machine for one event. Keeps the active configuration. |
| `hsmd_actions.py` | Compiles and runs the action and guard text. |
| `hsmd_components.py` | The `Component` base class, the registry of types, the `Timer`. |

The application talks to the `Dispatcher` only. The text of the diagram
calls the components; the components answer with signals, which return to
the queue. Nothing calls the application back except its own components and
the trace.

## The model

The reader opens the document with `CyberiadaML.LocalDocument` and follows
the pattern of `hsm-console-viewer/hsmmodel.py`: `get_meta()`,
`get_state_machines()`, the walk over `get_children()`, `get_actions()` of a
state and `get_transitions()` of a machine. For every machine it builds:

* the states with their parents and their `entry`, `exit` and internal
  transition blocks, in the document order;
* the pseudostates: initial, final, choice (history, points and terminate
  in stage 2);
* the transitions with the trigger, the guard, the behaviour, the
  propagation flag and the owner - the nearest common ancestor of the source
  and the target;
* the pool of the trigger names;
* the component declarations: the identifier and the parameters of each
  `CGML_COMPONENT <id>` comment.

The binding leaves two things to the caller, and the reader resolves them:
the meta defaults (`actionFirst`, `block`) and the parameters in the body of
a component comment (`name/ value` blocks, PNST 1044, 10.3.1).

A document that uses an element outside the current stage is refused when
it is loaded, not when the element is reached.

## Events and the queue

An event has a name, optional named parameters and a priority. It comes
from one of two sources:

* the application: `post('start')`, `post('go', speed=5)`;
* a component: the signal `timeout` of the component `timer1` is the event
  `timer1.timeout`.

All waiting events are in one queue. The next event to process is the one
with the highest priority; among equal priorities, the one that arrived
first. The completion events (PNST 984, 7.6.6.4) are taken before any other.

The priority of an event is the priority of its component: a number set by
the component type and optionally replaced in the declaration:

```
CGML_COMPONENT timer1          CGML_COMPONENT sensor
type/ Timer                    type/ Sensor

priority/ 10
```

An event posted by the application has the priority 0 unless the call gives
another one.

| Waiting, in the order of arrival | Priority | Processed |
|---|---|---|
| `sensor.changed` | 0 | third |
| `timer1.timeout` | 10 | first |
| `alarm.raised` | 10 | second |

The consequences of the priorities are a part of the rule:

* a low priority event may be processed in a configuration changed by the
  higher ones; it is then handled, rejected or dropped like any event;
* a low priority event waits as long as higher ones keep arriving;
* the priority has an effect only when several events wait at once.

A document may hold several machines. Each machine has its own
configuration and its own components. An event is offered to every machine,
in the document order, each making its own step. The machines influence
each other only through events, so a component identifier should be unique
in the document: two machines declaring the same identifier receive each
other's signals under one name.

## The step

The step of one machine for one event (PNST 984, 7.4.6.1):

1. **Select.** Starting from the active simple state and moving outwards,
   look for a transition or an internal transition whose trigger matches and
   whose guard is true. In one state the candidates are tried in the
   document order: the named triggers, then `ANY`; a guard `[else]` is
   tried last. The first enabled one fires. If another candidate of the same
   state is also enabled, the trace reports the ambiguity.
2. **Execute.** An internal transition runs its behaviour only. A transition
   leaves the states from the active one up to, not including, the owner,
   runs its behaviour and enters the states down to the target. With
   `actionFirst` the behaviour precedes the exit actions, with `exitFirst`
   it follows them (PNST 984, 7.6.6.7).
3. **Settle.** Entering a composite state continues along its initial
   pseudostate until a simple state is reached. A choice is resolved when it
   is reached, by the same candidate rule; a choice with no true branch is
   an error.
4. **Complete.** If the new state has a transition without a trigger, a
   completion event is raised for it. A final state on the top level
   finishes the machine.
5. **Propagate.** See below.

A transition from a state to itself leaves and enters the state. A
transition between a composite state and its own substate does not leave
the composite state (PNST 1044, 6.3.2).

### Propagation

After a reaction the event is either blocked or passed outwards: by the
flag of the transition (`propagate`, `block`) or, without a flag, by the
`eventPropagation` of the document. A passed event is offered to the next
enclosing state if that state is still active, with the same selection rule.
Its guards are evaluated at that moment.

```
A   go / -> D                        the enclosing state
B   go propagate / n.add(1)          case 1: internal, inside A
B   go propagate / -> C              case 2: C is inside A
B   go propagate / -> E              case 3: E is outside A
```

| Case | Result |
|---|---|
| 1 | the internal transition of `B`, then `A -> D` |
| 2 | `B -> C`, then `A -> D`: two changes of state in one step |
| 3 | `B -> E` only: `A` is no longer active |

### ANY and UNKNOWN

The pool of a machine is the set of the trigger names used in it. `ANY`
matches an event of the pool, `UNKNOWN` an event outside it; neither
matches a completion event. `ANY` obeys the common rule of the innermost
state: an `ANY` of an inner state hides the handlers of the enclosing
states unless it is marked `propagate`.

## Actions

The behaviour text is executed as Python statements, the guard text is
evaluated as a Python expression. The names visible to the text:

* the component identifiers of the machine;
* `event` - the event being processed: `event.name` and its parameters as
  attributes.

```
entry/
timer1.start(1000)

go [event.speed > 3] propagate/
counter.add(event.speed)

ANY/
log.write(event.name)
```

The text is compiled when the document is loaded, so a syntax error is
found before the machine starts. The diagram is code and is trusted like
code: the dispatcher does not restrict what the text may do.

## Components

A component is a Python object with signals (the events it may raise),
methods (the calls available to the text) and variables (the values
available to the text).

```
 CGML_COMPONENT timer1          registry                 names of the machine
 type/ Timer             --->   'Timer' -> class   --->  timer1 = Timer(...)
 priority/ 10                   Timer(Component)         parameters as arguments
```

A component type is a subclass of `Component` registered under its `type`
name. The application registers its types before the document is loaded; a
declaration with an unknown type is an error. The parameters of the
declaration other than `type` and `priority` are passed to the type.

The signals, methods and variables of a type can be exported as a platform
description in the form used by the Cyberiada editors, so the calls can be
shown as pictograms.

## Time

The standards have no time events. The diagrams of the Cyberiada platforms
use a `Timer` component (PNST 1044, the example of appendix Г.3), and the
dispatcher provides the same one:

| Member | Kind | Meaning |
|---|---|---|
| `timeout` | signal | the interval has passed; repeats every interval |
| `start(interval)` | method | start the timer, the interval is in milliseconds |
| `reset()` | method | begin the count again |
| `enable()`, `disable()` | methods | resume and stop the timer |
| `difference` | variable | the time left before the next `timeout` |

The dispatcher creates no threads. The application calls `tick()`; every
component compares the clock with its deadlines and raises its signals,
then the queue is processed. The clock is a parameter of the dispatcher:
the tests pass their own and advance the time by hand.

## Outcomes

Processing an event produces an outcome for each machine:

| Status | Meaning |
|---|---|
| `fired` | one or more transitions were executed; the outcome lists them |
| `rejected` | a trigger matched, but every guard was false |
| `dropped` | no trigger of the active states matched (PNST 984, 7.4.6.1) |

`run()` returns the outcomes of the processed events; `send()` posts one
event, processes the queue and returns the outcome of that event.

## The trace

The trace is a function supplied by the application. The dispatcher calls
it with a record for: an event taken from the queue, a guard evaluated and
its value, a behaviour block executed, a state left, a state entered, a
signal raised, an ambiguity, an outcome. The tests compare the trace with
the expected one.

## Errors

An exception in a behaviour or guard text ends the step at once. The
dispatcher raises an error to its caller with the machine, the element, the
block and the line of the text. The dispatcher is then stopped: the
configuration may be half changed, so no further event is accepted until
`restore()` is called. A guard that fails is not treated as false.

Errors of the document - an unknown component type, an element outside the
current stage, a syntax error in the text - are raised when it is loaded.

## The snapshot

`snapshot()` returns the execution state as plain data: the active
configuration of every machine, the queue, the state of the components
(each component reports its own). `restore()` continues from it and clears
the stopped state. The application decides where the snapshot is stored and
when it is taken; the natural moment is after `run()`, when the queue is
empty.

## Interface

`Dispatcher` (`hsmd.py`):

* `Dispatcher(path, clock=None, trace=None)` - load the document, create
  the components;
* `start()` - enter the initial configuration of every machine;
* `post(name, priority=0, **parameters)` - put an event into the queue;
* `run()` - process the queue until it is empty, return the outcomes;
* `send(name, **parameters)` - `post()` and `run()`, return the outcome of
  the event;
* `tick()` - let the components check the clock, then `run()`;
* `states(machine=None)` - the active states;
* `finished(machine=None)` - whether the machine has reached its final
  state;
* `triggers(machine=None)` - the trigger names of the transitions that can
  be selected in the current configuration, the guards not evaluated;
* `snapshot()`, `restore(data)`;
* `stopped` - set after an error.

`Component` (`hsmd_components.py`):

* `register(type, cls)` - add a component type to the registry;
* `Component.priority` - the default priority of the type;
* `Component.signal(name, **parameters)` - raise the event `<id>.<name>`;
* `Component.tick(now)` - called from `Dispatcher.tick()`;
* `Component.snapshot()`, `Component.restore(data)`.

## Stages

| Stage | Elements |
|---|---|
| 1 | simple and composite states with one region, initial and final pseudostates, choice, `entry/` and `exit/`, internal transitions, guards and `[else]`, transitions without a trigger, `transitionOrder`, `eventPropagation` with `propagate` and `block`, `ANY`, `UNKNOWN`, several machines, components, the Timer, priorities, outcomes, the trace, the snapshot |
| 2 | shallow and deep history, `defer`, entry and exit points, submachine states, terminate |
| 3 | orthogonal regions and `do/` activities |

Stage 3 needs the support of the regions and of the `do/` blocks in
`libcyberiadamlpp` first: the library rejects both today.

## Testing

A test loads a diagram, posts a sequence of events and compares the trace
and the outcomes with the expected ones; the clock belongs to the test. The
diagrams are the ones of `cyberiadaml-compat-tests` and the examples of
this project, one per rule of this document.

## Open questions

* the order of the behaviour of the two segments around a choice under
  `actionFirst`; proposed: first segment, exit, choice, second segment,
  entry;
* the place of the deferred events in the queue (stage 2);
* the execution of `do/`: a synchronous call or an activity with a
  completion event (stage 3);
* the format of the snapshot data;
* the form of the exported platform description.
