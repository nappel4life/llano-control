"""Fan curves: piecewise linear interpolation with a drop delay.

The vendor application interpolates linearly between breakpoints and rounds
the result, which is reproduced here. On top of that, a speed is lowered only
after the temperature has fallen by ``hysteresis`` degrees below the point
that caused the increase, so the fan does not pump up and down around a
breakpoint.
"""

from __future__ import annotations


def interpolate(curve: list[list[float]], temp: float) -> int:
    """Return the fan speed for ``temp`` from ``[[deg, percent], ...]``."""
    points = sorted(((float(a), float(b)) for a, b in curve), key=lambda p: p[0])
    if not points:
        raise ValueError("curve is empty")
    if temp <= points[0][0]:
        return _clamp(points[0][1])
    if temp >= points[-1][0]:
        return _clamp(points[-1][1])
    for (t0, s0), (t1, s1) in zip(points, points[1:]):
        if t0 <= temp < t1:
            if t1 == t0:
                return _clamp(s0)
            return _clamp(s0 + (temp - t0) / (t1 - t0) * (s1 - s0))
    return _clamp(points[-1][1])


def _clamp(speed: float) -> int:
    return max(1, min(100, int(round(speed))))


class CurveFollower:
    """Turns a stream of temperatures into a stream of fan speeds."""

    def __init__(self, curve: list[list[float]], hysteresis: float = 3.0):
        self.curve = curve
        self.hysteresis = float(hysteresis)
        self.applied: int | None = None
        self.anchor: float | None = None

    def update(self, temp: float) -> int:
        """Return the speed to apply now for this temperature reading."""
        target = interpolate(self.curve, temp)
        if self.applied is None or self.anchor is None:
            self.applied, self.anchor = target, temp
        elif target > self.applied:
            # Louder is allowed immediately.
            self.applied, self.anchor = target, temp
        elif temp <= self.anchor - self.hysteresis:
            # Only now may the fan slow down again.
            self.applied, self.anchor = target, temp
        return self.applied

    def reset(self) -> None:
        self.applied = None
        self.anchor = None
