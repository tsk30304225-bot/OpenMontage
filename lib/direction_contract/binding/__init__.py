"""Implementation binding: map each contract event to the runtime code that executes it.

One module per runtime. Each returns a trace whose ``hard_failures`` list the
contract events the authored code does not implement.

- ``remotion_source`` — bespoke (atelier) Remotion source, via the
  ``remotion-composer/src/direction`` runtime calls
- ``hyperframes`` — HyperFrames scene workspaces, via ``OM.at("<event id>")``
"""
