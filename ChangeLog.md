# hsm-dispatcher-py project changelog

## Version 0.1.0 (unreleased)

Added:
- the dispatcher of the CyberiadaML state machine diagrams: the reader over
  the `CyberiadaML` binding, the run-to-completion event queue ordered by
  the priority of the components, the hierarchy with the `actionFirst` and
  `exitFirst` orders, the `propagate` and `block` flags, the special events
  `ANY` and `UNKNOWN`, choice and completion transitions;
- the stage 2 elements: shallow and deep history, deferred events, entry and
  exit points, submachine states inlined from the same or from another
  document, terminate;
- the components: the base class, the registry, the local and shared
  visibility, the standard `Timer` and `Log`;
- the outcomes, the trace, the snapshot and the restore;
- the selection of the machines to run, the namespace of the application
  for the action text, the formal and informal comments kept for the
  application;
- the scenario tests (24 scenarios) and the architecture document;
- the pip installation and the Debian package.
