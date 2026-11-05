"""Dancing to your music. Pure Python: no Qt, no Windows, so it's easy to test.

``BeatTracker`` listens to how loud the PC's sound is (a "peak meter" reading, 0..1, about
25 times a second) and finds the beats: a sudden jump above the recent average. From the gaps
between beats it guesses the tempo (BPM), and keeps a steady beat going between the loud ones.

``Groove`` is what her window asks while drawing: "how high is she bouncing right now (0..1),
and which way is she leaning (-1..1)?" With a tracker it follows the music; without one
(no sound reading on this PC) she just grooves at a comfy 110 BPM.
"""

from __future__ import annotations

import math
from collections import deque

DEFAULT_BPM = 110.0
MIN_BPM, MAX_BPM = 70.0, 180.0
SILENT = 0.02          # below this the music is paused (or very quiet)
SILENCE_STOP = 3.0     # seconds of silence before she stops dancing
ONSET_RATIO = 1.35     # a beat: this much louder than the recent average...
MIN_GAP = 0.28         # ...and not closer than this to the last one (max ~210 BPM)


class BeatTracker:
    def __init__(self):
        self.levels: deque[tuple[float, float]] = deque()  # (time, level), the last ~1.5 s
        self.onsets: deque[float] = deque(maxlen=16)
        self.bpm = DEFAULT_BPM
        self.anchor = 0.0  # a time a beat fell on (the beat grid is anchor + k * 60 / bpm)
        self.loud_at = -1e9  # the last time there was sound
        self.level = 0.0  # smoothed loudness (how big her moves are)

    def feed(self, now: float, level: float) -> bool:
        """A new loudness reading. True if it was a beat."""
        level = max(0.0, min(1.0, float(level)))
        self.level += (level - self.level) * 0.25
        if level > SILENT:
            self.loud_at = now
        while self.levels and now - self.levels[0][0] > 1.5:
            self.levels.popleft()
        average = sum(v for _, v in self.levels) / len(self.levels) if self.levels else 0.0
        self.levels.append((now, level))
        last = self.onsets[-1] if self.onsets else -1e9
        if level > SILENT * 2 and level > average * ONSET_RATIO and now - last >= MIN_GAP:
            self.onsets.append(now)
            self._retune(now)
            return True
        return False

    def _retune(self, now: float) -> None:
        gaps = [b - a for a, b in zip(self.onsets, list(self.onsets)[1:]) if 0.25 <= b - a <= 1.6]
        if len(gaps) >= 3:
            gaps.sort()
            beat = gaps[len(gaps) // 2]  # the median gap is one beat (or two: folded into range below)
            bpm = 60.0 / beat
            while bpm < MIN_BPM:
                bpm *= 2
            while bpm > MAX_BPM:
                bpm /= 2
            self.bpm += (bpm - self.bpm) * 0.5  # glide to the new tempo, no jumps
        self.anchor = now

    def playing(self, now: float) -> bool:
        return now - self.loud_at < SILENCE_STOP


class Groove:
    """Her dance moves at a moment in time."""

    def __init__(self, start: float, tracker: BeatTracker | None = None, bpm: float = DEFAULT_BPM):
        self.start = start
        self.tracker = tracker
        self.bpm = bpm

    def phase(self, now: float) -> float:
        """Where in the beat we are: 0.0 on the beat, going to 1.0 just before the next one."""
        if self.tracker is not None:
            bpm, anchor = self.tracker.bpm, self.tracker.anchor or self.start
        else:
            bpm, anchor = self.bpm, self.start
        return ((now - anchor) * bpm / 60.0) % 1.0

    def energy(self) -> float:
        """How big her moves are (0.35 .. 1)."""
        if self.tracker is None:
            return 0.7
        return 0.35 + 0.65 * min(1.0, self.tracker.level * 2.2)

    def pose(self, now: float) -> tuple[float, float]:
        """(bounce 0..1, lean -1..1). Down on the beat, up between; she leans left and right on alternate beats."""
        phase = self.phase(now)
        bounce = math.sin(math.pi * phase) ** 2 * self.energy()
        if self.tracker is not None:
            bpm, anchor = self.tracker.bpm, self.tracker.anchor or self.start
        else:
            bpm, anchor = self.bpm, self.start
        beats = (now - anchor) * bpm / 60.0
        lean = math.sin(math.pi * beats) * self.energy()  # one full sway every two beats
        return bounce, lean
