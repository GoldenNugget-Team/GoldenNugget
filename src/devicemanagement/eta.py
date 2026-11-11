"""Estimate the remaining time of a percentage-based backup/restore.

The device progress callbacks report a monotonically increasing percentage
(0..100) with no notion of time. ``ProgressEta`` watches that percentage over
wall-clock time and turns it into a short human-readable estimate for the
UI. It is intentionally stateful and cheap: feed every numeric progress value
to :meth:`update` and it returns the formatted remaining time (or ``""`` until
a stable rate is known).
"""

import math
import time

from PySide6.QtCore import QCoreApplication


class ProgressEta:
    """Turn a 0..100 progress stream into a remaining-time estimate.

    The rate is measured over a sliding window of recent samples so an
    estimate stays responsive when a fresh phase runs at a different speed,
    using a fitted trend rather than a single pair of progress callbacks.
    A progress value that drops (a retry/restart) resets the estimator.
    """

    def __init__(self, window_seconds: float = 30.0,
                 min_elapsed: float = 2.0, min_delta: float = 0.25):
        self._window_seconds = window_seconds
        self._min_elapsed = min_elapsed
        self._min_delta = min_delta
        self._samples: list[tuple[float, float]] = []
        self._start: float | None = None
        self._last_pct: float | None = None

    def reset(self) -> None:
        """Forget all samples — call before a new operation."""
        self._samples = []
        self._start = None
        self._last_pct = None

    def update(self, percent) -> str:
        """Feed the latest percentage; return a readable estimate or ""."""
        if isinstance(percent, bool):
            return ""
        try:
            pct = float(percent)
        except (TypeError, ValueError):
            return ""
        if not math.isfinite(pct):
            return ""
        if pct < 0 or pct > 100:
            return ""
        now = time.monotonic()
        if pct == 0:
            if self._last_pct is None or self._last_pct > 0:
                self.reset()
                self._start = now
                self._samples.append((now, 0.0))
                self._last_pct = 0.0
            return ""
        if pct == 100:
            self.reset()
            return ""
        # A lower value means the operation (re)started — start over.
        if self._last_pct is not None and pct + 0.01 < self._last_pct:
            self.reset()
        # A gap longer than the window is a phase boundary (a reboot wait, a
        # user unlock prompt) where no progress is measurable; restart the
        # measurement rather than extrapolate across the dead time.
        if self._samples and now - self._samples[-1][0] > self._window_seconds:
            self._samples = []
            self._start = now
        if self._start is None:
            self._start = now
        self._last_pct = pct
        self._samples.append((now, pct))
        cutoff = now - self._window_seconds
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.pop(0)
        return _format_duration(self._estimate(now, pct))

    def _estimate(self, now: float, pct: float) -> float | None:
        if self._start is None or now - self._start < self._min_elapsed:
            return None
        t0, p0 = self._samples[0]
        dt = now - t0
        dp = pct - p0
        if dt < self._min_elapsed or dp < self._min_delta:
            return None
        mean_time = sum(t - t0 for t, _ in self._samples) / len(self._samples)
        mean_pct = sum(p for _, p in self._samples) / len(self._samples)
        variance = sum((t - t0 - mean_time) ** 2 for t, _ in self._samples)
        if variance <= 0:
            return None
        rate = sum((t - t0 - mean_time) * (p - mean_pct)
                   for t, p in self._samples) / variance
        if rate <= 0:
            return None
        return (100.0 - pct) / rate



def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(round(seconds)))
    parts = []
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        parts.append(QCoreApplication.translate("Nugget", "{0} hour" if hours == 1 else "{0} hours").format(hours))
    if minutes:
        parts.append(QCoreApplication.translate("Nugget", "{0} minute" if minutes == 1 else "{0} minutes").format(minutes))
    if secs or not parts:
        parts.append(QCoreApplication.translate("Nugget", "{0} second" if secs == 1 else "{0} seconds").format(secs))
    return " ".join(parts)
