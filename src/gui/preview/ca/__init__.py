"""Core Animation scene parsing + rendering ported from CAPlayground.

Right now GoldenNugget uses this to reconstruct richer lock-screen previews
from the ``.tendies`` CAML scenes (vs. the bitmap fallback in
:mod:`src.gui.preview.tendie_preview`) with animations played back from a
timeline. The heavy lifting lives in:

* :mod:`.caml`      -- XML -> layer tree + states/overrides/transitions/parallax
* :mod:`.tendie`    -- ``.tendies`` zip -> :class:`CADocument` bundles + assets
* :mod:`.animate`   -- keyframe animation evaluation at a given time
* :mod:`.render`    -- QPainter scene renderer (port of the TSX renderers)
"""

from .caml import (  # noqa: F401
    parse_ca_document,
    parse_caml,
    parse_state_overrides,
    parse_state_transitions,
    parse_states,
    parse_wallpaper_parallax_groups,
)
from .models import (
    Animation,
    CADocument,
    EmitterCell,
    Filter,
    GradientColor,
    Layer,
    ParallaxGroup,
    Size,
    StateTransition,
    TendieBundle,
    Vec2,
    Vec3,
)
from .render import (  # noqa: F401
    CAMLRenderer,
    SceneCompositeRenderer,
    appearance_variant_state,
    bundle_has_appearance_variants,
    document_loop_duration,
    home_state,
    preview_renderer,
    state_transition_spec,
)
from .tendie import load_tendie, preferred_scene  # noqa: F401

__all__ = [
    "CADocument",
    "Animation",
    "EmitterCell",
    "Filter",
    "GradientColor",
    "Layer",
    "ParallaxGroup",
    "Size",
    "StateTransition",
    "TendieBundle",
    "Vec2",
    "Vec3",
    "parse_ca_document",
    "parse_caml",
    "parse_state_overrides",
    "parse_state_transitions",
    "parse_states",
    "parse_wallpaper_parallax_groups",
    "load_tendie",
    "preferred_scene",
    "CAMLRenderer",
    "SceneCompositeRenderer",
    "appearance_variant_state",
    "bundle_has_appearance_variants",
    "document_loop_duration",
    "home_state",
    "preview_renderer",
    "state_transition_spec",
]