"""The floating character window.

It only knows how to *show* things: which picture, where, how it moves. What
she feels is decided by brain.py; the controller in app.py connects the two.

Things that make her feel alive:
    * breathing:      a tiny up-and-down stretch, slower while sleeping
    * blinking:       every few seconds (if the pack has a blink picture)
    * crossfade:      expressions blend into each other instead of popping
    * hop / land:     little jumps when happy, a squash when she lands
    * swing:          she dangles and swings while you drag her around
    * gravity:        drop her in mid-air and she falls to the taskbar; fling her and she flies
    * wander:         now and then she hops along the taskbar to a new spot
    * zzz:            floating letters while she sleeps
"""

from __future__ import annotations

import logging
import math
import random
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QWidget

from .character import CharacterPack
from .settings import SIZES

log = logging.getLogger(__name__)

FADE_SECONDS = 0.18
HOP_SECONDS, HOP_HEIGHT = 0.42, 0.075  # height as a fraction of her height
LAND_SECONDS = 0.40
SHAKE_SECONDS = 0.45
BREATH = (3.4, 0.010)  # (period in s, depth)
SLEEP_BREATH = (4.8, 0.017)
MAX_SWING_DEG = 10.0
FAST_MS, CALM_MS = 33, 66  # ~30 fps while something moves, ~15 fps otherwise

BLINK_SECONDS = 0.13
BLINK_GAP = (2.4, 6.0)  # seconds between blinks
DOUBLE_BLINK_CHANCE = 0.18

# Physics, in logical pixels and seconds (scaled with her size where it matters).
GRAVITY = 3200.0
MAX_FALL_SPEED = 2600.0
MAX_TOSS = 2200.0
AIR_DRAG = 1.1
WALL_BOUNCE = 0.45
FLOOR_BOUNCE = 0.2
BOUNCE_MIN_SPEED = 1300.0
HOLD_STILL_FADE = 3.8  # per second: throw speed fades while you hold her still
WALK_SPEED = 75.0  # at medium size; hop-walk when the pack has no walk pictures
STEP_SPEED = 110.0  # with real walk pictures (matches their stride at 4.5 fps)
WALK_HOP_SECONDS, WALK_HOP_HEIGHT = 0.34, 0.022
WANDER_DISTANCE = (120.0, 380.0)  # at medium size


# ------------------------------------------------------------------------ images
def load_frames(pack: CharacterPack) -> dict[str, list[QImage]]:
    """Decode every PNG of the pack. Broken files are skipped (and logged)."""
    frames: dict[str, list[QImage]] = {}
    for name, animation in pack.animations.items():
        images = []
        for path in animation.frames:
            reader = QImageReader(str(path))
            image = reader.read()
            if image.isNull():
                log.error("Could not load %s: %s", path, reader.errorString())
                continue
            images.append(image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
        if images:
            frames[name] = images
    if "idle" not in frames:
        log.error("No usable idle image for %s; showing a placeholder", pack.name)
        frames["idle"] = [placeholder_image()]
    return frames


def placeholder_image() -> QImage:
    """A simple stand-in so DeskMate still runs if the character images are missing."""
    image = QImage(420, 600, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor("#3B2F4A")
    p.setPen(QPen(ink, 8))
    p.setBrush(QColor("#E9D8F5"))
    p.drawRoundedRect(QRectF(120, 380, 180, 200), 70, 70)
    p.drawEllipse(QRectF(60, 90, 300, 300))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ink)
    p.drawEllipse(QRectF(140, 220, 34, 46))
    p.drawEllipse(QRectF(246, 220, 34, 46))
    p.setBrush(QColor("#F4A6C0"))
    p.drawEllipse(QRectF(112, 280, 40, 22))
    p.drawEllipse(QRectF(268, 280, 40, 22))
    p.setPen(QPen(ink, 7, cap=Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(184, 270, 52, 36), 200 * 16, 140 * 16)
    p.end()
    return image


def _smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value)) if low <= high else low


# ------------------------------------------------------------------------ window
class Companion(QWidget):
    clicked = Signal()
    dragStarted = Signal()
    dragEnded = Signal()
    landed = Signal(float)  # impact speed (px/s); 0 when simply put down
    hoverChanged = Signal(bool)
    menuRequested = Signal(QPoint)
    moved = Signal()

    def __init__(self, pack: CharacterPack, frames: dict[str, list[QImage]], size: str = "medium",
                 on_top: bool = True, clock=time.monotonic, rng: random.Random | None = None,
                 gravity: bool = True):
        super().__init__(None, self._flags(on_top))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle(f"DeskMate - {pack.name}")

        self._clock = clock
        self._rng = rng or random.Random()
        self._t0 = clock()
        self._size = size if size in SIZES else "medium"
        self._load_pack(pack, frames)
        self._cache: dict[tuple[str, int, bool], QPixmap] = {}
        self._cache_dpr = 0.0

        self._requested = "idle"  # what the brain asked for
        self._expr = "idle"  # what is actually shown
        self._expr_started = self._t0
        self._prev: tuple[str, int, bool] | None = None
        self._fade_start = -1.0
        self._sleeping = False
        self._effects: dict[str, float] = {}
        self._next_blink = self._t0 + self._rng.uniform(*BLINK_GAP)
        self._blink_until = -1.0

        self._armed = False
        self._dragging = False
        self._press_global = QPoint()
        self._press_pos = QPoint()
        self._press_local = QPointF()
        self._pivot = QPointF(0, 0)  # swing pivot, relative to her feet
        self._vx = 0.0  # drag speed, px/s
        self._vy = 0.0
        self._last_sample: tuple[float, int, int] | None = None
        self._swing = 0.0
        self._swing_speed = 0.0
        self._last_frame = self._t0
        self._hover = False
        self._settle_anim: QPropertyAnimation | None = None
        self._screen_hooked = None

        self._gravity = gravity
        self._falling = False
        self._fall_vx = self._fall_vy = 0.0
        self._fall_impact = 0.0
        self._fx = self._fy = 0.0  # precise window position while moving by itself
        self._walk: tuple[float, float] | None = None  # (target x, start time)
        self._facing = 1

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_frame)
        self._apply_size(keep_feet=False)

    # ------------------------------------------------------------ setup bits
    def _load_pack(self, pack: CharacterPack, frames: dict[str, list[QImage]]) -> None:
        self.pack = pack
        self._frames = frames
        reference = frames["idle"][0]
        self._ref_w, self._ref_h = reference.width(), reference.height()
        self._accent = QColor(pack.theme.get("accent", "#C9A0DC")).darker(135)
        self._pixel_art = pack.meta.get("smooth") is False  # keep pixel art crisp
        self.setWindowTitle(f"DeskMate - {pack.name}")

    def set_pack(self, pack: CharacterPack, frames: dict[str, list[QImage]]) -> None:
        """Swap to another character, keeping her feet where they are."""
        feet = self.feet_global()
        self._load_pack(pack, frames)
        self._expr, self._prev, self._effects = "idle", None, {}
        self._blink_until = -1.0
        self._expr_started = self._clock()
        self._apply_size(keep_feet=False)
        self.move(self.clamped_pos(feet - self._feet_local().toPoint()))
        self.play("hop")

    @staticmethod
    def _flags(on_top: bool) -> Qt.WindowType:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.NoDropShadowWindowHint
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def _apply_size(self, keep_feet: bool = True) -> None:
        old_feet = self.feet_global() if keep_feet else None
        self._H = float(SIZES[self._size])
        self._scale = self._H / self._ref_h
        self._W = self._ref_w * self._scale
        self._side = math.ceil(self._W * 0.15)
        self._top = math.ceil(self._H * 0.17)
        self._bottom = math.ceil(self._H * 0.03)
        self.setFixedSize(math.ceil(self._W) + 2 * self._side, math.ceil(self._H) + self._top + self._bottom)
        self._cache.clear()
        if old_feet is not None:
            self.move(old_feet - self._feet_local().toPoint())
        self.update()

    # -------------------------------------------------------------- geometry
    def _feet_local(self) -> QPointF:
        return QPointF(self.width() / 2.0, self._top + self._H)

    def feet_global(self) -> QPoint:
        return self.pos() + self._feet_local().toPoint()

    def _sprite_rect_local(self) -> QRect:
        feet = self._feet_local()
        return QRect(int(feet.x() - self._W / 2), int(feet.y() - self._H), math.ceil(self._W), math.ceil(self._H))

    def _head_local(self) -> QRectF:
        hx, hy, top = self.pack.head
        feet = self._feet_local()
        left, upper = feet.x() - self._W / 2, feet.y() - self._H
        cx, cy, ty = left + hx * self._W, upper + hy * self._H, upper + top * self._H
        radius = max(10.0, cy - ty)
        return QRectF(cx - radius, ty, 2 * radius, 2 * radius)

    def head_rect_global(self) -> QRect:
        rect = self._head_local()
        return QRect(self.mapToGlobal(rect.topLeft().toPoint()), rect.size().toSize())

    def screen_for(self, point: QPoint):
        screen = QGuiApplication.screenAt(point)
        if screen is not None:
            return screen
        best, best_distance = None, None
        for candidate in QGuiApplication.screens():
            g = candidate.availableGeometry()
            dx = max(g.left() - point.x(), 0, point.x() - g.right())
            dy = max(g.top() - point.y(), 0, point.y() - g.bottom())
            distance = dx * dx + dy * dy
            if best_distance is None or distance < best_distance:
                best, best_distance = candidate, distance
        return best or QGuiApplication.primaryScreen()

    def available_rect(self) -> QRect:
        screen = self.screen_for(self.head_rect_global().center())
        return screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    def _ground_rect(self, pos: QPoint | None = None) -> QRect:
        """Usable area (above the taskbar) of the screen under her feet."""
        pos = self.pos() if pos is None else pos
        screen = self.screen_for(pos + self._feet_local().toPoint())
        return screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    def _limits(self, avail: QRect) -> tuple[float, float, float, float]:
        """Allowed window x/y range so her whole body stays inside ``avail``."""
        sprite = self._sprite_rect_local()
        return (
            avail.left() - sprite.left(),
            avail.right() + 1 - (sprite.left() + sprite.width()),
            avail.top() - sprite.top(),
            avail.bottom() + 1 - (sprite.top() + sprite.height()),
        )

    def clamped_pos(self, pos: QPoint) -> QPoint:
        """Keep her whole body on a screen, standing above the taskbar."""
        sprite = self._sprite_rect_local()
        screen = self.screen_for(pos + sprite.center())
        if screen is None:
            return pos
        min_x, max_x, min_y, max_y = self._limits(screen.availableGeometry())
        return QPoint(int(_clamp(pos.x(), min_x, max_x)), int(_clamp(pos.y(), min_y, max_y)))

    def floor_y(self, pos: QPoint | None = None) -> int:
        """Window y at which her feet stand on the taskbar."""
        return int(self._limits(self._ground_rect(pos))[3])

    def on_floor(self) -> bool:
        return abs(self.pos().y() - self.floor_y()) <= 2

    def default_pos(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        feet = QPoint(int(avail.right() - 36 - self._W / 2), avail.bottom())
        return self.clamped_pos(feet - self._feet_local().toPoint())

    def place(self, saved: list | None) -> None:
        if saved:
            self.move(self.clamped_pos(QPoint(int(saved[0]), int(saved[1]))))
        else:
            self.move(self.default_pos())

    # ------------------------------------------------------------ public API
    def set_size(self, size: str) -> None:
        if size in SIZES and size != self._size:
            self._size = size
            self._apply_size(keep_feet=True)
            self.move(self.clamped_pos(self.pos()))
            self.settle()

    def set_on_top(self, on_top: bool) -> None:
        pos, visible = self.pos(), self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)  # this hides the window
        self.move(pos)
        if visible:
            self.show()

    def set_gravity(self, on: bool) -> None:
        self._gravity = bool(on)
        if self._gravity:
            self.settle()
        else:
            self._falling = False
            self._walk = None

    @property
    def gravity(self) -> bool:
        return self._gravity

    @property
    def falling(self) -> bool:
        return self._falling

    @property
    def walking(self) -> bool:
        return self._walk is not None

    def set_expression(self, name: str) -> None:
        self._requested = name
        self._sleeping = name == "sleep"
        self._show(self._effective())

    @property
    def expression(self) -> str:
        return self._expr

    def play(self, effect: str) -> None:
        if effect == "wander":
            self.start_wander()
        elif effect in ("hop", "land", "shake"):
            self._effects[effect] = self._clock()
            self._kick()

    def reset_position(self) -> None:
        self._stop_moving()
        self._animate_to(self.default_pos())

    def settle(self) -> None:
        """With gravity on, fall to the floor if she's floating in mid-air."""
        if self._gravity and self.isVisible() and not self._dragging and not self.on_floor():
            self._start_fall(0.0, 0.0)

    def start_wander(self, target_x: float | None = None) -> bool:
        """Hop along the taskbar to a new spot. Returns False if now isn't a good time."""
        if (not self._gravity or self._dragging or self._falling or self._walk is not None
                or not self.isVisible() or not self.on_floor()):
            return False
        min_x, max_x, _min_y, _max_y = self._limits(self._ground_rect())
        x = float(self.pos().x())
        if target_x is None:
            size = self._H / SIZES["medium"]
            distance = self._rng.uniform(*WANDER_DISTANCE) * size
            direction = self._rng.choice((-1, 1))
            if not (min_x + 8 <= x + direction * distance <= max_x - 8):
                direction = -direction
            target_x = x + direction * distance
        target_x = _clamp(target_x, min_x + 8, max_x - 8)
        if abs(target_x - x) < 20:
            return False
        self._fx, self._fy = x, float(self.pos().y())
        self._walk = (target_x, self._clock())
        self._facing = 1 if target_x > x else -1
        self._kick()
        return True

    # -------------------------------------------------------------- animation
    def _kick(self) -> None:
        if self.isVisible():
            self._timer.setInterval(FAST_MS)
            if not self._timer.isActive():
                self._timer.start()
            self.update()

    def _effective(self) -> str:
        """The animation to show: her pose (dragged/falling/walking) beats her mood."""
        if self._dragging and "drag" in self._frames:
            return "drag"
        if self._falling and "fall" in self._frames:
            return "fall"
        if self._walk is not None and "walk" in self._frames:
            return "walk"
        animation = self.pack.resolve(self._requested)
        return animation if animation in self._frames else "idle"

    def _mirrored(self, animation: str) -> bool:
        return animation == "walk" and self._facing < 0  # walk frames face right

    def _show(self, animation: str) -> None:
        if animation == self._expr:
            return
        now = self._clock()
        self._prev = (self._expr, self._frame_index(self._expr, now), self._mirrored(self._expr))
        self._expr = animation
        self._expr_started = now
        self._fade_start = now
        self._blink_until = -1.0
        self._kick()

    def _progress(self, name: str, now: float, seconds: float) -> float | None:
        start = self._effects.get(name)
        if start is None:
            return None
        t = (now - start) / seconds
        if t >= 1.0:
            del self._effects[name]
            return None
        return max(0.0, t)

    def _frame_index(self, animation: str, now: float) -> int:
        frames = self._frames.get(animation) or self._frames["idle"]
        if len(frames) == 1:
            return 0
        meta = self.pack.animations.get(animation)
        fps = meta.fps if meta else 6.0
        loop = meta.loop if meta else True
        step = int((now - self._expr_started) * fps)
        return step % len(frames) if loop else min(step, len(frames) - 1)

    def showing_blink(self, now: float | None = None) -> bool:
        now = self._clock() if now is None else now
        return self._expr == "idle" and self._prev is None and now < self._blink_until and "blink" in self._frames

    def _update_blink(self, now: float) -> None:
        if "blink" not in self._frames or self._expr != "idle" or self._prev is not None:
            return
        if self._dragging or self._falling or now < self._next_blink:
            return
        self._blink_until = now + BLINK_SECONDS
        if self._rng.random() < DOUBLE_BLINK_CHANCE:
            self._next_blink = now + BLINK_SECONDS + 0.18
        else:
            self._next_blink = now + self._rng.uniform(*BLINK_GAP)

    def _busy(self, now: float) -> bool:
        return (
            self._dragging
            or self._falling
            or self._walk is not None
            or bool(self._effects)
            or self._prev is not None
            or now < self._blink_until + 0.05
            or abs(self._swing) > 0.05
            or abs(self._swing_speed) > 0.5
            or len(self._frames.get(self._expr, ())) > 1
        )

    def _on_frame(self) -> None:
        now = self._clock()
        dt = min(0.1, max(0.0, now - self._last_frame))
        self._last_frame = now
        # Swing like a pendulum while dragged, wobble back to rest afterwards.
        target = _clamp(-self._vx * 0.018, -MAX_SWING_DEG, MAX_SWING_DEG) if self._dragging else 0.0
        self._swing_speed += (140.0 * (target - self._swing) - 11.0 * self._swing_speed) * dt
        self._swing += self._swing_speed * dt
        if not self._dragging and abs(self._swing) < 0.02 and abs(self._swing_speed) < 0.2:
            self._swing = self._swing_speed = 0.0
        if self._dragging:
            fade = math.exp(-HOLD_STILL_FADE * dt)  # forget old speed if the mouse stops (same at any fps)
            self._vx *= fade
            self._vy *= fade
        if self._falling:
            self._fall_step(dt, now)
        elif self._walk is not None:
            self._walk_step(dt, now)
        self._show(self._effective())
        self._update_blink(now)
        self._timer.setInterval(FAST_MS if self._busy(now) else CALM_MS)
        self.update()

    # --------------------------------------------------------------- physics
    def _start_fall(self, vx: float, vy: float) -> None:
        self._walk = None
        if self._settle_anim is not None:
            self._settle_anim.stop()
        self._fx, self._fy = float(self.pos().x()), float(self.pos().y())
        self._fall_vx = _clamp(vx, -MAX_TOSS, MAX_TOSS)
        self._fall_vy = _clamp(vy, -MAX_TOSS, MAX_FALL_SPEED)
        self._fall_impact = 0.0
        self._falling = True
        self._last_frame = self._clock()
        self._kick()

    def _fall_step(self, dt: float, now: float) -> None:
        self._fall_vy = min(MAX_FALL_SPEED, self._fall_vy + GRAVITY * dt)
        self._fall_vx *= math.exp(-AIR_DRAG * dt)
        self._fx += self._fall_vx * dt
        self._fy += self._fall_vy * dt
        min_x, max_x, min_y, floor = self._limits(self._ground_rect(QPoint(int(self._fx), int(self._fy))))
        if self._fx < min_x:
            self._fx, self._fall_vx = min_x, abs(self._fall_vx) * WALL_BOUNCE
        elif self._fx > max_x:
            self._fx, self._fall_vx = max_x, -abs(self._fall_vx) * WALL_BOUNCE
        if self._fy < min_y:
            self._fy, self._fall_vy = min_y, abs(self._fall_vy) * 0.3
        if self._fy >= floor:
            self._fy = floor
            impact = self._fall_vy
            if not self._fall_impact:
                self._fall_impact = impact
            self._effects["land"] = now
            if impact > BOUNCE_MIN_SPEED:
                self._fall_vy = -impact * FLOOR_BOUNCE  # one little bounce on a hard landing
            else:
                self._falling = False
                self._fall_vx = self._fall_vy = 0.0
                self.move(QPoint(int(round(self._fx)), int(round(self._fy))))
                self.landed.emit(float(self._fall_impact))
                return
        self.move(QPoint(int(round(self._fx)), int(round(self._fy))))

    def _walk_step(self, dt: float, now: float) -> None:
        target, _start = self._walk
        speed = (STEP_SPEED if "walk" in self._frames else WALK_SPEED) * self._H / SIZES["medium"]
        remaining = target - self._fx
        if abs(remaining) <= speed * dt:
            self._fx = target
            self._walk = None
            self._effects["land"] = now
        else:
            self._fx += math.copysign(speed * dt, remaining)
        self.move(QPoint(int(round(self._fx)), self.floor_y()))

    def _stop_moving(self) -> None:
        self._falling = False
        self._walk = None
        self._fall_vx = self._fall_vy = 0.0

    def _body_transform(self, now: float) -> tuple[float, float, float, float]:
        sx = sy = 1.0
        dx = dy = 0.0
        period, depth = SLEEP_BREATH if self._sleeping else BREATH
        breath = math.sin(2 * math.pi * (now - self._t0) / period)
        if self._pixel_art:
            # Stretching pixel art makes it shimmer; a classic little bob looks right instead.
            dy -= max(1, round(self._H * 0.012)) if breath > 0 else 0
        else:
            sy *= 1 + depth * breath
            sx *= 1 - depth * 0.4 * breath
        if self._walk is not None and "walk" not in self._frames:  # no legs to walk with: hop along
            phase = ((now - self._walk[1]) / WALK_HOP_SECONDS) % 1.0
            dy -= self._H * WALK_HOP_HEIGHT * math.sin(math.pi * phase)
        t = self._progress("hop", now, HOP_SECONDS)
        if t is not None:
            dy -= self._H * HOP_HEIGHT * 4 * t * (1 - t)
            sy *= 1 + 0.03 * math.sin(math.pi * t)
        t = self._progress("land", now, LAND_SECONDS)
        if t is not None:
            wobble = math.exp(-5 * t) * math.cos(3.2 * math.pi * t)
            sy *= 1 - 0.07 * wobble
            sx *= 1 + 0.05 * wobble
        t = self._progress("shake", now, SHAKE_SECONDS)
        if t is not None:
            dx += math.sin(t * math.pi * 8) * self._W * 0.025 * (1 - t)
        return sx, sy, dx, dy

    # ------------------------------------------------------------- painting
    def _pixmap(self, animation: str, index: int, mirrored: bool = False) -> QPixmap:
        dpr = self.devicePixelRatioF() or 1.0
        if dpr != self._cache_dpr:
            self._cache.clear()
            self._cache_dpr = dpr
        key = (animation, index, mirrored)
        pixmap = self._cache.get(key)
        if pixmap is None:
            image = self._frames[animation][index]
            if mirrored:
                image = image.transformed(QTransform().scale(-1, 1))
            factor = self._scale * dpr
            target = QSize(max(1, round(image.width() * factor)), max(1, round(image.height() * factor)))
            mode = (Qt.TransformationMode.FastTransformation if self._pixel_art
                    else Qt.TransformationMode.SmoothTransformation)
            scaled = image.scaled(target, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
            pixmap = QPixmap.fromImage(scaled)
            pixmap.setDevicePixelRatio(dpr)
            self._cache[key] = pixmap
        return pixmap

    def _current_pixmap(self, now: float) -> QPixmap:
        if self.showing_blink(now):
            return self._pixmap("blink", 0)
        current = self._pixmap(self._expr, self._frame_index(self._expr, now), self._mirrored(self._expr))
        if self._prev is None:
            return current
        k = (now - self._fade_start) / FADE_SECONDS
        previous_key = self._prev
        if k >= 1.0 or previous_key[0] not in self._frames:
            self._prev = None
            return current
        previous = self._pixmap(*previous_key)
        if previous.size() != current.size():
            self._prev = None
            return current
        # A true cross-dissolve: (1-k)*old + k*new, alpha included.
        k = _smoothstep(k)
        blend = QImage(current.size(), QImage.Format.Format_ARGB32_Premultiplied)
        blend.setDevicePixelRatio(current.devicePixelRatio())
        blend.fill(Qt.GlobalColor.transparent)
        painter = QPainter(blend)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setOpacity(1.0 - k)
        painter.drawPixmap(0, 0, previous)
        painter.setOpacity(k)
        painter.drawPixmap(0, 0, current)
        painter.end()
        return QPixmap.fromImage(blend)

    def paintEvent(self, _event) -> None:
        now = self._clock()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not self._pixel_art)
        feet = self._feet_local()
        sx, sy, dx, dy = self._body_transform(now)

        if not self._dragging and not self._falling:  # a soft shadow grounds her on the desktop
            lift = min(1.0, -dy / max(1.0, self._H * HOP_HEIGHT))
            width = self._W * 0.46 * (1 - 0.3 * lift)
            height = self._H * 0.045 * (1 - 0.3 * lift)
            gradient = QRadialGradient(feet, width / 2)
            gradient.setColorAt(0.0, QColor(30, 15, 45, int(70 * (1 - 0.5 * lift))))
            gradient.setColorAt(1.0, QColor(30, 15, 45, 0))
            painter.save()
            painter.translate(feet)
            painter.scale(1.0, height / width)
            painter.translate(-feet)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(feet, width / 2, width / 2)
            painter.restore()

        painter.save()
        painter.translate(feet.x() + dx, feet.y() + dy)
        if self._swing:
            painter.translate(self._pivot)
            painter.rotate(self._swing)
            painter.translate(-self._pivot)
        painter.scale(sx, sy)
        pixmap = self._current_pixmap(now)
        dpr = pixmap.devicePixelRatio() or 1.0
        painter.drawPixmap(QPointF(-pixmap.width() / dpr / 2, -pixmap.height() / dpr), pixmap)
        painter.restore()

        if self._sleeping:
            self._draw_zzz(painter, now)
        painter.end()

    def _draw_zzz(self, painter: QPainter, now: float) -> None:
        head = self._head_local()
        font = QFont(self.font())
        font.setBold(True)
        outline = QPen(QColor(255, 255, 255, 230), max(2.0, self._H * 0.009))
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for i in range(3):
            phase = ((now - self._t0) * 0.32 + i / 3.0) % 1.0
            font.setPixelSize(max(9, int(self._H * (0.05 + 0.04 * phase))))
            x = head.right() - head.width() * 0.14 + self._W * 0.10 * phase + math.sin(phase * 6.0) * 3
            y = head.top() + head.height() * 0.12 - self._H * 0.13 * phase
            path = QPainterPath()
            path.addText(QPointF(x, y), font, "z")
            painter.setOpacity(math.sin(math.pi * phase))
            painter.strokePath(path, outline)
            painter.fillPath(path, self._accent)
        painter.setOpacity(1.0)

    # ---------------------------------------------------------------- mouse
    def _opaque_at(self, local: QPointF) -> bool:
        """Is there actually part of her under this point (not a transparent corner)?"""
        frames = self._frames.get(self._expr) or self._frames["idle"]
        image = frames[min(self._frame_index(self._expr, self._clock()), len(frames) - 1)]
        feet = self._feet_local()
        x = (local.x() - feet.x()) / self._scale + image.width() / 2
        y = (local.y() - feet.y()) / self._scale + image.height()
        if self._mirrored(self._expr):
            x = image.width() - 1 - x
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return False
        return image.pixelColor(int(x), int(y)).alpha() > 40

    def mousePressEvent(self, event) -> None:
        button = event.button()
        if button == Qt.MouseButton.RightButton:
            self.menuRequested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if button != Qt.MouseButton.LeftButton or not self._opaque_at(event.position()):
            event.ignore()
            return
        if self._settle_anim is not None:
            self._settle_anim.stop()
        if self._falling or self._walk is not None:
            self._stop_moving()  # catch her mid-air / stop her walk
        self._armed = True
        self._press_global = event.globalPosition().toPoint()
        self._press_pos = self.pos()
        self._press_local = event.position()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.mousePressEvent(event)  # a double-click is just two pets

    def mouseMoveEvent(self, event) -> None:
        if self._armed and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_global
            if not self._dragging and delta.manhattanLength() >= QGuiApplication.styleHints().startDragDistance():
                self._dragging = True
                self._pivot = self._press_local - self._feet_local()
                self._vx = self._vy = 0.0
                self._last_sample = None
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.dragStarted.emit()
                self._kick()
            if self._dragging:
                self.move(self._press_pos + delta)
                self._sample_speed(event.globalPosition().toPoint())
            event.accept()
            return
        if self._opaque_at(event.position()):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def _sample_speed(self, point: QPoint) -> None:
        now = self._clock()
        if self._last_sample is not None:
            elapsed = now - self._last_sample[0]
            if elapsed > 0.004:
                self._vx = 0.6 * self._vx + 0.4 * (point.x() - self._last_sample[1]) / elapsed
                self._vy = 0.6 * self._vy + 0.4 * (point.y() - self._last_sample[2]) / elapsed
                self._last_sample = (now, point.x(), point.y())
        else:
            self._last_sample = (now, point.x(), point.y())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self._dragging = False
            self._last_sample = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.dragEnded.emit()
            self._drop()
        elif self._armed:
            self.clicked.emit()
        self._armed = False
        event.accept()

    def _drop(self) -> None:
        """Let go of her: fall (with gravity), or stay where she was put."""
        if self._gravity:
            if self.on_floor() and abs(self._vx) < 300 and abs(self._vy) < 300:
                self.move(self.clamped_pos(self.pos()))
                self.play("land")
                self.landed.emit(0.0)
            else:
                self._start_fall(self._vx * 0.9, self._vy * 0.6)
        else:
            target = self.clamped_pos(self.pos())
            if target != self.pos():
                self._animate_to(target)
            self.play("land")
            self.landed.emit(0.0)
        self._kick()

    def _animate_to(self, target: QPoint) -> None:
        if self._settle_anim is not None:
            self._settle_anim.stop()
        animation = QPropertyAnimation(self, b"pos", self)
        animation.setDuration(260)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(self.pos())
        animation.setEndValue(target)
        animation.start()
        self._settle_anim = animation

    def enterEvent(self, event) -> None:
        if not self._hover:
            self._hover = True
            self.hoverChanged.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover:
            self._hover = False
            self.hoverChanged.emit(False)
        self.unsetCursor()
        super().leaveEvent(event)

    # -------------------------------------------------------------- lifecycle
    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.moved.emit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._last_frame = self._clock()
        self._timer.start(CALM_MS)
        handle = self.windowHandle()
        if handle is not None and handle is not self._screen_hooked:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_hooked = handle

    def hideEvent(self, event) -> None:
        self._timer.stop()
        self._stop_moving()
        super().hideEvent(event)

    def _on_screen_changed(self, *_args) -> None:
        self._cache.clear()  # different scaling on the new monitor: re-render crisp images
        self.update()
