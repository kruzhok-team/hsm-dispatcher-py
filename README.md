# The Python HSM Dispatcher

The run-time interpreter of the Cyberiada project that executes Hierarchical
State Machine diagrams stored in the CyberiadaML-GraphML format. The
dispatcher reads a diagram with the `CyberiadaML` module, takes events from
the application and from the components, and runs the actions of the diagram
as Python code. It is written in pure Python 3 and generates no code.

The code is distributed under the Lesser GNU Public License (version 3), the
documentation -- under the GNU Free Documentation License (version 1.3).

## Documentation

The documentation is located in the `docs` directory and contains:

* The interface - `API.md` (`API-ru.md` in Russian): for the authors of the
  programs, the diagrams and the component types - the `Dispatcher`, the code
  of a diagram, a machine written in Python, the standard components, the
  time events, a component type of one's own, the errors
* The architecture - `ARCHITECTURE.md`: the usage requirements, the
  references to the standards PNST 984-2024 and PNST 1044-2025, the core
  specifications of the dispatcher

## Installation

The dispatcher needs the `CyberiadaML` module: the binding of
`libcyberiadamlpp-py` with its libraries (`libhtreegeom`, `libcyberiadaml`,
`libcyberiadamlpp`), each installed by its own README, or, when it is not
installed, the pure-Python interface of `cyberiadaml-py` 1.8+; check the
binding with `python3 -c "import CyberiadaML"`.

The Debian package:

    cmake -B build && cd build && ctest && cpack -G DEB
    sudo apt install ./python3-hsm-dispatcher_0.1.0_all.deb

`ctest` runs the scenario tests with the Python CMake finds
(`-DPython3_EXECUTABLE=...` selects another one). The package depends on
`python3-libcyberiadamlpp`.

With pip (a virtual environment, the user site, Windows, macOS) the
dispatcher needs no binary build: pip installs cyberiadaml-py with it, and the
dispatcher uses the binding only when it is installed:

    python3 -m venv --system-site-packages venv && . venv/bin/activate
    pip install /path/to/hsm-dispatcher-py

`--system-site-packages` lets the environment see an installed `CyberiadaML`
module; for a module that is built but not installed, write the build
directory into a `.pth` file of the environment instead:

    echo /path/to/libcyberiadamlpp-py/build > "$(python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")/cyberiadaml.pth"

Check with `python3 -c "import hsmd"`. The modules are plain files, so the
directory of the repository on the Python path works as well.

## Usage

```python
import hsmd

class Lamp(hsmd.Component):          # a component type of the application
    def on(self):
        ...

hsmd.register('Lamp', Lamp)

dispatcher = hsmd.Dispatcher('blinker.graphml')
dispatcher.start()
outcome = dispatcher.send('button.PRESSED', long=True)
print(outcome.status, dispatcher.states())
dispatcher.tick()                    # call it regularly: the timers
```

The diagram declares its components with `CGML_COMPONENT <id>` comments and
calls them from the action text, which is Python. The standard component
types, exported by `hsmd`, are `Timer` (periodic, or `once()`), `Log`,
`Clock` (the local time, `alarm(9)` raises `ALARM` every day at 09:00) and
`Console` (`LINE` for every line of the input, then `EOF`); a type declares
its `signals` and `variables`, and `hsmd.describe(cls)` gives them with the
methods. `calendar=` and `input=` give the clocks and the consoles their
time and their stream. With a period
(`Dispatcher(..., period=0.1)`), `tick()` posts the time events the
machines use: `TIME_TICK` every period, `TIME_TICK_1S`, `TIME_TICK_1M` and
`TIME_TICK_1H`. A component is local to its machine or shared
by the machines of the document (`shared/ yes` in the declaration). A
program may run a part of the machines (`machines=[...]`) and give the text
its own namespace (`namespace=globals()`).

A machine may be written in Python instead: the code is functions, the
structure a tree of declarations, and neither the diagram file nor
`CyberiadaML` is needed to run it (hsm-to-python generates such programs):

```python
def go_guard():
    return event.speed > 3


machine = hsmd.Machine('Robot', states=[
    hsmd.Initial(id='init'),
    hsmd.State('Idle', entry="log.print('idle')"),
    hsmd.State('Work'),
], transitions=[
    hsmd.Transition('init', 'Idle'),
    hsmd.Transition('Idle', 'Work', 'GO', guard=go_guard),
], components=[
    hsmd.Declaration('log', 'Log'),
])

dispatcher = hsmd.Dispatcher(machine, namespace=globals())
```

## Tests

    cd test
    python3 run.py            # compare with the good files
    python3 run.py --built    # the same, every document rebuilt from declarations
    python3 run.py --regen    # record the good files again

Each test is a diagram from `test/graphs`, a scenario from `test/scripts`
and the expected trace in `test/good`. The diagrams are checked with the
validator of `cyberiadaml-compat-tests` when that repository is found beside
this one. Where the installed `CyberiadaML` module is older than 1.0.7,
point the environment to a current build:

    export PYTHONPATH=../../libcyberiadamlpp-py/build
    export LD_LIBRARY_PATH=<the directory of libcyberiadamlpp and libcyberiadaml>

`pylint.sh` runs the linter over the sources.

## Requirements

* python3 (version 3.8+)
* the `CyberiadaML` module: libcyberiadamlpp-py (version 1.0.7+, with its
  dependencies) or, when it is not installed, cyberiadaml-py (version 1.8+),
  its pure-Python interface
* cmake (version 3.16+) - for the Debian package
