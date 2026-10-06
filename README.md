# The Python HSM Dispatcher

The run-time interpreter of the Cyberiada project that executes Hierarchical
State Machine diagrams stored in the CyberiadaML-GraphML format. The
dispatcher reads a diagram with the `CyberiadaML` binding, takes events from
the application and from the components, and runs the actions of the diagram
as Python code. It is written in pure Python 3 and generates no code.

The code is distributed under the Lesser GNU Public License (version 3), the
documentation -- under the GNU Free Documentation License (version 1.3).

## Documentation

The documentation is located in the `docs` directory and contains:

* The architecture - `ARCHITECTURE.md`: the usage requirements, the
  references to the standards PNST 984-2024 and PNST 1044-2025, the core
  specifications of the dispatcher

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
types are `Timer` and `Log`. A component is local to its machine or shared
by the machines of the document (`shared/ yes` in the declaration). The
modules are plain files: add the directory of the repository to the Python
path.

## Tests

    cd test
    python3 run.py            # compare with the good files
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
* libcyberiadamlpp-py (version 1.0.7+, the `CyberiadaML` module and its
  dependencies)
