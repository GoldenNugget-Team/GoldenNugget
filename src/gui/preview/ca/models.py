"""Data model for Core Animation scenes parsed from .tendies CAML files.

Port of CAPlayground's ``lib/ca/types.ts`` layer unions flattened into one
dataclass with optional fields -- the parser keeps one shape per kind and the
renderer branches on ``Layer.type`` just like the TSX renderers do.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Dict, List, Optional


@dataclass
class Vec2:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class Size:
    w: float = 0.0
    h: float = 0.0


@dataclass
class GradientColor:
    color: str = "#000000"
    opacity: float = 1.0


@dataclass
class Filter:
    name: str = ""
    type: str = ""
    enabled: bool = True
    value: float = 0.0


@dataclass
class Animation:
    keyPath: str = ""
    values: List[Any] = field(default_factory=list)
    keyTimes: List[float] = field(default_factory=list)
    enabled: bool = True
    autoreverses: bool = False
    durationSeconds: float = 0.0
    infinite: bool = False
    repeatDurationSeconds: Optional[float] = None
    speed: Optional[float] = None
    calculationMode: str = "linear"
    timingFunction: str = "linear"


@dataclass
class EmitterCell:
    id: str = ""
    name: Optional[str] = None
    src: Optional[str] = None
    contentsScale: float = 1.0
    birthRate: float = 0.0
    lifetime: float = 0.0
    emissionLongitude: float = 0.0
    emissionRange: float = 0.0
    emissionLatitude: float = 0.0
    velocity: float = 0.0
    velocityRange: float = 0.0
    xAcceleration: float = 0.0
    yAcceleration: float = 0.0
    color: str = "#FFFFFF"
    alpha: float = 1.0
    red: float = 1.0
    green: float = 1.0
    blue: float = 1.0
    redRange: float = 0.0
    redSpeed: float = 0.0
    greenRange: float = 0.0
    greenSpeed: float = 0.0
    blueRange: float = 0.0
    blueSpeed: float = 0.0
    scale: float = 1.0
    scaleRange: float = 0.0
    scaleSpeed: float = 0.0
    alphaRange: float = 0.0
    alphaSpeed: float = 0.0
    spin: float = 0.0
    spinRange: float = 0.0


@dataclass
class Layer:
    id: str = ""
    name: str = ""
    type: str = "shape"  # image | text | gradient | emitter | transform | replicator | liquidGlass | video | shape
    position: Vec2 = field(default_factory=Vec2)
    zPosition: float = 0.0
    boundsOrigin: Vec2 = field(default_factory=Vec2)
    size: Size = field(default_factory=Size)
    opacity: float = 1.0
    cornerRadius: float = 0.0
    rotation: float = 0.0
    rotationX: float = 0.0
    rotationY: float = 0.0
    anchorPoint: Optional[Vec2] = None
    geometryFlipped: int = 0
    masksToBounds: int = 0
    scale: float = 1.0
    speed: Optional[float] = None
    blendMode: str = "normalBlendMode"
    filters: List[Filter] = field(default_factory=list)
    backgroundColor: Optional[str] = None
    backgroundOpacity: Optional[float] = None
    borderColor: Optional[str] = None
    borderWidth: Optional[float] = None
    visible: Optional[bool] = None

    # image
    src: Optional[str] = None
    # text
    text: Optional[str] = None
    fontFamily: Optional[str] = None
    fontSize: Optional[float] = None
    color: Optional[str] = None
    align: Optional[str] = None
    wrapped: Optional[int] = None
    # gradient
    gradientType: str = "axial"
    startPoint: Optional[Vec2] = None
    endPoint: Optional[Vec2] = None
    colors: List[GradientColor] = field(default_factory=list)
    # shape
    shape: Optional[str] = None
    fill: Optional[str] = None
    # video
    frameCount: int = 0
    fps: float = 30.0
    duration: Optional[float] = None
    autoReverses: bool = False
    framePrefix: Optional[str] = None
    frameExtension: Optional[str] = None
    syncWWithState: bool = False
    # emitter
    emitterPosition: Vec2 = field(default_factory=Vec2)
    emitterSize: Size = field(default_factory=Size)
    emitterShape: str = "point"
    emitterMode: str = "volume"
    renderMode: str = "unordered"
    emitterCells: List[EmitterCell] = field(default_factory=list)
    # replicator
    instanceCount: int = 1
    instanceDelay: float = 0.0
    instanceTranslation: Vec3 = field(default_factory=Vec3)
    instanceRotation: float = 0.0
    # transform
    perspective: Optional[float] = None

    children: List["Layer"] = field(default_factory=list)
    animations: List[Animation] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"<Layer {self.name!r} ({self.type}, {self.size.w:.0f}x{self.size.h:.0f})>"


@dataclass
class StateTransitionElement:
    targetId: str = ""
    keyPath: str = ""
    animationType: str = ""
    damping: Optional[float] = None
    mass: Optional[float] = None
    stiffness: Optional[float] = None
    velocity: Optional[float] = None
    duration: Optional[float] = None


@dataclass
class StateTransition:
    fromState: str = ""
    toState: str = ""
    elements: List[StateTransitionElement] = field(default_factory=list)


@dataclass
class ParallaxGroup:
    axis: str = "x"
    image: str = "null"
    keyPath: str = "position.x"
    layerName: str = ""
    mapMaxTo: float = 0.0
    mapMinTo: float = 0.0
    title: str = ""
    view: str = "Floating"


StateOverride = Dict[str, List[Dict[str, Any]]]


@dataclass
class CADocument:
    root: Optional[Layer] = None
    states: List[str] = field(default_factory=list)
    stateOverrides: StateOverride = field(default_factory=dict)
    stateTransitions: List[StateTransition] = field(default_factory=list)
    parallax: List[ParallaxGroup] = field(default_factory=list)
    assets: Mapping[str, bytes] = field(default_factory=dict)
    revision: int = field(default=0, compare=False)

    def touch(self):
        """Invalidate derived render data after an in-place edit."""
        self.revision += 1
        layers = [self.root] if self.root else []
        while layers:
            layer = layers.pop()
            for animation in layer.animations or ():
                animation.__dict__.pop('_prepared_track', None)
            layers.extend(layer.children)

    @contextmanager
    def edit(self):
        """Group mutable edits and invalidate all derived data on exit."""
        try:
            yield self
        finally:
            self.touch()


@dataclass
class TendieBundle:
    floating: Optional[CADocument] = None
    background: Optional[CADocument] = None
    wallpaper: Optional[CADocument] = None
    width: int = 390
    height: int = 844
    geometryFlipped: int = 0