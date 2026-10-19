# hsm-dispatcher-py project changelog

## Version 0.1.0

Added:
- the dispatcher of the CyberiadaML state machine diagrams: the reader over
  the `CyberiadaML` binding, the run-to-completion event queue ordered by
  the priority of the components, the hierarchy with the `actionFirst` and
  `exitFirst` orders, the `propagate` and `block` flags, the special events
  `ANY` and `UNKNOWN`, choice and completion transitions;
- the components: the base class, the registry, the local and shared
  visibility, the standard `Timer` (periodic or `once()`), `Log`, `Clock`
  (the local time and the `ALARM`) and `Console` (`LINE`, `EOF` from the
  input), exported by `hsmd`;
- the outcomes, the trace, the snapshot and the restore;
- the selection of the machines to run, the namespace of the application
  for the action text, the formal and informal comments kept for the
  application;
- the machine written in Python: the declarations (`Machine`, `State`, the
  pseudostates, `On`, `Transition`, `Declaration`), functions for the code,
  no `CyberiadaML` at run time (`hsmd_model`, `hsmd_build`);
- the declared API of the component types (`signals`, `variables`,
  `describe()`) and the time events of `tick()` with a period
  (`TIME_TICK`, `TIME_TICK_1S`, `TIME_TICK_1M`, `TIME_TICK_1H`);
- the scenario tests (30 scenarios, also run through the declarations with
  `--built`), the architecture document and the interface specification
  (`docs/API.md`, `docs/API-ru.md`);
- the pip installation and the Debian package; the `CyberiadaML` module from
  the binding or from the pure-Python interface of cyberiadaml-py 1.8
  (Python 3.8+), the package accepts either.
