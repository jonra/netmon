from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual.widget import Widget

# Braille dot layout (2 wide × 4 tall per character cell).
_DOT = (
    (0x01, 0x08),
    (0x02, 0x10),
    (0x04, 0x20),
    (0x40, 0x80),
)


@dataclass(frozen=True)
class Series:
    values: deque[float]
    color: str
    """Rich color name, e.g. red, cyan, green."""


def _resample(values: list[float], width: int) -> list[float]:
    if width <= 0:
        return []
    if not values:
        return [0.0] * width
    if len(values) == 1:
        return [values[0]] * width
    out: list[float] = []
    last = len(values) - 1
    for i in range(width):
        pos = i * last / (width - 1)
        lo = int(pos)
        hi = min(lo + 1, last)
        frac = pos - lo
        out.append(values[lo] * (1 - frac) + values[hi] * frac)
    return out


def _scale(value: float, y_max: float, height_px: int) -> int:
    if y_max <= 0:
        return 0
    clamped = max(0.0, min(value, y_max))
    return int(clamped / y_max * (height_px - 1))


class BraillePlot(Widget):
    """High-resolution plot using braille characters (2×4 dots per cell)."""

    DEFAULT_CSS = """
    BraillePlot {
        height: 1fr;
        width: 1fr;
        min-height: 5;
    }
    """

    def __init__(
        self,
        *,
        y_max: float = 100.0,
        stacked: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.y_max = y_max
        self.stacked = stacked
        self._series: list[Series] = []

    def set_series(self, series: list[Series]) -> None:
        self._series = series
        self.refresh()

    def render(self) -> RenderResult:
        width = self.size.width
        height = self.size.height
        if width <= 0 or height <= 0:
            return Text("")

        width_px = width * 2
        height_px = height * 4

        # Per braille cell: accumulated dots + style of topmost dot.
        bits = [[0] * width for _ in range(height)]
        styles: list[list[Style | None]] = [[None] * width for _ in range(height)]

        if self.stacked and len(self._series) >= 2:
            self._paint_stacked(bits, styles, width_px, height_px)
        else:
            self._paint_single(bits, styles, width_px, height_px)

        text = Text()
        for row in range(height):
            for col in range(width):
                ch = chr(0x2800 + bits[row][col])
                style = styles[row][col] or Style()
                text.append(ch, style)
            if row < height - 1:
                text.append("\n")
        return text

    def _paint_stacked(
        self,
        bits: list[list[int]],
        styles: list[list[Style | None]],
        width_px: int,
        height_px: int,
    ) -> None:
        """Stack series bottom-up (first series = base layer)."""
        cumulative: list[float] | None = None
        width = len(bits[0])

        for series in self._series:
            samples = _resample(list(series.values), width_px)
            if cumulative is None:
                base = [0.0] * width_px
            else:
                base = cumulative
            cumulative = [b + s for b, s in zip(base, samples)]
            color = series.color
            for px, top in enumerate(cumulative):
                bottom = base[px]
                y_top = _scale(top, self.y_max, height_px)
                y_bot = _scale(bottom, self.y_max, height_px)
                y_lo, y_hi = sorted((y_bot, y_top))
                for py in range(y_lo, y_hi + 1):
                    self._set_dot(bits, styles, px, py, color, width)

    def _paint_single(
        self,
        bits: list[list[int]],
        styles: list[list[Style | None]],
        width_px: int,
        height_px: int,
    ) -> None:
        width = len(bits[0])
        for series in self._series:
            samples = _resample(list(series.values), width_px)
            color = series.color
            for px, value in enumerate(samples):
                y = _scale(value, self.y_max, height_px)
                for py in range(y + 1):
                    self._set_dot(bits, styles, px, py, color, width)

    def _set_dot(
        self,
        bits: list[list[int]],
        styles: list[list[Style | None]],
        px: int,
        py: int,
        color: str,
        width: int,
    ) -> None:
        col, subx = divmod(px, 2)
        row, suby = divmod(py, 4)
        if col >= width or row >= len(bits):
            return
        bits[row][col] |= _DOT[suby][subx]
        styles[row][col] = Style(color=color)
