"""Atelier doctrine: which imports from the stock Remotion registry a bespoke project may use.

A bespoke (atelier) composition must hand-author its look. Importing a stock
creative component (``src/components``, ``src/Explainer`` …) is reuse and fails
the render; engine knowledge (``remotion``, ``@remotion/*``, project-local files,
the ``src/direction`` contract runtime) is fine. A short allow-list of shared
infrastructure modules carries no look of its own and may be imported by exact
path. Used by ``VideoCompose._run_atelier_checks``.
"""

from __future__ import annotations

import re

# Stock-registry modules that violate the atelier doctrine. Any import of
# these from a bespoke project means a creative component was reused
# instead of hand-stitched. Engine knowledge (the `remotion` package,
# `@remotion/*`, project-local files, the src/direction contract runtime)
# is fine.
STOCK_MODULE_RE = (
    r"^src/(?:components|Explainer|CinematicRenderer|TitledVideo|TalkingHead|"
    r"CollageBurst|LyricOverlay|cinematic|crucix|phantom)(?:/|$|\.)"
)
# Shared infrastructure that lives among the stock components but carries
# no look of its own. Exact module paths only (no barrels, no wildcards):
# importing `src/components` as a whole still counts as stock reuse.
SHARED_INFRA_MODULES = frozenset({
    "src/components/PhraseCaptions",  # shared narration caption renderer (subtitles.style="karaoke")
})
IMPORT_SPEC_RE = r"""(?:\bfrom\s+|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)["']([^"']+)["']"""


def classify_import(spec: str) -> str | None:
    """'stock', 'shared_infra' or None (not a stock-registry path)."""
    path = spec.replace("\\", "/")
    path = re.sub(r"^(?:\./|\.\./)+", "", path)
    idx = path.find("remotion-composer/")
    if idx >= 0:
        path = path[idx + len("remotion-composer/"):]
    if not re.match(STOCK_MODULE_RE, path):
        return None
    module = re.sub(r"\.(?:tsx|ts|jsx|js)$", "", path)
    module = re.sub(r"/index$", "", module)
    return "shared_infra" if module in SHARED_INFRA_MODULES else "stock"
