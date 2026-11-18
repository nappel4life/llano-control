"""Native surface for the llano V12 Ultra, with a tray icon.

PyQt6 only. The control loop runs in a worker thread and pushes its status
into the window through a signal, so temperature polling (including the
nvidia-smi call) never blocks the interface. All writes go through the
Controller, whose lock keeps the loop and the widgets from writing at the
same time.
"""

from __future__ import annotations

import logging
import math
import os
import signal
import sys
import time

from PyQt6.QtCore import (
    QRectF, QPointF, Qt, QSocketNotifier, QThread, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QActionGroup, QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox, QComboBox,
    QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy,    QSpinBox, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QToolButton,
    QVBoxLayout, QWidget,
)

from . import config as config_mod
from .curve import interpolate
from .loop import AlreadyRunning, Controller
from .protocol import COLORS, EFFECTS, EFFECT_SPEEDS

APP_NAME = "llano-control"
WINDOW_TITLE = "llano V12 Ultra"

# Derselbe Logger wie die Steuerung: ein Fenster, das sich nicht zeigt, soll
# im Terminal sagen koennen, wie weit es gekommen ist.
log = logging.getLogger("llano")

# Screen colours for the five pad colours, in pad order.
COLOR_SWATCH = {
    0: "#ff3b30",   # rot
    1: "#3fc6ff",   # hellblau
    2: "#39d353",   # gruen
    3: "#a855f7",   # lila
    4: "#ff9500",   # orange
}


# --------------------------------------------------------------------- theme

STYLE = """
QWidget { color: #e6edf3; }
QMainWindow, QDialog { background: #14181e; }
QGroupBox {
    border: 1px solid #262d38; border-radius: 10px;
    margin-top: 12px; padding: 10px 10px 8px; background: #171d25;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: #8b98a9; font-weight: 600;
}
QPushButton {
    background: #1d2530; border: 1px solid #2a3441;
    border-radius: 8px; padding: 6px 12px;
}
QPushButton:hover { border-color: #3a4757; }
QPushButton:checked { background: #34d3a6; border-color: #34d3a6; color: #06241c; font-weight: 600; }
QPushButton:disabled { color: #66707d; border-color: #222a34; }
QLineEdit, QTableWidget {
    background: #0f141a; border: 1px solid #2a3441; border-radius: 6px;
    selection-background-color: #1d7d64;
}
/* Zahlenfelder bleiben aus dieser Regel draußen: Rand, Rundung oder Polster per
   Stylesheet ziehen bei Qt das Textfeld in einer Spinbox auf ein Pixel
   zusammen, das Feld steht dann leer da. Ohne Regel zeichnet Qt sie selbst. */
QHeaderView::section { background: #171d25; color: #8b98a9; border: 0; padding: 4px; }
QTableCornerButton::section { background: #171d25; border: 0; }
QComboBox {
    background: #1d2530; border: 1px solid #2a3441; border-radius: 8px;
    padding: 5px 10px;
}
QComboBox:hover { border-color: #34d3a6; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox QAbstractItemView {
    background: #171d25; border: 1px solid #2a3441; border-radius: 8px;
    selection-background-color: #1d7d64; outline: 0;
}
QToolButton {
    background: #1d2530; border: 1px solid #2a3441; border-radius: 7px;
    color: #e6edf3; font-weight: 600;
}
QToolButton:hover { border-color: #34d3a6; }
QToolButton:pressed { background: #16202a; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #3a4757; background: #0f141a;
}
QCheckBox::indicator:checked { background: #34d3a6; border-color: #34d3a6; }
QCheckBox::indicator:hover { border-color: #34d3a6; }
QStatusBar { background: #11161b; color: #8b98a9; }
QMenu { background: #171d25; border: 1px solid #2a3441; }
QMenu::item { padding: 5px 22px 5px 14px; }
QMenu::item:selected { background: #1d7d64; }
QMenu::separator { height: 1px; background: #262d38; margin: 5px 8px; }
QMenu::item:disabled { color: #66707d; }
QToolTip { background: #1d2530; color: #e6edf3; border: 1px solid #3a4757; }
"""


def apply_theme(app: QApplication) -> None:
    """A dark, desktop-independent look.

    Without this the window inherits whatever Breeze theme the user picked,
    and the muted labels were chosen against a dark background.
    """
    from PyQt6.QtGui import QPalette

    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        "Window": "#14181e", "Base": "#0f141a", "AlternateBase": "#171d25",
        "Text": "#e6edf3", "WindowText": "#e6edf3", "Button": "#1d2530",
        "ButtonText": "#e6edf3", "ToolTipBase": "#1d2530", "ToolTipText": "#e6edf3",
        "PlaceholderText": "#7d8898", "BrightText": "#ff8080",
        "Light": "#222b36", "Midlight": "#1d2530", "Dark": "#0c1015", "Mid": "#2a3441",
        "Shadow": "#000000",
    }
    for name, colour in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, name), QColor(colour))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1d7d64"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#eafff8"))
    disabled = QColor("#66707d")
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


# --------------------------------------------------------------------- icons

def make_icon(accent: str = "#34d3a6", size: int = 64, spinning: bool = False) -> QIcon:
    """Draw the tray/taskbar icon instead of shipping an image file."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = max(1, int(size * 0.06))
    body = pixmap.rect().adjusted(margin, margin, -margin, -margin)
    painter.setPen(QPen(QColor("#2b3542"), max(1, int(size * 0.05))))
    painter.setBrush(QBrush(QColor("#151b23")))
    painter.drawRoundedRect(QRectF(body), size * 0.22, size * 0.22)

    hub = body.center()
    radius = int(min(body.width(), body.height()) * 0.30)
    painter.setPen(QPen(QColor(accent), max(1.0, size * 0.055), Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(hub, radius, radius)

    for index in range(3):
        angle = 120 * index + (30 if spinning else 0)
        path = QPainterPath()
        path.moveTo(QPointF(hub))
        direction = angle * 3.141592653589793 / 180.0
        tip_x = hub.x() + radius * 0.92 * math.cos(direction)
        tip_y = hub.y() + radius * 0.92 * math.sin(direction)
        control_x = hub.x() + radius * 0.55 * math.cos(direction + 0.9)
        control_y = hub.y() + radius * 0.55 * math.sin(direction + 0.9)
        path.quadTo(control_x, control_y, tip_x, tip_y)
        painter.drawPath(path)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(accent)))
    painter.drawEllipse(hub, int(size * 0.07), int(size * 0.07))
    painter.end()
    return QIcon(pixmap)


# --------------------------------------------------------------------- worker

class Worker(QThread):
    """Runs the control loop and reports every cycle."""

    updated = pyqtSignal(dict)
    problem = pyqtSignal(str)

    def __init__(self, controller: Controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._running = True

    def run(self):  # noqa: D102
        while self._running:
            try:
                status = self.controller.poll()
            except Exception as exc:  # keep the loop alive
                self.problem.emit(str(exc))
                status = None
            if status is not None:
                self.updated.emit(status)
            self._pause(max(0.5, float(self.controller.cfg["poll_seconds"])))

    def _pause(self, seconds: float) -> None:
        """Wait between polls, and stop waiting when the program is closing.

        A sleeping thread cannot be rushed, and at logout every second of that
        sleep is a second in which the pad is still waiting to be switched off.
        """
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            self.msleep(100)

    def stop(self):
        self._running = False
        self.wait(4000)


# ------------------------------------------------------------------ curve view

class CurveWidget(QWidget):
    """Die Lüfterkurve: ansehen und mit der Maus anfassen.

    Punkte lassen sich ziehen, ein Doppelklick legt einen Punkt an, ein
    Rechtsklick entfernt ihn. Während des Ziehens geht das Signal mit
    ``final=False`` weg, damit nicht bei jedem Pixel Konfiguration geschrieben
    und der Lüfter verstellt wird; erst beim Loslassen wird gespeichert.
    """

    points_changed = pyqtSignal(list, bool)

    LEFT, TOP, RIGHT, BOTTOM = 34, 10, 12, 24
    T_MIN, T_MAX = 30.0, 100.0
    GRAB = 12
    MAX_POINTS = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: list[list[float]] = []
        self.temp: float | None = None
        self._drag: int | None = None
        self.setMinimumHeight(180)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("Punkt ziehen · Doppelklick = Punkt hinzufügen · Rechtsklick = entfernen")

    def set_data(self, points: list[list[float]], temp: float | None) -> None:
        # While a point is being dragged the widget owns the list.
        if self._drag is None:
            self.points = points
        self.temp = temp
        self.update()

    def snapshot(self, sort: bool = False) -> list[list]:
        points = [[float(point[0]), int(point[1])] for point in self.points]
        if sort:
            points.sort(key=lambda point: point[0])
        return points

    # ------------------------------------------------------------- coordinates

    def _area(self) -> QRectF:
        box = self.rect()
        return QRectF(self.LEFT, self.TOP,
                      max(20.0, box.width() - self.LEFT - self.RIGHT),
                      max(20.0, box.height() - self.TOP - self.BOTTOM))

    def _x(self, temp: float) -> float:
        area = self._area()
        clipped = max(self.T_MIN, min(self.T_MAX, float(temp)))
        return area.left() + (clipped - self.T_MIN) / (self.T_MAX - self.T_MIN) * area.width()

    def _y(self, speed: float) -> float:
        area = self._area()
        return area.bottom() - max(0.0, min(100.0, float(speed))) / 100.0 * area.height()

    def _temp_at(self, pixel_x: float) -> float:
        area = self._area()
        return self.T_MIN + (pixel_x - area.left()) / area.width() * (self.T_MAX - self.T_MIN)

    def _speed_at(self, pixel_y: float) -> float:
        area = self._area()
        return (area.bottom() - pixel_y) / area.height() * 100.0

    def _nearest(self, position) -> int | None:
        best, best_distance = None, self.GRAB * self.GRAB
        for index, point in enumerate(self.points):
            dx = self._x(point[0]) - position.x()
            dy = self._y(point[1]) - position.y()
            distance = dx * dx + dy * dy
            if distance <= best_distance:
                best, best_distance = index, distance
        return best

    # ------------------------------------------------------------------ editing

    def add_point(self, temp: float, speed: float) -> None:
        if len(self.points) >= self.MAX_POINTS:
            return
        self.points.append([float(round(max(self.T_MIN, min(self.T_MAX, temp)))),
                            int(round(max(1, min(100, speed))))])
        self.points.sort(key=lambda point: point[0])
        self.update()
        self.points_changed.emit(self.snapshot(sort=True), True)

    def remove_point(self, index: int) -> None:
        if len(self.points) <= 2 or index is None or index >= len(self.points):
            return
        del self.points[index]
        self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        self.points_changed.emit(self.snapshot(sort=True), True)

    # -------------------------------------------------------------------- mouse

    def mousePressEvent(self, event):  # noqa: N802
        index = self._nearest(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and index is not None:
            self._drag = index
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.remove_point(index)
            event.accept()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position()
            self.add_point(self._temp_at(position.x()), self._speed_at(position.y()))
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        position = event.position()
        if self._drag is None:
            over_point = self._nearest(position.toPoint()) is not None
            self.setCursor(Qt.CursorShape.PointingHandCursor if over_point
                           else Qt.CursorShape.ArrowCursor)
            return
        index = self._drag
        if index >= len(self.points):
            self._drag = None
            return
        self.points[index][0] = float(round(max(self.T_MIN, min(self.T_MAX,
                                                                self._temp_at(position.x())))))
        self.points[index][1] = int(round(max(1, min(100, self._speed_at(position.y())))))
        self.update()
        self.points_changed.emit(self.snapshot(), False)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag is None:
            return
        self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        self.points_changed.emit(self.snapshot(sort=True), True)
        event.accept()

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        if area.width() < 40 or area.height() < 40:
            return
        x, y = self._x, self._y

        font = QFont(self.font())
        font.setPointSize(max(7, font.pointSize() - 2))
        painter.setFont(font)

        for percent in (0, 25, 50, 75, 100):
            painter.setPen(QPen(QColor("#242e3a")))
            painter.drawLine(int(area.left()), int(y(percent)), int(area.right()), int(y(percent)))
            painter.setPen(QColor("#6b7889"))
            painter.drawText(_rect(area.left() - 32, y(percent) - 8, 28, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{percent}%")
        for temp in (40, 50, 60, 70, 80, 90, 100):
            painter.setPen(QPen(QColor("#1c242e")))
            painter.drawLine(int(x(temp)), int(area.top()), int(x(temp)), int(area.bottom()))
            painter.setPen(QColor("#6b7889"))
            painter.drawText(_rect(x(temp) - 14, area.bottom() + 4, 28, 14),
                             Qt.AlignmentFlag.AlignHCenter, str(temp))

        ordered = sorted(self.points, key=lambda point: point[0])
        if len(ordered) >= 2:
            path = QPainterPath()
            path.moveTo(QPointF(x(ordered[0][0]), y(ordered[0][1])))
            for point in ordered[1:]:
                path.lineTo(QPointF(x(point[0]), y(point[1])))
            painter.setPen(QPen(QColor("#34d3a6"), 2.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        if self.temp is not None:
            painter.setPen(QPen(QColor("#f0a640"), 1.2, Qt.PenStyle.DashLine))
            painter.drawLine(int(x(self.temp)), int(area.top()),
                             int(x(self.temp)), int(area.bottom()))
            if len(ordered) >= 2:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#f0a640")))
                painter.drawEllipse(_point(x(self.temp), y(interpolate(ordered, self.temp))), 5, 5)

        for index, point in enumerate(self.points):
            active = index == self._drag
            painter.setPen(QPen(QColor("#0e1116"), 1.5))
            painter.setBrush(QBrush(QColor("#7ff0cd") if active else QColor("#34d3a6")))
            painter.drawEllipse(_point(x(point[0]), y(point[1])), 6 if active else 4,
                                6 if active else 4)

        if self._drag is not None and self._drag < len(self.points):
            point = self.points[self._drag]
            label = f"{point[0]:.0f} °C  ·  {point[1]:.0f} %"
            box = _rect(x(point[0]) + 10, y(point[1]) - 26, 108, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#0e1116")))
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(QColor("#e6edf3"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)


def _rect(x: float, y: float, w: float, h: float) -> QRectF:
    return QRectF(x, y, w, h)


def _point(x: float, y: float) -> QPointF:
    return QPointF(x, y)


# ------------------------------------------------------------------ pick widgets

class ColorDots(QWidget):
    """Die fünf Farben des Kühlers als kleine Kreise.

    Es sind fünf Kreise und kein freies Farbfeld, weil das Gerät nichts mischt:
    am Kühler nachgemessen rechnet die Firmware jedes andere Farbbyte auf eine
    dieser fünf Farben zurück, und auch die Windows-Software bietet genau diese
    fünf an. Ein freies Rad würde Farben zeigen, die der Kühler nicht kann.
    """

    picked = pyqtSignal(int)

    SIZE = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buttons: dict[int, QToolButton] = {}
        self.active = 2
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        for value, name in sorted(COLORS.items()):
            button = QToolButton(self)
            button.setCheckable(True)
            button.setFixedSize(self.SIZE, self.SIZE)
            button.setToolTip(name)
            button.setAccessibleName(f"Farbe {name}")
            button.clicked.connect(lambda _=False, colour=value: self.picked.emit(colour))
            layout.addWidget(button)
            self.buttons[value] = button
        layout.addStretch(1)
        self._draw()

    def set_active(self, value: int) -> None:
        self.active = int(value)
        self._draw()

    def _draw(self) -> None:
        radius = self.SIZE // 2
        for value, button in self.buttons.items():
            chosen = value == self.active
            button.setChecked(chosen)
            button.setStyleSheet(
                f"QToolButton {{ background:{COLOR_SWATCH[value]};"
                f" border:2px solid {'#e6edf3' if chosen else '#0e1116'};"
                f" border-radius:{radius}px; }}"
                " QToolButton:hover { border:2px solid #34d3a6; }"
            )


class PickBox(QComboBox):
    """Ausklappliste für nummerierte Choices wie Effekt und Effekttakt.

    Reagiert wird auf `activated`, nicht auf `currentIndexChanged`: beim
    Nachziehen des Gerätezustands würde die Liste sonst sofort zurückschreiben,
    was der Kühler gerade meldet.
    """

    def __init__(self, table: dict[int, str], on_pick, field: str, parent=None):
        super().__init__(parent)
        self._on_pick = on_pick
        self._field = field
        for value, name in sorted(table.items()):
            self.addItem(name, value)
        self.activated.connect(self._chosen)

    def _chosen(self, _index: int) -> None:
        self.pick(self.currentData())

    def pick(self, value) -> None:
        """Einen Wert setzen, als hätte ihn jemand ausgewählt."""
        if value is not None:
            self._on_pick(**{self._field: int(value)})

    def set_active(self, value: int) -> None:
        index = self.findData(int(value))
        if index >= 0 and index != self.currentIndex():
            self.setCurrentIndex(index)


def stepper(spin: QAbstractSpinBox, unit: str = "") -> QWidget:
    """Zahlenfeld mit Plus und Minus daneben.

    Die eingebauten Qt-Pfeile sind kaum 16 Pixel hoch und auf einem Notebook
    nebeneinander kaum zu treffen. Zwei richtige Knöpfe neben dem Feld zeigen
    dasselbe und sind erreichbar; eintippen kann man weiterhin.
    """
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    wrap = QWidget()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    step = spin.singleStep()
    how = f"{step:g} {unit}".strip()
    minus, plus = QToolButton(wrap), QToolButton(wrap)
    minus.setText("−")
    plus.setText("+")
    for button, label, move in ((minus, f"um {how} kleiner", spin.stepDown),
                                (plus, f"um {how} groesser", spin.stepUp)):
        button.setFixedSize(28, 28)
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.clicked.connect(lambda _=False, turn=move: turn())
    row.addWidget(spin, 1)
    row.addWidget(minus)
    row.addWidget(plus)
    wrap.minus = minus
    wrap.plus = plus
    return wrap


class PaintedBar(QWidget):
    """Balken zum Ziehen, eigens gemalt -- senkrecht wie waagerecht.

    Ein QSlider war der kürzere Weg, aber Qt zeichnet hinter jedem gestylten
    Slider seine eigene Nut weiter: sie reicht über die ganze Breite des Widgets
    und bleibt stehen, egal ob man Rand, Seiten oder Griff umdefiniert (an den
    Pixeln nachgemessen, nicht am Gefühl). Also hier wie bei der Kurve: selbst
    gemalt, mit Maus, Mausrad und Tastatur.

    Die senkrechte Richtung ist so gemeint, wie man sie liest: 0 unten, der
    Anschlag oben. Die waagerechte läuft von links nach rechts. Ein abgeschalteter
    Balken malt in Grau und lässt sich nicht anfassen -- im Automatikmodus zeigt
    er bloß mit, was die Kurve gerade will.
    """

    valueChanged = pyqtSignal(int)
    editingFinished = pyqtSignal()

    THICK = 26          # Platz in Querrichtung: hier muss der Griff hineinpassen
    TRACK = 12
    KNOB = 11

    def __init__(self, minimum: int = 0, maximum: int = 255, value=None,
                 orientation: Qt.Orientation = Qt.Orientation.Vertical, step: int = 8,
                 unit: str = "", name: str = "", parent=None):
        super().__init__(parent)
        self.minimum = int(minimum)
        self.maximum = max(int(minimum) + 1, int(maximum))
        self.step = int(step)
        self.unit = unit
        self.name = name
        self.vertical = orientation == Qt.Orientation.Vertical
        self._value = self._clamp(value if value is not None else minimum)
        self._dragging = False
        self._hovered = False
        if self.vertical:
            self.setFixedWidth(self.THICK)
            self.setMinimumHeight(190)
        else:
            self.setFixedHeight(self.THICK)
            self.setMinimumWidth(220)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._say()

    # ------------------------------------------------------------------ Werte

    def value(self) -> int:
        return self._value

    def _clamp(self, value) -> int:
        return max(self.minimum, min(self.maximum, int(round(float(value)))))

    def set_value(self, value: int) -> None:
        """Von aussen setzen, ohne jemanden zu benachrichtigen.

        Der Kühler meldet seine Stufe alle paar Sekunden, und im Automatikmodus
        zeigt der Balken bloß mit. Würde das hier ein Signal auslösen, schrieb die
        Oberfläche den Wert dem Gerät sofort zurück.
        """
        self._value = self._clamp(value)
        self._say()
        self.update()

    def _apply(self, value: int) -> None:
        value = self._clamp(value)
        if value == self._value:
            return
        self._value = value
        self._say()
        self.update()
        self.valueChanged.emit(value)

    def _say(self) -> None:
        text = f"{self.name} {self._value}{self.unit}".strip()
        self.setToolTip(text)
        self.setAccessibleName(text)

    # ------------------------------------------------------------- Geometrie

    def _ends(self):
        """Anfang und Ende für den Griffmittelpunkt, entlang der Achse."""
        span = self.height() if self.vertical else self.width()
        return 2 + self.KNOB, span - 2 - self.KNOB

    def _track(self) -> QRectF:
        if self.vertical:
            left = (self.width() - self.TRACK) / 2.0
            return QRectF(left, 2, self.TRACK, max(4.0, self.height() - 4))
        top = (self.height() - self.TRACK) / 2.0
        return QRectF(2, top, max(4.0, self.width() - 4), self.TRACK)

    def _knob_along(self, value) -> float:
        low, high = self._ends()
        if high <= low:
            return (low + high) / 2.0
        ratio = (float(value) - self.minimum) / (self.maximum - self.minimum)
        if self.vertical:
            return high - (high - low) * ratio
        return low + (high - low) * ratio

    def _value_at(self, position) -> int:
        along = position.y() if self.vertical else position.x()
        low, high = self._ends()
        if high <= low:
            return self._value
        ratio = (along - low) / (high - low)
        if self.vertical:
            ratio = 1.0 - ratio
        ratio = max(0.0, min(1.0, ratio))
        return self._clamp(self.minimum + ratio * (self.maximum - self.minimum))

    def _fill(self) -> QRectF:
        track = self._track()
        knob = self._knob_along(self._value)
        if self.vertical:
            return QRectF(track.left(), knob, track.width(), max(0.0, track.bottom() - knob))
        return QRectF(track.left(), track.top(), max(0.0, knob - track.left()), track.height())

    # ------------------------------------------------------------------- Input

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setFocus()
            self._apply(self._value_at(event.position()))
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging:
            self._apply(self._value_at(event.position()))
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if not self._dragging:
            return
        self._dragging = False
        self._apply(self._value_at(event.position()))
        self.editingFinished.emit()
        event.accept()

    def wheelEvent(self, event):  # noqa: N802
        self._apply(self._value + (self.step if event.angleDelta().y() > 0 else -self.step))
        self.editingFinished.emit()
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802
        step = {Qt.Key.Key_Up: self.step, Qt.Key.Key_Right: self.step,
                Qt.Key.Key_Down: -self.step, Qt.Key.Key_Left: -self.step,
                Qt.Key.Key_PageUp: 4 * self.step, Qt.Key.Key_PageDown: -4 * self.step,
                Qt.Key.Key_Home: self.minimum - self._value,
                Qt.Key.Key_End: self.maximum - self._value}.get(event.key())
        if step is None:
            super().keyPressEvent(event)
            return
        self._apply(self._value + step)
        self.editingFinished.emit()
        event.accept()

    def enterEvent(self, event):  # noqa: N802
        self._hovered = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hovered = False
        self.update()

    # ------------------------------------------------------------------ Malen

    def _gradient(self, from_colour: str, to_colour: str, track: QRectF) -> QLinearGradient:
        if self.vertical:
            gradient = QLinearGradient(0, track.bottom(), 0, track.top())
        else:
            gradient = QLinearGradient(track.left(), 0, track.right(), 0)
        gradient.setColorAt(0, QColor(from_colour))
        gradient.setColorAt(1, QColor(to_colour))
        return gradient

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        live = self.isEnabled()
        track = self._track()

        painter.setPen(QPen(QColor("#262f3b"), 1))
        painter.setBrush(QColor("#0f151c"))
        painter.drawRoundedRect(track, 6, 6)

        fill = self._fill()
        if fill.width() > 1 and fill.height() > 1:
            gradient = (self._gradient("#1d7d64", "#34d3a6", track) if live
                        else self._gradient("#243040", "#2f3d4e", track))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(fill, 6, 6)

        along = self._knob_along(self._value)
        knob = QRectF(0, 0, 2 * self.KNOB, 2 * self.KNOB)
        centre = (QPointF(self.width() / 2.0, along) if self.vertical
                  else QPointF(along, self.height() / 2.0))
        knob.moveCenter(centre)
        shine = QLinearGradient(0, knob.top(), 0, knob.bottom())
        shine.setColorAt(0, QColor("#8cf5d4") if live else QColor("#57626f"))
        shine.setColorAt(1, QColor("#2bbf95") if live else QColor("#3c4652"))
        painter.setPen(QPen(QColor("#0b1015"), 1))
        painter.setBrush(QBrush(shine))
        painter.drawEllipse(knob)

        if live and (self._hovered or self._dragging or self.hasFocus()):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#7ff0cd"), 1))
            painter.drawEllipse(knob.adjusted(-2, -2, 2, 2))


# --------------------------------------------------------------------- window

class MainWindow(QMainWindow):
    def __init__(self, controller: Controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(make_icon())
        self.resize(940, 700)
        self._programmatic = False
        self._quitting = False
        self._last_status: dict = {}

        self._build_ui()
        self._build_tray()

        self.worker = Worker(controller, self)
        self.worker.updated.connect(self.apply_status)
        self.worker.problem.connect(lambda text: self.statusBar().showText(text, 6000))
        self.worker.start()

    # ------------------------------------------------------------- interface

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 10)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self._fan_box(), 3)
        top.addWidget(self._light_box(), 2)
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.addWidget(self._curve_box(), 3)
        bottom.addWidget(self._sensor_box(), 2)
        outer.addLayout(bottom)

        self.status = QLabel("verbinde ...")
        self.statusBar().addWidget(self.status)

    def _fan_box(self) -> QGroupBox:
        box = QGroupBox("Lüfter")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        self.mode_auto = QPushButton("Automatisch")
        self.mode_manual = QPushButton("Manuell")
        for button in (self.mode_auto, self.mode_manual):
            button.setCheckable(True)
            button.setMinimumWidth(120)
            row.addWidget(button)
        self.mode_auto.clicked.connect(lambda: self.set_mode("auto"))
        self.mode_manual.clicked.connect(lambda: self.set_mode("manual"))
        row.addStretch(1)
        self.value_label = QLabel("– %")
        value_font = QFont(self.font())
        value_font.setPointSize(value_font.pointSize() + 14)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        row.addWidget(self.value_label)
        layout.addLayout(row)

        self.fan_slider = PaintedBar(1, 100, int(self.controller.cfg["manual_speed"]),
                                     Qt.Orientation.Horizontal, step=5, unit=" %",
                                     name="Lüfterstufe")
        self.fan_slider.valueChanged.connect(self._slider_moved)
        self.fan_slider.editingFinished.connect(self._slider_released)
        layout.addWidget(self.fan_slider)

        details = QGridLayout()
        details.setHorizontalSpacing(18)
        self.read_real = QLabel("–")
        self.read_rpm = QLabel("–")
        self.read_temp = QLabel("–")
        for index, (name, widget) in enumerate((
            ("gemeldet", self.read_real), ("Anzeige", self.read_rpm), ("Referenz", self.read_temp),
        )):
            details.addWidget(_muted(name), 0, index * 2)
            details.addWidget(widget, 0, index * 2 + 1)
        layout.addLayout(details)

        self.fan_hint = _muted("")
        self.fan_hint.setWordWrap(True)
        layout.addWidget(self.fan_hint)

        self.power_start = QCheckBox("Kuehler beim Start einschalten")
        self.power_exit = QCheckBox("Kuehler beim Beenden ausschalten (auch beim Herunterfahren)")
        for check, field in ((self.power_start, "power_on_start"),
                             (self.power_exit, "power_off_on_exit")):
            check.setChecked(bool(self.controller.cfg.get(field, True)))
            check.toggled.connect(lambda value, name=field: self._setting(name, value))
            layout.addWidget(check)
        return box

    def _setting(self, field: str, value) -> None:
        self._run(lambda: self.controller.update_config({field: bool(value)}))

    def _light_box(self) -> QGroupBox:
        box = QGroupBox("Beleuchtung")
        grid = QGridLayout(box)
        grid.setColumnMinimumWidth(0, 62)
        grid.setContentsMargins(10, 10, 2, 10)      # rechts knapp: der Balken soll an den Rand
        grid.setHorizontalSpacing(14)

        self.light_on = QCheckBox("LEDs an")
        self.light_on.toggled.connect(lambda value: self.send_light(on=value))
        grid.addWidget(self.light_on, 0, 0, 1, 2)

        self.color_dots = ColorDots()
        self.color_dots.picked.connect(lambda value: self.send_light(color=value))
        colour_row = QHBoxLayout()
        colour_row.addWidget(self.color_dots)
        self.color_name = QLabel("")
        self.color_name.setStyleSheet("color:#8b98a9;")
        colour_row.addWidget(self.color_name, 1)
        grid.addLayout(colour_row, 1, 1)

        self.effect_box = PickBox(EFFECTS, self.send_light, "effect")
        self.speed_box = PickBox(EFFECT_SPEEDS, self.send_light, "speed")
        grid.addWidget(self.effect_box, 2, 1)
        grid.addWidget(self.speed_box, 3, 1)

        # Helligkeit senkrecht rechts, über die volle Höhe des Kastens: ein
        # kurzer Balken wirkt schnell gequetscht und ist schlecht zu fassen
        bright = QVBoxLayout()
        bright.addWidget(_muted("Helligkeit"))
        self.brightness_value = QLabel("255")
        self.brightness_value.setStyleSheet("color:#e6edf3; font-weight:600;")
        bright.addWidget(self.brightness_value)
        self.brightness = PaintedBar(0, 255,
                             int(self.controller.cfg["light"]["brightness"]),
                             Qt.Orientation.Vertical, step=8, name="Helligkeit")
        self.brightness.valueChanged.connect(self._brightness_moved)
        self.brightness.editingFinished.connect(self._brightness_released)
        bright.addWidget(self.brightness, 1)
        bright.setAlignment(self.brightness, Qt.AlignmentFlag.AlignHCenter)
        grid.addLayout(bright, 0, 2, 5, 1)
        grid.setColumnStretch(1, 1)

        actions = QGridLayout()
        save_button = QPushButton("Auf Kühler speichern")
        save_button.setToolTip(
            "Die gespeicherten LEDs auf den Kuehler schreiben.\n\n"
            "Noetig wird das nur, wenn der Kuehler unterwegs etwas anderes "
            "gemacht hat als gespeichert: nach dem Wiedereinstoepseln, nach "
            "Stromlos oder nachdem ihn jemand von Hand umgestellt hat. "
            "Solange alles zusammenpasst, aendert dieser Knopf nichts."
        )
        save_button.clicked.connect(self._apply_light_now)
        read_button = QPushButton("Vom Kühler laden")
        read_button.setToolTip(
            "Ubernehmen, was der Kuehler gerade wirklich zeigt, und als neue "
            "Standardeinstellung speichern.\n\n"
            "Die Lüfterstufe bleibt dabei, wie sie ist."
        )
        read_button.clicked.connect(self._load_light_from_pad)
        self.power_button = QPushButton("Kühler ausschalten")
        self.power_button.clicked.connect(self._toggle_power)
        actions.addWidget(save_button, 0, 0)
        actions.addWidget(read_button, 0, 1)
        actions.addWidget(self.power_button, 1, 0, 1, 2)
        grid.addWidget(_muted("Farbe"), 1, 0)
        grid.addWidget(_muted("Effekt"), 2, 0)
        grid.addWidget(_muted("Tempo"), 3, 0)
        grid.addLayout(actions, 4, 0, 1, 2)      # Spalte 2 gehoert dem Balken
        return box

    def _curve_box(self) -> QGroupBox:
        box = QGroupBox("Lüfterkurve")
        layout = QVBoxLayout(box)

        self.curve_view = CurveWidget()
        self.curve_view.points_changed.connect(self._curve_dragged)
        layout.addWidget(self.curve_view, 1)
        layout.addWidget(_muted("Punkte mit der Maus ziehen · Doppelklick fuegt einen hinzu · "
                                "Rechtsklick entfernt ihn."))

        table_row = QHBoxLayout()
        self.curve_table = QTableWidget(0, 3)
        self.curve_table.setHorizontalHeaderLabels(["°C", "%", ""])
        self.curve_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.curve_table.verticalHeader().setVisible(False)
        self.curve_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.curve_table.setMinimumHeight(150)
        self.curve_table.itemChanged.connect(self._curve_edited)
        table_row.addWidget(self.curve_table, 1)

        side = QVBoxLayout()
        add = QPushButton("+ Punkt")
        add.clicked.connect(self._add_point)
        remove = QPushButton("- Punkt")
        remove.clicked.connect(self._remove_point)
        form = QFormLayout()
        self.hysteresis = QDoubleSpinBox()
        self.hysteresis.setRange(0, 15)
        self.hysteresis.setSingleStep(0.5)
        self.hysteresis.setSuffix(" °C")
        self.hysteresis.valueChanged.connect(self._settings_changed)
        self.poll = QSpinBox()
        self.poll.setRange(1, 60)
        self.poll.setSuffix(" s")
        self.poll.valueChanged.connect(self._settings_changed)
        self.hysteresis_row = stepper(self.hysteresis, "°C")
        self.poll_row = stepper(self.poll, "s")
        form.addRow("Reaktion", self.hysteresis_row)
        form.addRow("Abstand", self.poll_row)
        side.addWidget(add)
        side.addWidget(remove)
        side.addLayout(form)
        side.addStretch(1)
        side_box = QWidget()
        side_box.setLayout(side)
        side_box.setMinimumWidth(215)
        table_row.addWidget(side_box)
        layout.addLayout(table_row)
        return box

    def _sensor_box(self) -> QGroupBox:
        box = QGroupBox("Temperaturen")
        layout = QVBoxLayout(box)
        self.sensor_list = QVBoxLayout()
        layout.addLayout(self.sensor_list)
        layout.addWidget(_muted("Die Kurve folgt dem wärmsten der markierten Sensoren."))
        layout.addStretch(1)
        self._sensor_widgets: dict[str, tuple[QCheckBox, QLabel]] = {}
        return box

    # ------------------------------------------------------------- tray icon

    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip(WINDOW_TITLE)
        menu = QMenu()

        header = menu.addAction("llano V12 Ultra")
        header.setEnabled(False)
        menu.addSeparator()

        mode_menu = menu.addMenu("Modus")
        self.tray_auto = _checkable_action("Automatisch", self)
        self.tray_manual = _checkable_action("Manuell", self)
        self.tray_auto.triggered.connect(lambda: self.set_mode("auto"))
        self.tray_manual.triggered.connect(lambda: self.set_mode("manual"))
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        for action in (self.tray_auto, self.tray_manual):
            mode_group.addAction(action)
            mode_menu.addAction(action)

        speed_menu = menu.addMenu("Stufe")
        self.tray_speeds: dict[int, QAction] = {}
        for speed in (25, 40, 55, 70, 85, 100):
            action = QAction(f"{speed} %", self)
            action.triggered.connect(lambda _=False, s=speed: self.set_speed(s))
            speed_menu.addAction(action)
            self.tray_speeds[speed] = action

        color_menu = menu.addMenu("Farbe")
        self.tray_colors: dict[int, QAction] = {}
        color_group = QActionGroup(self)
        color_group.setExclusive(True)
        for value, name in sorted(COLORS.items()):
            action = _checkable_action(name, self)
            action.triggered.connect(lambda _=False, v=value: self.send_light(color=v))
            color_group.addAction(action)
            color_menu.addAction(action)
            self.tray_colors[value] = action

        effect_menu = menu.addMenu("Effekt")
        self.tray_effects: dict[int, QAction] = {}
        effect_group = QActionGroup(self)
        effect_group.setExclusive(True)
        for value, name in sorted(EFFECTS.items()):
            action = _checkable_action(name, self)
            action.triggered.connect(lambda _=False, v=value: self.send_light(effect=v))
            effect_group.addAction(action)
            effect_menu.addAction(action)
            self.tray_effects[value] = action

        self.tray_light = _checkable_action("LEDs aus", self)
        self.tray_light.triggered.connect(
            lambda: self.send_light(on=not self.tray_light.isChecked()))
        menu.addAction(self.tray_light)
        menu.addSeparator()

        show = QAction("Fenster zeigen", self)
        show.triggered.connect(self._show_window)
        menu.addAction(show)
        quit_action = QAction("Beenden", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_window()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------- live state

    def apply_status(self, status: dict) -> None:
        self._last_status = status
        cfg = self.controller.cfg
        device = status.get("device") or {}
        mode = status.get("mode", "auto")
        target = status.get("target")

        self._programmatic = True
        self.mode_auto.setChecked(mode == "auto")
        self.mode_manual.setChecked(mode == "manual")
        self.tray_auto.setChecked(mode == "auto")
        self.tray_manual.setChecked(mode == "manual")
        self.fan_slider.setEnabled(mode == "manual")
        if mode == "manual":
            self.fan_slider.set_value(int(cfg["manual_speed"]))
        elif target is not None:
            self.fan_slider.set_value(int(target))

        light = cfg["light"]
        self.light_on.setChecked(bool(light["on"]))
        self.tray_light.setChecked(not light["on"])
        self.tray_light.setText("LEDs an" if light["on"] else "LEDs aus")
        self.color_dots.set_active(int(light["color"]))
        self.color_name.setText(COLORS.get(light["color"], "?"))
        for value, action in self.tray_colors.items():
            action.setChecked(value == light["color"])
        for value, action in self.tray_effects.items():
            action.setChecked(value == light["effect"])
        self.effect_box.set_active(light["effect"])
        self.speed_box.set_active(light["speed"])
        self.brightness.set_value(int(light["brightness"]))
        self.brightness_value.setText(str(int(light["brightness"])))

        self.hysteresis.blockSignals(True)
        self.poll.blockSignals(True)
        self.hysteresis.setValue(float(cfg["hysteresis"]))
        self.poll.setValue(int(cfg["poll_seconds"]))
        self.hysteresis.blockSignals(False)
        self.poll.blockSignals(False)
        self._programmatic = False

        shown = int(cfg["manual_speed"]) if mode == "manual" else (target or 0)
        self.value_label.setText(f"{shown} %")
        self.read_real.setText(f"{device.get('fan_speed', '–')} %" if device else "–")
        self.read_rpm.setText(f"~{device['rpm_display']} U/min" if device else "–")
        temp = status.get("temp")
        self.read_temp.setText(f"{temp:.1f} °C" if temp is not None else "–")
        self.fan_hint.setText(
            "Automatik: die Stufe ergibt sich aus der Kurve."
            if mode == "auto" else
            "Manuell: der Regler schreibt direkt an den Kuehler."
        )
        self.power_button.setText("Kühler einschalten"
                                  if device and not device.get("powered_on")
                                  else "Kühler ausschalten")

        self._fill_sensors(status.get("temps", {}), cfg["sensors"], temp)
        self.curve_view.set_data(cfg["curve"], temp)
        self._sync_curve_table(cfg["curve"])

        node = status.get("node") or "kein Geraet"
        error = status.get("error")
        self.status.setText(f"{node} · {len(status.get('temps', {}))} Sensoren"
                            + (f" · {error}" if error else ""))
        self.status.setStyleSheet("color:#f0a640;" if error else "")

        accent = COLOR_SWATCH.get(light["color"], "#34d3a6")
        spinning = bool(device.get("fan_speed", 0)) and bool(device.get("powered_on", True))
        self.tray.setIcon(make_icon(accent=accent, spinning=spinning))
        self.setWindowIcon(make_icon(accent=accent))
        self.tray.setToolTip(
            f"{WINDOW_TITLE}\n"
            + (f"Luefter {device['fan_speed']} %  ·  " if device else "")
            + (f"{temp:.0f} °C\n" if temp is not None else "\n")
            + ("LEDs an · " + COLORS.get(light["color"], "?") if light["on"] else "LEDs aus")
        )

    def _fill_sensors(self, temps: dict, chosen: list, reference: float | None) -> None:
        chosen = set(chosen)
        for key, value in sorted(temps.items()):
            entry = self._sensor_widgets.get(key)
            if entry is None:
                entry = self._add_sensor_row(key)
                self._sensor_widgets[key] = entry
            check, label = entry
            if not check.underMouse():
                check.setChecked(key in chosen)
            label.setText(f"{value:.1f} °C")
            bold = value == reference
            label.setStyleSheet("font-weight:600;color:#f0a640;" if bold else "")
            check.show()
        for key, (check, _label) in self._sensor_widgets.items():
            if key not in temps:
                check.hide()

    def _add_sensor_row(self, key: str) -> tuple[QCheckBox, QLabel]:
        row = QHBoxLayout()
        check = QCheckBox(_pretty_sensor(key))
        check.setToolTip(key)
        check.toggled.connect(lambda value, k=key: self._sensor_toggled(k, value))
        label = QLabel("–")
        label.setMinimumWidth(64)
        label.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(check, 1)
        row.addWidget(label)
        holder = QWidget()
        holder.setLayout(row)
        self.sensor_list.addWidget(holder)
        return check, label

    def _sync_curve_table(self, curve: list) -> None:
        if self.curve_table.hasFocus():
            return
        self.curve_table.blockSignals(True)
        self.curve_table.setRowCount(len(curve))
        for row, (temp, speed) in enumerate(curve):
            for column, value in enumerate((temp, speed)):
                item = self.curve_table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.curve_table.setItem(row, column, item)
                item.setData(Qt.ItemDataRole.EditRole, value)
                item.setText(f"{value:g}")
        self.curve_table.blockSignals(False)

    # --------------------------------------------------------------- commands

    def set_mode(self, mode: str) -> None:
        self._run(lambda: self.controller.update_config({"mode": mode}))
        self._run(lambda: self.controller.apply_fan(force=True))

    def set_speed(self, speed: int) -> None:
        self._run(lambda: self.controller.update_config(
            {"mode": "manual", "manual_speed": int(speed)}))
        self._run(lambda: self.controller.apply_fan(force=True))

    def _slider_moved(self, value: int) -> None:
        if not self._programmatic:
            self.value_label.setText(f"{value} %")

    def _slider_released(self) -> None:
        if not self._programmatic and self.controller.cfg["mode"] == "manual":
            self.set_speed(self.fan_slider.value())

    def send_light(self, **patch) -> None:
        self._run(lambda: self.controller.update_config({"light": patch}))
        self._run(lambda: self.controller.apply_light(force=True))

    def _brightness_moved(self, value: int) -> None:
        self.brightness_value.setText(str(value))

    def _brightness_released(self) -> None:
        if not self._programmatic:
            self.send_light(brightness=int(self.brightness.value()))

    def _apply_light_now(self) -> None:
        self.send_light(**{k: v for k, v in self.controller.cfg["light"].items()})

    def _load_light_from_pad(self) -> None:
        """Take whatever the pad is really showing as the new standard setting.

        The other way round from "Auf Kuehler speichern": useful when somebody
        set the pad up by hand -- or on another computer -- and that look is the
        one to keep. The fan level is deliberately left alone; it lives in the
        other box and follows the curve.
        """
        with self.controller.io:
            pad = self.controller.ensure_connected()
            if pad is None:
                self.status.setText("Geraet nicht erreichbar")
                return
            try:
                state = pad.read_state()
            except OSError as exc:
                self.status.setText(f"Geraet: {exc}")
                return
        light = {"on": bool(state.light_on), "color": int(state.color),
                 "effect": int(state.effect), "speed": int(state.effect_speed),
                 "brightness": int(state.brightness)}
        self._run(lambda: self.controller.update_config({"light": light}))
        self.status.setText(
            f"Vom Kuehler uebernommen: {state.color_name}, {state.effect_name}, "
            f"Helligkeit {state.brightness}")

    def _toggle_power(self) -> None:
        device = self._last_status.get("device") or {}
        turn_on = not device.get("powered_on", True)
        with self.controller.io:
            pad = self.controller.ensure_connected()
            if pad is None:
                self.status.setText("Geraet nicht erreichbar")
                return
            self.controller.last_state = pad.set_power(turn_on)
            self.controller._light_signature = None
        self.controller.apply_light(force=True)
        self.controller.apply_fan(force=True)

    def _sensor_toggled(self, key: str, on: bool) -> None:
        sensors = list(self.controller.cfg["sensors"])
        if on and key not in sensors:
            sensors.append(key)
        elif not on and key in sensors:
            sensors.remove(key)
        if not sensors:
            QMessageBox.warning(self, "llano", "Mindestens ein Sensor muss gewaehlt bleiben.")
            self._programmatic = True
            self._sensor_widgets[key][0].setChecked(True)
            self._programmatic = False
            return
        self._run(lambda: self.controller.update_config({"sensors": sensors}))

    def _curve_dragged(self, points: list, final: bool) -> None:
        """Punkte im Graph bewegen.

        Während des Ziehens nur anzeigen: sonst schreibt jede Mausbewegung die
        Konfigurationsdatei und stellt den Lüfter um. Gespeichert und geschrieben
        wird erst, wenn die Maustaste losgeläßt ist.
        """
        self.controller.cfg["curve"] = points
        self.controller.follower.curve = points
        self._sync_curve_table(points)
        if final:
            self._run(lambda: self.controller.update_config({"curve": points}))

    def _curve_edited(self, item: QTableWidgetItem) -> None:
        if self._programmatic:
            return
        curve = [list(point) for point in self.controller.cfg["curve"]]
        row, column = item.row(), item.column()
        if column > 1 or row >= len(curve):
            return
        try:
            value = float(item.text().replace(",", "."))
        except ValueError:
            return
        curve[row][column] = value if column == 0 else max(1, min(100, int(value)))
        self._run(lambda: self.controller.update_config({"curve": curve}))

    def _add_point(self) -> None:
        curve = [list(point) for point in self.controller.cfg["curve"]]
        last = curve[-1] if curve else [70, 50]
        curve.append([min(100, last[0] + 5), min(100, last[1] + 5)])
        self._run(lambda: self.controller.update_config({"curve": curve}))

    def _remove_point(self) -> None:
        curve = [list(point) for point in self.controller.cfg["curve"]]
        row = self.curve_table.currentRow()
        if len(curve) <= 2:
            self.status.setText("Mindestens zwei Punkte behalten die Kurve.")
            return
        del curve[row if row >= 0 else -1]
        self._run(lambda: self.controller.update_config({"curve": curve}))

    def _settings_changed(self) -> None:
        if self._programmatic:
            return
        patch = {"hysteresis": float(self.hysteresis.value()),
                 "poll_seconds": int(self.poll.value())}
        self._run(lambda: self.controller.update_config(patch))

    def _run(self, action) -> None:
        """Run a device or config change and repaint right away."""
        try:
            action()
        except OSError as exc:
            self.status.setText(f"Geraet: {exc}")
            return
        try:
            self.apply_status(self.controller.poll())
        except OSError:
            pass

    # ------------------------------------------------------------- lifecycle

    def closeEvent(self, event):  # noqa: N802
        if self._quitting or not self.tray.isVisible():
            self.quit()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(
            WINDOW_TITLE, "Laeuft im Hintergrund weiter — Symbol in der Taskleiste.",
            QSystemTrayIcon.MessageIcon.Information, 3000,
        )

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.worker.stop()
        # Switching off has to happen while we still own the pad.
        self.controller.finish()
        self.tray.hide()
        self.controller.disconnect()
        QApplication.instance().quit()


def _checkable_action(text: str, parent) -> QAction:
    """QAction with the checkable flag set the explicit way."""
    action = QAction(text, parent)
    action.setCheckable(True)
    return action


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color:#8b98a9;")
    return label


def _pretty_sensor(key: str) -> str:
    chip, _, label = key.partition(":")
    names = {"coretemp": "CPU", "k10temp": "CPU", "acpitz": "Mainboard", "nvme": "SSD",
             "nvidia": "GPU", "spd5118": "RAM", "iwlwifi_1": "WLAN", "amdgpu": "GPU"}
    base = names.get(chip, chip)
    if not label or label in ("Composite", "total"):
        return base
    # "nvidia:GPU" would read "GPU GPU", a bare "1" adds nothing.
    if label.lower() in (base.lower(), chip.lower()) or label.isdigit():
        return base
    return f"{base} · {label}"


# ----------------------------------------------------------------- entry point

def run(controller: Controller | None = None, start_minimized: bool = False,
        tray_only: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(WINDOW_TITLE)
    app.setDesktopFileName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_icon())

    # Before anything reaches the pad, so a session that ends during startup
    # still leaves the pad switched off instead of switched on.
    wake = QuitWatcher()
    try:
        return _run_window(app, controller, wake, start_minimized, tray_only)
    finally:
        wake.close()


def _run_window(app: QApplication, controller: Controller, wake: QuitWatcher,
                start_minimized: bool, tray_only: bool) -> int:
    if controller is None:
        try:
            controller = config_and_controller()
        except AlreadyRunning as exc:
            # Ein Doppelklick auf das Symbol darf nicht einfach ins Leere laufen:
            # die Meldung ging bisher auf eine Konsole, die ein verpacktes
            # Programm gar nicht hat. Am Terminal genugt der Text, sonst das
            # Fenster -- sonst scheint das Programm nur bose zu sein.
            print(f"Fehler: {exc}")
            if not sys.stdout or not sys.stdout.isatty():
                QMessageBox.warning(None, WINDOW_TITLE, str(exc))
            return 0
    if controller.cfg.get("power_on_start", True):
        controller.set_power(True, quiet=True)
    window = MainWindow(controller)
    if tray_only:
        window.hide()
    elif start_minimized:
        window.showMinimized()
    else:
        window.show()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        window.tray.showMessage(WINDOW_TITLE,
                                "Diese Oberflaeche hat kein Taskleisten-Symbol.",
                                QSystemTrayIcon.MessageIcon.Warning, 5000)

    log.info("Fenster ist gebaut und gezeigt; Schleife laeuft an.")
    wake.attach(window)
    return app.exec()


class QuitWatcher:
    """End the program on its feet when the session ends.

    Logging out and shutting the machine down send SIGTERM. Left alone that
    kills the process where it stands - mid-poll, with the pad still running,
    because the "switch off on exit" step never happens. So the signal writes
    into a pipe that the Qt event loop watches, which wakes the loop and lets
    the window clean up as though "Beenden" had been clicked.

    Two things matter here. A Python handler only runs once the interpreter
    gets the thread back, and while the Qt loop waits for events it does not;
    `set_wakeup_fd` is written by the interpreter itself on delivery, so the
    loop wakes at once. And the watcher has to exist *before* the pad is
    switched on: a session that ends during startup would otherwise leave the
    pad running with nothing left to switch it off again. A signal that
    arrives that early is remembered and carried out as soon as the window is
    there to do the cleanup.
    """

    def __init__(self) -> None:
        self.read_fd, self.write_fd = os.pipe()
        os.set_blocking(self.read_fd, False)
        os.set_blocking(self.write_fd, False)
        self.signal: int | None = None
        self.notifier: QSocketNotifier | None = None
        self.previous = {signum: signal.signal(signum, self._wake)
                         for signum in (signal.SIGTERM, signal.SIGINT)}
        signal.set_wakeup_fd(self.write_fd)

    def _wake(self, signum, _frame) -> None:
        self.signal = signum
        try:
            os.write(self.write_fd, b"x")
        except OSError:
            pass

    def attach(self, window: "MainWindow") -> None:
        """Hand the wake-up to the window.

        The signal that arrives here may have come before the window was
        there -- a console that still had an interrupt in the air, a session
        already on its way out. That is a "Beenden" like any other, so it goes
        through the window once the loop runs: only that way does the pad get
        switched off on the way out, which is the whole point of watching for
        the signal. Quitting before the loop ever started left the pad switched
        on with nothing left to switch it off, and left nothing on screen
        either -- which is what one reporter saw as "the interface just does
        not start".
        """
        self.notifier = QSocketNotifier(self.read_fd, QSocketNotifier.Type.Read, window)
        self.notifier.activated.connect(lambda *_: window.quit())
        if self.signal is None:
            return
        log.warning("Ein Abbruch (Signal %d) kam schon vor dem Fenster an - "
                    "die Oberflaeche beendet sich wieder.", self.signal)
        QTimer.singleShot(0, window.quit)

    def close(self) -> None:
        for signum, handler in self.previous.items():
            signal.signal(signum, handler)
        signal.set_wakeup_fd(-1)
        if self.notifier is not None:
            self.notifier.setEnabled(False)
        for fd in (self.read_fd, self.write_fd):
            os.close(fd)


def config_and_controller() -> Controller:
    controller = Controller(config_mod.load())
    controller.lock.acquire()          # AlreadyRunning, wenn ein anderer schon am Geraet sitzt
    return controller
