# The Python HSM Dispatcher Interface Specification

Document version: 0.1 (2026-10-17)

This document is for the authors of the programs that run state machines on
the dispatcher, of the diagrams those programs run, and of the component
types. It specifies everything they use: the `Dispatcher`, the code of a
diagram, a machine written in Python, the standard components, the time
events, a component type of one's own and the errors. The execution rules
and their reasons are in `ARCHITECTURE.md`; hsm-to-python generates programs
that use this interface.

```
 the program                          hsmd                          the diagram
 ───────────                          ────                          ───────────
 Dispatcher(source, ...)  ──────────▶ the model ◀──── a document (CyberiadaML) or
 start() post() run() send() tick()   the queue        hsmd.Machine(...) declarations
 states() finished() snapshot()       the components ──▶ Timer, Clock, Console, Log,
      ▲                                    │               types of the program
      └──── outcomes, trace ◀──────────────┘  ◀──── signals <id>.<SIGNAL>
```

Everything is imported from one module: `import hsmd`.

## Conventions

* An **event** has a name, a priority and named parameters. The names are
  written in capitals with an underscore between the words: `GO`,
  `DOOR_OPENED`. The dispatcher compares them as written.
* A **component** is declared in the machine that uses it, one declaration
  per instance, by the formal comment `CGML_COMPONENT <id>` (PNST 1044,
  10.3) with the parameters `type`, optionally `priority` and `shared`, and
  the parameters of its type:

  ```
  CGML_COMPONENT blink
  type/ Timer

  priority/ 10
  ```

  The component identifier (`blink`) is unique in its machine; the `id` of
  the comment node is unique in the document like every node.
* A **signal** `S` of the component `c` is the event `c.S`; a transition
  names it as its trigger: `blink.TIMEOUT/`.
* A **method** is called from the code: `blink.start(500)`; a **variable** is
  read: `[blink.difference < 100]`.
* The **priority** orders the waiting events: the higher first, equal ones
  in the order of arrival. An event of the program has the priority 0, a
  signal the priority of its component.
* A component is **local** (an instance per declaring machine, its signals
  to that machine) or **shared** (one instance in the document under the same
  identifier and type, its signals to every machine). The type decides,
  `shared/ yes` or `shared/ no` overrides.
* **Times:** the clock and the calendar are seconds (floats), `period` is
  seconds, a `Timer` counts milliseconds.

## The dispatcher

```python
import time

import hsmd

dispatcher = hsmd.Dispatcher('blinker.graphml', period=0.1)
dispatcher.start()
outcome = dispatcher.send('button.PRESSED', long=True)
print(outcome.status, dispatcher.states())
while not dispatcher.finished():
    dispatcher.tick()                    # the time events, the timers, the console
    time.sleep(0.1)
```

### `Dispatcher(source, clock=None, trace=None, output=None, machines=None, namespace=None, period=None, calendar=None, input=None)`

| Parameter | Meaning |
|---|---|
| `source` | the path of a CyberiadaML document, or a `hsmd.Machine` or a list of them |
| `clock` | a function returning the seconds of a monotonic clock; `time.monotonic` |
| `trace` | a function called with each trace record (a tuple); no trace without it |
| `output` | the stream of the `Log` messages; `sys.stderr` |
| `machines` | the identifiers or names of the machines to run; all of them |
| `namespace` | the dictionary the code of the machines runs in; a new one |
| `period` | seconds: `tick()` posts the time events; none without it |
| `calendar` | a function returning the calendar time, the seconds of the epoch, for `Clock`; `time.time` |
| `input` | the stream of `Console`; `sys.stdin` |

The constructor loads the document (or builds the declared machines),
checks them, creates the components and compiles the code; a problem is a
`DocumentError`. Nothing runs before `start()`. A program that writes the
code of its machine as functions gives its own globals as the namespace:
`namespace=globals()`.

### Methods

| Method | Returns | Does |
|---|---|---|
| `start()` | the outcomes | enters the initial configuration of every machine, processes the queue |
| `post(name, priority=0, machine=None, **parameters)` | the `Event` | puts an event into the queue, for every machine or for the named one |
| `run()` | the outcomes | processes the queue until it is empty |
| `send(name, **parameters)` | the `Outcome` of the event | `post()` and `run()` |
| `tick()` | the outcomes | posts the due time events, lets every component check the clock, `run()` |
| `states(machine=None)` | a list of state identifiers | the active states, the outermost first |
| `finished(machine=None)` | `bool` | whether the machine has reached its final state |
| `triggers(machine=None)` | a list of names | the triggers of the active states, the guards not evaluated |
| `comments(machine=None, formal=True)` | `(name, body)` pairs | the comments the dispatcher does not interpret: the formal ones, the informal ones (`False`, the name empty) or both (`None`) |
| `snapshot()` | a dictionary of plain data | the execution state |
| `restore(data)` | | continues from a snapshot, clears the stopped state |

A machine is named by its identifier or its name; without it the first
machine is meant. `stopped` is true after an error (see Errors).

### `Event` and `Outcome`

`Event`: `name`, `priority`, `parameters` (a dictionary), `machine` (the
addressee, `None` for every machine). The parameters are attributes too:
`event.speed`; a missing one is an `AttributeError`.

`Outcome`: `event`, `status`, `transitions` (the identifiers of the executed
transitions) and `results` (one per machine: `machine`, `status`,
`transitions`). The status:

| Status | Constant | Meaning |
|---|---|---|
| `fired` | `hsmd.FIRED` | one or more transitions were executed |
| `deferred` | `hsmd.DEFERRED` | a deferring state kept the event |
| `rejected` | `hsmd.REJECTED` | a trigger matched, every guard was false |
| `dropped` | `hsmd.DROPPED` | no trigger matched |

The outcomes of `run()` include the completion events; their name is empty.

### The trace

The trace function gets a tuple, the kind first:

| Record | When |
|---|---|
| `('post', name, priority[, machine])` | an event is queued |
| `('event', name)` | an event is taken from the queue |
| `('guard', machine, transition, text, value)` | a guard is evaluated (`text` is the name of a guard function) |
| `('fire', machine, transition)` | a transition is executed |
| `('exit', machine, state)`, `('enter', machine, state)` | a state is left, entered |
| `('completion', machine, state)` | a completion event is raised |
| `('defer', machine, transition)` | an event is deferred |
| `('history', machine, pseudostate, state)` | a history pseudostate restores a state |
| `('ambiguous', machine, chosen, others)` | several transitions were enabled |
| `('terminated', machine)`, `('finished', machine)` | a terminate, the final state |
| `('print', component, line)` | a `Log` message |
| `('outcome', machine, status, transitions)` | the result of a step |
| `('error', message)` | the dispatcher is stopped |

An internal transition is named `<state>#<n>`, an element of an inlined
submachine `<state>/<identifier>`.

### The snapshot

`snapshot()` returns the version of the format, the configuration and the
history of every machine, the queue, the deferred events and the data of the
components, as plain data (JSON stores it when the event parameters are
plain too). `restore(data)` continues
from it in the same dispatcher or in a new one with the same machines. Take
it after `run()`, when the queue is empty. A timer keeps the time left, a
clock its alarm; a console has no snapshot.

## The code of a diagram

The behaviour of a state or a transition is Python statements, a guard is
an expression. They see:

* the components of the machine by their identifiers: `blink.start(500)`;
* `event`, the event being processed: `event.name`, `event.speed`;
* the names of the namespace (`namespace=`): the program's functions and
  variables. A name the code assigns stays in the namespace, visible to the
  later code of the machine.

```
entry/
blink.start(500)

GO [event.speed > 3]/
log.print('going at', event.speed)

blink.TIMEOUT/
led = not led

[else]/
```

The trigger `ANY` matches every event some trigger of the machine names,
`UNKNOWN` an event no trigger names; an `ANY` of an inner state hides the
handlers of the enclosing states unless it is marked `propagate`. `[else]` is
the guard of the way taken when no other guard of the same trigger holds.
The time events are below.

The code may also be Python functions (see the next section): a function is
called without arguments and works in the globals of its module, so the
program gives them as the namespace; the names it assigns are declared
`global`. An error in the code is an `ActionError` naming the element and
the line of the block.

## A machine written in Python

A program may declare its machine instead of loading a document: the code
is functions, the structure a tree of declarations. The rules of a document
apply, and neither the file nor `CyberiadaML` is needed.

```python
import hsmd


def idle_entry():
    log.print('idle')


def go_guard():
    return event.speed > 3


machine = hsmd.Machine('Robot', id='R', states=[
    hsmd.Initial(id='init'),
    hsmd.State('Idle', id='idle', entry=idle_entry, internal=[
        hsmd.On('PING', action="log.print('pong')"),
    ]),
    hsmd.State('Work', id='work', states=[
        hsmd.Initial(id='work-init'),
        hsmd.State('Step', id='step'),
    ]),
    hsmd.Final(id='fin'),
], transitions=[
    hsmd.Transition('init', 'idle'),
    hsmd.Transition('idle', 'work', 'GO', guard=go_guard),
    hsmd.Transition('work-init', 'step'),
    hsmd.Transition('work', 'fin', 'STOP'),
], components=[
    hsmd.Declaration('log', 'Log'),
])

dispatcher = hsmd.Dispatcher(machine, namespace=globals())
```

| Declaration | Meaning |
|---|---|
| `Machine(name, id=None, states=(), transitions=(), components=(), transition_order='actionFirst', propagate=False, comments=())` | a state machine; the comments are `(name, body)` pairs, the name empty for an informal one |
| `State(name, id=None, entry=None, exit=None, internal=(), states=())` | a state, composite with `states`; `entry`, `exit`: one piece of code or a list |
| `Initial(id=None)`, `Final(id=None)`, `Terminate(id=None)` | the pseudostates and the final state |
| `Choice(id=None, name='')`, `History(id=None, deep=False)` | a choice, a shallow or deep history |
| `EntryPoint(name, id=None)`, `ExitPoint(name, id=None)` | the points of a state or of the machine |
| `On(event, guard=None, action=None, propagate=None, defer=False)` | an internal transition of its state |
| `Transition(source, target, event='', guard=None, action=None, propagate=None, defer=False, id=None)` | a transition between the vertices named by their identifiers |
| `Declaration(id, type, priority=None, shared=None, **parameters)` | a component |
| `ELSE` | the `[else]` guard |

A guard or an action is a function or text. The identifiers left out are: a
machine's or a state's name; `<parent>.<kind>` for a pseudostate (a point
`<parent>.<name>`); `<state>#<n>` for an internal transition;
`<source>-<target>` for a transition, `#2`, `#3` for the next ones with the
same ends. `propagate=None` is the machine's default. A declaration breaking
the rules is a `DocumentError` from the `Dispatcher`.

## The standard components

### Timer

Local. Counts milliseconds on the dispatcher's clock.

* Signals: `TIMEOUT` - the interval has passed; it repeats every interval,
  or comes once after `once()`.
* Methods: `start(interval)` - periodic; `once(interval)` - a single
  `TIMEOUT`, then the timer is disabled (`start()` makes it periodic again);
  `reset()` - count the interval again; `enable()`, `disable()` - resume and
  stop, keeping the time left.
* Variables: `interval`, `enabled`, `difference` - the time left before the
  next `TIMEOUT`.

A late `tick()` raises one `TIMEOUT`; the next interval counts from it.

```
entry/
blink.start(500)
deadline.once(10000)

deadline.TIMEOUT/
log.print('too late')
```

### Clock

Local. The calendar time of the dispatcher (`calendar=`) in the local time.

* Signals: `ALARM` - the local time has the fields of the alarm.
* Methods: `alarm(hour=None, minute=0, second=0)` - ring at every local
  time with these fields, `None` for any value; `cancel()`.
* Variables: `now` (a `datetime`), `hour`, `minute`, `second`, `weekday`
  (0 for Monday).

| Call | Rings |
|---|---|
| `alarm(9)` | every day at 09:00:00 |
| `alarm(9, 30)` | every day at 09:30:00 |
| `alarm()` | every hour at hh:00:00 |
| `alarm(minute=None)` | every minute at hh:mm:00 |

A late `tick()` raises one `ALARM`, the next one is the next matching time;
the daylight saving time is followed.

```
entry/
morning.alarm(9)

morning.ALARM [morning.weekday < 5]/
log.print('a working day', morning.now.date())
```

### Console

Shared: one input for the document. The lines of the dispatcher's `input`
(`sys.stdin`), UTF-8, polled by `tick()` without blocking.

* Signals: `LINE(text)` - a line, `event.text` without the newline; `EOF` -
  once, after the last line (a last line without a newline is a `LINE`
  first).
* Variables: `last` - the last line read; when one `tick()` reads several
  lines it is ahead of the event, so a transition reads `event.text`.

On Windows only the keyboard of the console is read, a piped input is not.

```
console.LINE [event.text == 'quit']/
log.print('bye')

console.EOF/
```

### Log

Local. Methods: `print(*values)` - one line to the dispatcher's `output`
(`sys.stderr`) and the `print` record of the trace. No signals.

## The time events

With `period` (seconds), `tick()` posts the time events the started
machines trigger on, counted from `start()` on the dispatcher's clock
(`hsmd.TIME_EVENTS`):

| Event | Every |
|---|---|
| `TIME_TICK` | the period |
| `TIME_TICK_1S` | second |
| `TIME_TICK_1M` | minute |
| `TIME_TICK_1H` | hour |

They stay at whole periods from the start: a late `tick()` posts each one
once and skips the missed ones; `restore()` counts them again. An event no
trigger names is not posted, so `ANY` and `UNKNOWN` do not see them. An hour
aligned to the clock (`hh:00`) is a `Clock` alarm, an interval the machine
starts and stops a `Timer`.

## Writing a component type

A component type is a subclass of `hsmd.Component` registered under the name
the declarations give as `type`. Only a type that raises events or needs the
dispatcher is worth a component: a counter or a list is plain Python.

```python
import hsmd


class Battery(hsmd.Component):
    """The charge level; LOW once when it falls under the threshold."""

    signals = {'LOW': ('level',)}
    variables = ('level',)

    def __init__(self, ident, dispatcher, **parameters):
        hsmd.Component.__init__(self, ident, dispatcher, **parameters)
        self.threshold = int(parameters.get('threshold', 20))
        self.level = 100

    def drain(self, amount):
        self.level = max(0, self.level - amount)
        if self.level < self.threshold:
            self.signal('LOW', level=self.level)

    def snapshot(self):
        return {'level': self.level}

    def restore(self, data):
        self.level = data['level']


hsmd.register('Battery', Battery)
```

```
CGML_COMPONENT battery          entry/                 battery.LOW/
type/ Battery                   battery.drain(7)       log.print('low', event.level)

threshold/ 20
```

| Member | Meaning |
|---|---|
| `Component(ident, dispatcher, **parameters)` | the constructor a type keeps; the parameters of the declaration arrive as strings |
| `id`, `dispatcher`, `parameters`, `machine` | the identifier, the dispatcher, the parameters, the identifier of the owning machine (`None` when shared) |
| `priority`, `shared` | the defaults of the type: the priority of its signals, the visibility |
| `signals` | signal -> the names of its parameters; `None` when not declared (the checks of the tools then accept any) |
| `variables` | the names the code reads |
| `signal(name, **parameters)` | raise the event `<id>.<name>` |
| `tick(now)` | called by `Dispatcher.tick()` with the clock; check the deadlines here |
| `snapshot()`, `restore(data)` | the data of the component in a snapshot; plain data |

The methods of the type are its public functions. A method runs inside a
step: it returns at once, and work that takes time is started by a method and
reported by a signal from `tick()`. `hsmd.describe(cls)` gives the declared
API: `{'methods': {name: [parameters]}, 'variables': [...], 'signals':
{...} or None}`. Register the type before the dispatcher loads the machines.

## Errors

| Error | When |
|---|---|
| `hsmd.DocumentError` | the document or the declarations break a rule, a component type is unknown, the code has a syntax error; raised by the constructor |
| `hsmd.ActionError` | the code fails at run time; `where` (the machine, the element, the block), `line` (of the block), `error` (the exception) |
| `hsmd.ExecutionError` | the machine cannot go on: a choice with no true branch, a composite state without an initial pseudostate entered by default |
| `hsmd.StoppedError` | a call to a stopped dispatcher |

They are subclasses of `hsmd.DispatcherError`. An error during a step
stops the dispatcher: the configuration may be half changed, so every call
raises `StoppedError` until `restore()`. A guard that fails is an error, not
a false guard.
