"""Visual direction contract: what must change on screen, kept intact from plan to pixels.

Layers (each depends only on the ones above it):

- ``contract``   meaning — model types, operations, validation, timeline
                 compilation, state replay. Pure: no files, no runtime.
- ``timeline``   loading the compiled visual_timeline and checking it is executable.
- ``binding``    implementation trace per runtime: which authored code executes
                 each contract event (``remotion_source``, ``hyperframes``).
- ``guards``     render-time refusal when the contract would be lost.
- ``hooks``      the public entry points. Everything outside this package
                 imports from ``hooks``; core files reach it only through the
                 fork seams ``lib/compose_hooks.py`` and ``lib/checkpoint_hooks.py``.

Topic-agnostic: meaning (ids, labels, palette) lives in each project's
visual_direction, never here.
"""
