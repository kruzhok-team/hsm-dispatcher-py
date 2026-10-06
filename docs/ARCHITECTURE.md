# The Python HSM Dispatcher Architecture

Document version: 0.5 (2026-10-06)

The dispatcher executes Hierarchical State Machine (HSM) diagrams at run
time. The diagrams are stored in the CyberiadaML-GraphML format (CGML,
PNST 1044-2025) and are executed with the semantics of PNST 984-2024. The
dispatcher is a general purpose library: an application loads a diagram,
supplies the components the diagram works with, and feeds events.

The dispatcher is not a code generator. It has no event loop and no threads
of its own, and it contains nothing specific to a particular application.
It depends on the `CyberiadaML` binding (`libcyberiadamlpp-py`) and on
the Python 3 standard library only.

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
| R12 | The diagram prints messages; they reach the trace and a stream chosen by the application. | Printing |
| R13 | Several machines of one document share the components that stand for one thing (the harness) and keep private the ones that do not (a timer). | Components |
| R14 | A machine is reused as a fragment of another one through a submachine state. | Submachine states |

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
| PNST 984, 7.6.7.4 | deferred events |
| PNST 984, 7.10.6 | the pseudostates: initial, choice, history, entry and exit points, terminate |
| PNST 1044, 6.1 | several state machines in a document |
| PNST 1044, 6.3.2 | a transition between a composite state and its substate is local: the composite state is not left |
| PNST 1044, 6.8 | the text of events, guards and behaviour: `entry/`, `exit/`, `Event [guard] propagate/ behaviour`, `[else]` |
| PNST 1044, 6.9 | the meta parameters `transitionOrder` (default `actionFirst`) and `eventPropagation` (default `block`) |
| PNST 1044, 8.1, 8.2, 8.3 | submachine states, history, entry and exit points |
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
| the communication of the machines of one document (1044, 6.1.2) | through the shared components; an event of the application is offered to every machine |
| the place of a deferred event when it is offered again (984, 7.6.7.4) | ahead of the queue, after the completion events |
| an exit point without an outgoing transition (984, 7.10.6) | the state is left and the machine stays in the enclosing state |
| a history pseudostate without a default transition, never entered (984, 7.10.6) | the initial pseudostate of the container |
| a machine referenced by a submachine state (1044, 8.1) | runs on its own as well, like every machine of the document |
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
   post, run, tick,       |   Dispatcher   | signal|   Timer, Log   |
   queries, snapshot      |                |       |   user types   |
                          +----------------+       +----------------+
```

The modules are plain files in the repository root; there is no package.

| Module | Role |
|---|---|
| `hsmd.py` | The `Dispatcher`: the queue, the public interface, the snapshot, the trace. The only module an application imports besides the component base. |
| `hsmd_reader.py` | Opens the document with the binding and builds the model; copies the referenced machines into the submachine states. |
| `hsmd_step.py` | The step of one machine for one event. Keeps the active configuration. |
| `hsmd_actions.py` | Compiles and runs the action and guard text. |
| `hsmd_components.py` | The `Component` base class, the registry of types, the standard types `Timer` and `Log`. |

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
* the pseudostates: initial, final, choice, shallow and deep history, entry
  and exit points, terminate;
* the transitions with the trigger, the guard, the behaviour, the
  propagation flag and the owner - the nearest common ancestor of the source
  and the target;
* the pool of the trigger names;
* the component declarations: the identifier, the type, the priority, the
  visibility and the other parameters of each `CGML_COMPONENT <id>` comment.

The binding leaves two things to the caller, and the reader resolves them:
the meta defaults (`actionFirst`, `block`) and the parameters in the body of
a component comment (`name/ value` blocks, PNST 1044, 10.3.1).

A document that uses an element outside the current stage (an orthogonal
region, a `do/` activity) is refused when it is loaded, not when the
element is reached.

## Events and the queue

An event has a name, optional named parameters and a priority. It comes
from one of two sources:

* the application: `post('START')`, `post('GO', speed=5)`;
* a component: the signal `TIMEOUT` of the component `timer1` is the event
  `timer1.TIMEOUT`.

By convention the names of the events are written in capitals, with an
underscore between the words (`GO`, `DOOR_OPENED`, `timer1.TIMEOUT`); the
identifiers of the components, the methods and the variables are lowercase.
The dispatcher compares the names as they are written and does not enforce
the convention.

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
| `sensor.CHANGED` | 0 | third |
| `timer1.TIMEOUT` | 10 | first |
| `alarm.RAISED` | 10 | second |

The consequences of the priorities are a part of the rule:

* a low priority event may be processed in a configuration changed by the
  higher ones; it is then handled, rejected or dropped like any event;
* a low priority event waits as long as higher ones keep arriving;
* the priority has an effect only when several events wait at once.

A document may hold several machines. Each machine has its own
configuration. An event of the application is offered to every machine, in
the document order, each making its own step; the signal of a shared
component is offered to every machine too, the signal of a local one to its
own machine only (see "Components"). The machines influence each other
through the shared components only.

## The step

The step of one machine for one event (PNST 984, 7.4.6.1):

1. **Select.** Starting from the active simple state and moving outwards,
   look for a transition or an internal transition whose trigger matches and
   whose guard is true. In one state the candidates are its internal
   transitions in the order of the text, then its outgoing transitions in
   the document order. Those with the name of the event are tried first,
   then those with `ANY` or `UNKNOWN`; inside each group a guard `[else]`
   is tried last. The first enabled one fires. If another candidate of the
   same group is also enabled, the trace reports the ambiguity.
2. **Execute.** An internal transition runs its behaviour only. A transition
   leaves the states from the active one up to, not including, the owner,
   runs its behaviour and enters the states down to the target. With
   `actionFirst` the behaviour precedes the exit actions, with `exitFirst`
   it follows them (PNST 984, 7.6.6.7).
3. **Settle.** Entering a composite state continues along its initial
   pseudostate until a simple state is reached. A pseudostate is a position:
   the states around it are entered before it is processed. A choice is
   resolved when it is reached, by the same candidate rule, and its branch
   is executed as a transition of its own: with `actionFirst` the order is
   first behaviour, exit, choice, second behaviour, entry. A choice with no
   true branch is an error.
4. **Complete.** If the new state has a transition without a trigger, a
   completion event is raised for it; for a composite state it is raised
   when the final state inside it is reached. The completion event belongs
   to its machine and its state and is offered to the transitions without a
   trigger only. A final state on the top level finishes the machine.
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
A   GO / -> D                        the enclosing state
B   GO propagate / n.add(1)          case 1: internal, inside A
B   GO propagate / -> C              case 2: C is inside A
B   GO propagate / -> E              case 3: E is outside A
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

GO [event.speed > 3] propagate/
counter.add(event.speed)

ANY/
log.print(event.name)
```

The text is compiled when the document is loaded, so a syntax error is
found before the machine starts. The diagram is code and is trusted like
code: the dispatcher does not restrict what the text may do.

A name assigned by the text stays visible to the later text of the same
machine, but it is not a part of the snapshot: the values to keep belong to
the components.

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
declaration other than `type`, `priority` and `shared` are passed to the
type as strings. The identifier `event` is reserved.

### Visibility

A component is **local** or **shared**. A local component belongs to the
machine that declares it: its own instance, its signals delivered to that
machine only, so two machines may both declare a `timer1` of their own. A
shared component exists once in the document: it is created at its first
declaration, every later declaration under the same identifier refers to
it, and its signals reach every machine. The type decides
(`Component.shared`, `False` unless the type says otherwise; `Timer` and
`Log` are local), and a declaration may override the type:

```
CGML_COMPONENT t
type/ Timer

shared/ yes
```

The declarations of a shared component must be identical apart from
`shared`: another type, priority or parameter in a later machine is an
error, and so is an identifier that is local in one machine and shared in
another.

A declaration carries two identifiers with different scopes. The component
identifier after `CGML_COMPONENT` is unique in its state machine, so several
machines may declare the same component (PNST 1044, 10.3.1 and 10.3.2). The
`id` of the comment node is a GraphML identifier and is unique in the whole
document like every other node (PNST 1044, 5.9): the two declarations of
`timer1` are two nodes, for example `m1_timer1` and `m2_timer1`.

The signals, methods and variables of a type can be exported as a platform
description in the form used by the Cyberiada editors, so the calls can be
shown as pictograms.

## Time

The standards have no time events. The diagrams of the Cyberiada platforms
use a `Timer` component (PNST 1044, the example of appendix Г.3), and the
dispatcher provides the same one:

| Member | Kind | Meaning |
|---|---|---|
| `TIMEOUT` | signal | the interval has passed; repeats every interval |
| `start(interval)` | method | start the timer, the interval is in milliseconds |
| `reset()` | method | begin the count again |
| `enable()`, `disable()` | methods | resume and stop the timer |
| `difference` | variable | the time left before the next `TIMEOUT` |

The dispatcher creates no threads. The application calls `tick()`; every
component compares the clock with its deadlines and raises its signals,
then the queue is processed. The clock is a parameter of the dispatcher, a
function that returns seconds like `time.monotonic`: the tests pass their
own and advance the time by hand.

The timer counts in whole milliseconds. It raises one `TIMEOUT` in a
`tick()` at most and counts the next interval from that tick, so a late
`tick()` does not produce a burst. `enable()` and `reset()` start the count
again; `disable()` keeps the time left in `difference`.

## Printing

The diagram prints through the standard component type `Log`, declared like
any other component:

```
CGML_COMPONENT log             entry/
type/ Log                      log.print('speed is', event.speed)
```

`print(...)` joins its values into one line. The line becomes a record of
the trace and is written to the output stream of the dispatcher - the
standard error stream unless the application passes another one. The text
of a diagram does not call the Python `print`.

## Deferred events

An internal transition `E/ defer` keeps the event `E` for later (PNST 984,
7.6.7.4). The deferring block is a candidate like any other: it is found
from the innermost state outwards, so a substate deferring an event beats an
enclosing state handling it, and a substate handling it beats an enclosing
state deferring it. A deferred event waits in a pool of its machine. After
every step that changed the active configuration the pool is offered again,
in the deferral order, ahead of the queue (the completion events still go
first); an event deferred again returns to the pool. The outcome of a
deferred event is `deferred`.

## History

A history pseudostate stands for the last state of its container (PNST 984,
7.10.6). The dispatcher records, whenever a container is left, its last
direct substate and the last leaf under it. A transition to a shallow
history enters the last direct substate (then its default entry if it is
composite); to a deep history, the whole last configuration, every state
entered once. When the container was never active, or its last substate was
a final state, the default transition of the history pseudostate is taken;
without one, the initial pseudostate of the container.

## Entry and exit points

A transition into an entry point enters the point's container (its entry
actions run) and then follows the one transition from the point inside the
container (PNST 984, 7.10.6). A transition into an exit point runs its
behaviour, leaves the active states up to and including the container, and
follows the transition from the point outside the container; a point
without one leaves the machine in the enclosing state. An exit point at
the top level of a machine finishes the machine. The transitions of the
points carry no event.

## Submachine states

A submachine state refers to a machine of the same document by identifier,
or to a machine of another document by `path` or `path#id` relative to the
document (PNST 1044, 8.1). The reader copies the referenced machine into
the state when the document is loaded: the state becomes a composite state
whose substates carry the identifiers `<state>/<identifier>`, whose
initial pseudostate is the referenced machine's, and whose entry and exit
points stand for the referenced machine's top-level points of the same name
(a point of the state without a counterpart is an error). The inlined
fragment runs in the configuration, the queue and the component namespace
of its host; the referenced declarations are merged by identifier - the
same type is one component, a different type is an error, a new identifier
is added. A circular reference is an error. The meta parameters of an
external document are ignored: the host's apply. A machine referenced in
the same document runs on its own as well, so it needs an initial
pseudostate like any other.

## Terminate

A transition to a terminate pseudostate runs its behaviour and ends the
machine at once: no state is left and no exit action runs (PNST 984,
7.10.6).

## Outcomes

Processing an event produces an outcome for each machine:

| Status | Meaning |
|---|---|
| `fired` | one or more transitions were executed; the outcome lists them, the branch of a choice included |
| `deferred` | the event was kept by a deferring state |
| `rejected` | a trigger matched, but every guard was false |
| `dropped` | no trigger of the active states matched (PNST 984, 7.4.6.1) |

`run()` returns the outcomes of the processed events, the completion
events included (their name is empty); `send()` posts one event, processes
the queue and returns the outcome of that event.

## The trace

The trace is a function supplied by the application. The dispatcher calls
it with a record - a tuple, the kind first:

| Record | When |
|---|---|
| `post`, name, priority[, machine] | an event is put into the queue; the machine when it is the only addressee |
| `event`, name | an event is taken from the queue |
| `guard`, machine, transition, text, value | a guard is evaluated |
| `ambiguous`, machine, chosen, others | several candidates were enabled |
| `fire`, machine, transition | a transition is executed |
| `exit`, machine, state | a state is left, before its exit actions |
| `enter`, machine, state | a state is entered, before its entry actions |
| `completion`, machine, state | a completion event is raised |
| `defer`, machine, transition | an event is deferred |
| `history`, machine, pseudostate, state | a history pseudostate restores a state |
| `terminated`, machine | the machine has reached a terminate pseudostate |
| `finished`, machine | the machine has reached its final state |
| `print`, component, line | a message of the diagram |
| `outcome`, machine, status, transitions | the result of a step |
| `error`, message | the dispatcher is stopped |

An internal transition is named by its state and its number in the text:
`a#1`; an element of an inlined submachine by its state and its own
identifier: `sub/m2s`. The tests compare the trace with the expected one.

## Errors

An exception in a behaviour or guard text ends the step at once. The
dispatcher raises an error to its caller with the machine, the element, the
block and the line of the text. The dispatcher is then stopped: the
configuration may be half changed, so no further event is accepted until
`restore()` is called. A guard that fails is not treated as false.

Errors of the document - an unknown component type, an element outside the
current stage, a syntax error in the text - are raised when it is loaded.

## The snapshot

`snapshot()` returns the execution state as a dictionary of plain data: the
version of the format, the active vertex, the finished flag and the history
of every machine, the queue, the waiting completion events, the deferred
events of every machine, the data of the components, the shared and the local
ones apart (each component reports its own; a timer reports the time left,
not the deadline). `restore()` continues from it, in the same dispatcher or
in a new one with the same document, and clears the stopped state. The
application decides where the snapshot is stored and when it is taken; the
natural moment is after `run()`, when the queue is empty.

## Interface

`Dispatcher` (`hsmd.py`):

* `Dispatcher(path, clock=None, trace=None, output=None)` - load the
  document, create the components;
* `start()` - enter the initial configuration of every machine, process
  the queue, return the outcomes;
* `post(name, priority=0, machine=None, **parameters)` - put an event into
  the queue, for every machine or for the named one;
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

A machine is named by its identifier or its name; without the argument the
first machine of the document is meant.

`Event`: `name`, `priority`, `parameters`, `machine` (the addressee, `None`
for every machine); the parameters are attributes too. `Outcome`: `event`,
`status`, `transitions`, and `results` - the status and the transitions of
each machine.

The errors are subclasses of `DispatcherError`: `DocumentError` (the
document cannot be loaded), `ActionError` (the text has failed; `where`,
`line`, `error`), `ExecutionError` (the diagram cannot be executed
further), `StoppedError` (the dispatcher is stopped).

`Component` (`hsmd_components.py`):

* `register(type, cls)` - add a component type to the registry;
* `Component(ident, dispatcher, **parameters)` - the constructor a type
  keeps; `id`, `dispatcher`, `parameters`;
* `Component.priority` - the default priority of the type;
* `Component.shared` - the default visibility of the type; `machine` - the
  owning machine of a local instance, `None` for a shared one;
* `Component.signal(name, **parameters)` - raise the event `<id>.<name>`;
* `Component.tick(now)` - called from `Dispatcher.tick()`;
* `Component.snapshot()`, `Component.restore(data)`.

## Stages

| Stage | Elements |
|---|---|
| 1 (done) | simple and composite states with one region, initial and final pseudostates, choice, `entry/` and `exit/`, internal transitions, guards and `[else]`, transitions without a trigger, `transitionOrder`, `eventPropagation` with `propagate` and `block`, `ANY`, `UNKNOWN`, several machines, components, the Timer, the Log, priorities, outcomes, the trace, the snapshot |
| 2 (done) | shallow and deep history, `defer`, entry and exit points, submachine states, terminate, the visibility of the components |
| 3 | orthogonal regions and `do/` activities |

Stage 3 needs the support of the regions and of the `do/` blocks in
`libcyberiadamlpp` first: the library rejects both today.

## Testing

A test is a diagram (`test/graphs`), a scenario (`test/scripts`) and the
expected output (`test/good`). The scenario is a list of commands - load,
start, post, send, run, clock, tick, the queries, snapshot, restore; the
output is the trace and the outcomes. The clock and the output stream
belong to the runner, `test/run.py`. There is a diagram for each rule of
this document; every diagram is checked with the validator of
`cyberiadaml-compat-tests` first. The diagrams `test/graphs/lib/` are the
external documents of the submachine tests.

## Open questions

* the execution of `do/`: a synchronous call or an activity with a
  completion event (stage 3);
* the form of the exported platform description.
