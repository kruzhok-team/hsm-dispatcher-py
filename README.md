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

* The architecture - `ARCHITECTURE.md`

The detailed specification of the interpreter and the code follow the
architecture and are not written yet.

## Requirements

* python3 (version 3.8+)
* libcyberiadamlpp-py (version 1.0.7+, the `CyberiadaML` module and its
  dependencies)
