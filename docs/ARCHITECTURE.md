# The Python HSM Dispatcher Architecture

Document version: 0.1 (2026-10-02)

The dispatcher executes Hierarchical State Machine (HSM) diagrams stored in
the CyberiadaML-GraphML format (CGML, PNST 1044-2025) with the semantics of
PNST 984-2024. It interprets the diagram at run time: nothing is generated
or compiled. The code generator `hsm-to-python` stays the tool for producing
standalone programs.

The dispatcher depends on the `CyberiadaML` binding (`libcyberiadamlpp-py`)
and on the Python 3 standard library only. It knows nothing about the
application: everything the diagram can do is provided by components.

## Components

```
                     reader.py              interpreter.py            actions.py
                  +---------------+        +---------------+        +---------------+
  diagram.graphml |               |        |               | -text> |               |
  ---- CGML ----> |    Reader     | model> |  Interpreter  |        |    Actions    |
                  |               |        |               | <bool- |               |
                  +---------------+        +---------------+        +---------------+
                          |                   ^         |              |         ^
                     CyberiadaML        event |         | state      calls   variables
                                              |         v              v         |
                                           dispatcher.py             components.py
                                           +---------------+        +---------------+
  application --- post(), tick() --------> |               |        |  Components   |
              <-- states(), snapshot() --- |  Dispatcher   | <-sig- |  Timer, the   |
                                           |               |        |  user's own   |
                                           +---------------+        +---------------+
```

The call direction: the application talks to the `Dispatcher` only; the
`Interpreter` asks `Actions` to run the text of the diagram; the text calls
the components; the components answer with signals, which return to the
queue of the `Dispatcher`.

## Modules

| Module | Role |
|---|---|
| `reader.py` | Opens the document with `CyberiadaML.LocalDocument` and builds the resolved model: states with parents, transitions with owners, parsed actions, the meta parameters, the component declarations. |
| `interpreter.py` | One run-to-completion step: selects the transitions for an event and runs the exit, transition and entry actions. Keeps the active state configuration. |
| `actions.py` | Compiles and runs the action text (`exec`) and the guard text (`eval`) in the namespace of the component instances. |
| `components.py` | The `Component` base class, the registry of component types and the `Timer`. |
| `dispatcher.py` | The public interface: the event queue, `post()`, `tick()`, the state queries, the snapshot. |

## The diagram

One CGML document, one or more state machines. The dispatcher uses:

* the states, pseudostates and transitions of each machine;
* the action text of the states and transitions (PNST 1044, 6.8): `entry/`,
  `exit/` and `Event [guard] / behaviour` blocks;
* the meta parameters `transitionOrder` (default `actionFirst`) and
  `eventPropagation` (default `block`) (PNST 1044, 6.9);
* the formal comments `CGML_COMPONENT <id>` with the mandatory `type`
  parameter (PNST 1044, 10.3) - the components of the machine.

The reader follows the pattern of `hsm-console-viewer/hsmmodel.py`:
`LocalDocument.open()`, `get_meta()`, `get_state_machines()`, the walk over
`ElementCollection.get_children()`, `State.get_actions()` and
`StateMachine.get_transitions()`. The binding leaves the meta defaults and
the component parameters to the caller, so the reader resolves both.

## Events

An event is a name with optional parameters. There are two sources:

* the application calls `post(name)`;
* a component raises a signal, which becomes the event `<id>.<signal>`, for
  example `timer1.timeout`.

Events are processed one at a time, each to completion (PNST 984, 7.4.6.1).
The actions executed during a step may raise new events; they wait in the
queue. An event that fires nothing is dropped.

## The interpreter

The step for one event:

1. find the enabled transitions, starting from the innermost active state
   (PNST 984, 7.4.6.5); the guards are evaluated at this moment;
2. run the transition: with `actionFirst` the transition action precedes the
   exit actions, with `exitFirst` it follows them (PNST 984, 7.6.6.7);
3. enter the target states, outermost first, following the initial
   pseudostates down to a simple state;
4. raise the completion event for the transitions without a trigger.

The supported part of the standard grows in three stages:

| Stage | Elements |
|---|---|
| 1 | simple and composite states with one region, initial and final pseudostates, choice, `entry/` and `exit/`, internal transitions, guards and `[else]`, transitions without a trigger, `transitionOrder`, `eventPropagation` with the `propagate` and `block` flags, the `ANY` event |
| 2 | shallow and deep history, `defer`, entry and exit points, submachine states, the `UNKNOWN` event, terminate |
| 3 | orthogonal regions and `do/` activities |

Stage 3 needs the support of the regions and of the `do/` blocks in
`libcyberiadamlpp` first: the library rejects both today.

## Actions

The action and guard text is Python. A behaviour block is executed, a guard
is evaluated as an expression. The names visible to the text are the
component identifiers of the machine:

```
entry/
timer1.start(1000)
led1.on()

timer1.timeout [counter.value < 10]/
counter.add(1)
```

The diagram is code and is trusted like code: the dispatcher does not
restrict what the text may do.

## Components

A component is a Python object with:

* signals - the events it may raise;
* methods - the calls available to the actions;
* variables - the values available to the actions and guards.

```
 CGML_COMPONENT timer1          registry                 namespace of the machine
 type/ Timer             --->   'Timer' -> class   --->  timer1 = Timer(...)
 <other parameters>             Timer(Component)         parameters as arguments
```

A component type is a subclass of `Component` registered under its `type`
name. The application registers its own types before the diagram is loaded;
a declaration with an unknown type is an error. The declared signals,
methods and variables can be exported as a platform description in the form
used by the Cyberiada editors, so that the calls can be shown as pictograms.

## The Timer

The time is not a part of the standard: the diagrams of the Cyberiada
platforms use a `Timer` component (PNST 1044, the example of appendix Г.3).
The dispatcher provides the same component:

| Member | Kind | Meaning |
|---|---|---|
| `timeout` | signal | the interval has passed; repeats every interval |
| `start(interval)` | method | start the timer, the interval is in milliseconds |
| `reset()` | method | begin the count again |
| `enable()`, `disable()` | methods | resume and stop the timer |
| `difference` | variable | the time left before the next `timeout` |

The dispatcher does not create threads. The application calls `tick()`, the
components compare the clock with their deadlines and raise the signals. The
clock is a parameter of the dispatcher, so the tests advance the time by
hand.

## The snapshot

`snapshot()` returns the active configuration, the queue, the history and
the variables of the components as plain data; `restore()` continues from
it. The application decides where the snapshot is stored.

## Testing

The interpreter is tested on diagrams from `cyberiadaml-compat-tests` and on
its own examples: each test posts a sequence of events and compares the
trace of the executed actions with the expected one. The clock is advanced
by the test. No external interpreter is a part of the dispatcher.

## Open questions

The standards leave these points undefined; the detailed specification
decides them:

* the order of the queue and the place of the completion and deferred
  events in it;
* the priority of `ANY` and `UNKNOWN` against the explicit triggers;
* the order of several enabled transitions of one state;
* how an event passed up by `propagate` meets a configuration already
  changed by the inner transition;
* the communication between the machines of one document: common queue or
  separate ones;
* the execution of `do/`: a synchronous call or an asynchronous activity
  with a completion event;
* the passing of event parameters to the action text;
* the format of the snapshot.
