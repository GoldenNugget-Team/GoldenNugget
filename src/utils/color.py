"""Pure RGBA colour value used by the template model.

Template options used to carry ``QColor`` values and touched Qt from the
backend. The model now stores :class:`RgbColor`; the Qt editor converts to and
from ``QColor`` at the boundary. Component values mirror ``QColor`` exactly:
``red``/``green``/``blue`` are ints 0-255, ``alpha``/``alphaF`` are 0-255 /
0.0-1.0.
"""

from __future__ import annotations

from dataclasses import dataclass


def _clamp_int(value: float, high: int) -> int:
    return max(0, min(high, int(round(value))))


@dataclass(frozen=True)
class RgbColor:
    red: int = 0
    green: int = 0
    blue: int = 0
    alpha: int = 255

    @classmethod
    def from_floats(cls, red: float, green: float, blue: float, alpha: float = 1.0) -> "RgbColor":
        return cls(
            _clamp_int(red * 255, 255),
            _clamp_int(green * 255, 255),
            _clamp_int(blue * 255, 255),
            _clamp_int(alpha * 255, 255),
        )

    @classmethod
    def from_hex(cls, text: str) -> "RgbColor":
        raw = str(text).strip().lstrip("#")
        if len(raw) == 8:
            red, green, blue, alpha = (int(raw[i:i + 2], 16) for i in range(0, 8, 2))
        elif len(raw) == 6:
            red, green, blue = (int(raw[i:i + 2], 16) for i in range(0, 6, 2))
            alpha = 255
        elif len(raw) == 3:
            red, green, blue = (int(ch * 2, 16) for ch in raw)
            alpha = 255
        else:
            raise ValueError(f"invalid colour: {text!r}")
        return cls(red, green, blue, alpha)

    # QColor-compatible accessors -----------------------------------------
    def redF(self) -> float:  # noqa: N802
        return self.red / 255.0

    def greenF(self) -> float:  # noqa: N802
        return self.green / 255.0

    def blueF(self) -> float:  # noqa: N802
        return self.blue / 255.0

    def alphaF(self) -> float:  # noqa: N802
        return self.alpha / 255.0

    def name(self) -> str:
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"

    def css(self, prefix: str = "rgba") -> str:
        return (f"{prefix}({self.red}, {self.green}, {self.blue}, "
                f"{self.alphaF():.3f})")

    def __iter__(self):
        return iter((self.red, self.green, self.blue, self.alpha))
