#!/usr/bin/env python3
"""
The "Build" tab of BlockSmith: Ollama proposes structures made of cubes, the app checks them,
shows them in a 3D view, and the robot builds after confirmation.

A structure is a list of cubes on a grid: x (away from the robot), y (to the left), z (level, 0 = table)
and a colour. A cube must stand on the table or exactly on another cube.
"""

import json
import math
import threading
import time
import urllib.error

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

import i18n
from i18n import T
import colours as vision

MAX_CUBES = 6
GRID = 4                     # structure grid: x and y from 0 to GRID-1
LABEL = i18n.ColorNames()      # colour names in the current language
SYNONYMS = {"red": "czerwony", "yellow": "zolty", "green": "zielony", "blue": "niebieski", "purple": "fioletowy",
            "violet": "fioletowy", "żółty": "zolty", "zółty": "zolty", "żolty": "zolty"}


# ----------------------------------------------------------------------------
# Checking and repairing a structure plan
# ----------------------------------------------------------------------------
def _gravity(cubes):
    """Drops cubes down: in every column levels 0, 1, 2... with no gaps. Returns True if anything changed."""
    changed = False
    columns = {}
    for c in cubes:
        columns.setdefault((c["x"], c["y"]), []).append(c)
    for col in columns.values():
        for level, c in enumerate(sorted(col, key=lambda k: k["z"])):
            if c["z"] != level:
                c["z"], changed = level, True
    return changed


def normalize_structure(raw, available, max_cubes=MAX_CUBES):
    """Turns any model answer into a structure that can be built from the available cubes.

    available: {colour: count}. Returns (cubes, notes). Empty list = nothing could be salvaged.
    """
    notes, cubes, seen = [], [], set()
    for item in raw if isinstance(raw, list) else []:
        try:
            x, y, z = int(round(float(item["x"]))), int(round(float(item["y"]))), int(round(float(item["z"])))
        except (KeyError, TypeError, ValueError):
            continue
        color = str(item.get("color", "")).strip().lower()
        cubes.append({"x": x, "y": y, "z": max(z, 0), "color": SYNONYMS.get(color, color)})
    if not cubes:
        return [], [T("plan nie zawierał kostek")]
    mx, my = min(c["x"] for c in cubes), min(c["y"] for c in cubes)
    kept = []
    for c in cubes:
        c["x"], c["y"] = c["x"] - mx, c["y"] - my
        if c["x"] < GRID and c["y"] < GRID and (c["x"], c["y"], c["z"]) not in seen:
            seen.add((c["x"], c["y"], c["z"]))
            kept.append(c)
    if len(kept) < len(cubes):
        notes.append(T("usunięto kostki poza siatką lub zdublowane"))
    cubes = kept
    if _gravity(cubes):
        notes.append(T("dosunięto kostki wiszące w powietrzu"))

    total = sum(available.values())
    limit = min(max_cubes, total)
    if len(cubes) > limit:
        notes.append(T("przycięto do liczby dostępnych kostek: ") + str(limit))
        while len(cubes) > limit:                       # remove from the top, starting with the tallest column
            cubes.remove(max(cubes, key=lambda c: (c["z"], c["x"], c["y"])))

    stock, recolored = dict(available), False
    for c in cubes:                                     # first the cubes whose colour is in stock
        if stock.get(c["color"], 0) > 0:
            stock[c["color"]] -= 1
            c["ok"] = True
    for c in cubes:
        if not c.pop("ok", False):
            best = max(stock, key=stock.get) if stock else None
            if best is None or stock[best] <= 0:
                c["color"] = None
            else:
                c["color"], recolored = best, True
                stock[best] -= 1
    cubes = [c for c in cubes if c["color"]]
    if recolored:
        notes.append(T("zmieniono kolory na dostępne"))
    _gravity(cubes)
    if cubes:
        mx, my = min(c["x"] for c in cubes), min(c["y"] for c in cubes)
        for c in cubes:
            c["x"], c["y"] = c["x"] - mx, c["y"] - my
    return sorted(cubes, key=lambda c: (c["z"], c["x"], c["y"])), notes


def kostki(n):
    """Count with the noun in the current language: 1 cube, 2 cubes."""
    return i18n.count(n, "kostka")


def shape_key(cubes):
    """Shape without colours, used to filter out repeated proposals."""
    return tuple(sorted((c["x"], c["y"], c["z"]) for c in cubes))


def templates(available, max_cubes=MAX_CUBES):
    """Built-in templates, for when Ollama does not answer or proposes too little."""
    n = min(max_cubes, sum(available.values()))
    shapes = [(T("Wieża"), T("Wszystkie kostki jedna na drugiej."), [(0, 0, z) for z in range(n)])]
    if n >= 3:
        stairs, col = [], 0
        while len(stairs) < n:
            for z in range(col + 1):
                if len(stairs) < n:
                    stairs.append((col, 0, z))
            col += 1
        shapes.append((T("Schody"), T("Każdy kolejny słupek o jedną kostkę wyższy."), stairs))
    if n >= 4:
        shapes.append((T("Mur"), T("Dwa poziomy kostek obok siebie."), [(x, 0, z) for z in range(2) for x in range(n // 2)]))
    if n >= 5:
        shapes.append((T("Zamek"), T("Kwadratowa podstawa z wieżyczką."), ([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (0, 0, 1), (0, 0, 2)])[:n]))
    out = []
    for name, desc, pts in shapes:
        palette = [k for k, v in sorted(available.items(), key=lambda kv: -kv[1]) for _ in range(v)]
        raw = [{"x": x, "y": y, "z": z, "color": palette[i % len(palette)] if palette else ""} for i, (x, y, z) in enumerate(pts)]
        cubes, _ = normalize_structure(raw, available, max_cubes)
        if cubes:
            out.append({"name": name, "description": desc, "cubes": cubes, "notes": [], "source": T("wzorzec programu")})
    return out


PROMPT = """You design small structures built from identical toy cubes by a robot arm.
Cubes sit on a grid. Each cube has integer coordinates x (0-3), y (0-3) and z (level, 0 = on the table).
Rule: a cube must be on the table (z = 0) or directly on top of another cube (same x and y, z one lower).
Available cubes: __STOCK__. You may use at most __MAX__ cubes in one structure and never more of a colour than available.
Propose exactly 3 clearly different structures (different shapes, not just different colours), for example a tower,
stairs, a wall, a pyramid, a gate-like shape, a castle. Use colours deliberately (patterns, layers, symmetry).
__WISH__
Reply with ONE JSON object and nothing else:
{"proposals": [{"name": "<short name in __LANG__>", "description": "<one sentence in __LANG__>",
  "cubes": [{"x": 0, "y": 0, "z": 0, "color": "<one of: __COLORS__>"}]}]}"""


def ask_ollama(core, model, available, wish="", max_cubes=MAX_CUBES, timeout=300.0):
    """Returns the list of raw proposals from the model. Raises core.RobotError with a description on failure."""
    stock = ", ".join(f"{v} x {k}" for k, v in available.items() if v > 0)
    system = (PROMPT.replace("__LANG__", "English" if i18n.language() == "en" else "Polish").replace("__STOCK__", stock).replace("__MAX__", str(min(max_cubes, sum(available.values()))))
              .replace("__COLORS__", ", ".join(k for k, v in available.items() if v > 0))
              .replace("__WISH__", f"The user asked for: {wish.strip()}" if wish.strip() else ""))
    body = {"model": model, "stream": False, "format": "json", "keep_alive": "15m", "options": {"temperature": 0.7},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": T("Zaproponuj trzy budowle.")}]}
    try:
        resp = core._http_json(core.OLLAMA_URL + "/api/chat", body, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise core.RobotError(T("Ollama zwróciła błąd {0}: {1}").format(e.code, e.read().decode('utf-8', 'ignore')[:160]))
    except (urllib.error.URLError, OSError) as e:
        raise core.RobotError(T("Brak połączenia z Ollamą ({0}). Sprawdź, czy działa: ollama list").format(e))
    text = (resp.get("message") or {}).get("content", "").strip()
    try:
        obj = json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        try:
            obj = json.loads(text[a:b + 1]) if 0 <= a < b else None
        except ValueError:
            obj = None
    props = obj.get("proposals") if isinstance(obj, dict) else None
    if isinstance(obj, dict) and props is None and "cubes" in obj:
        props = [obj]
    if not isinstance(props, list) or not props:
        raise core.RobotError(T("Model nie zwrócił propozycji w oczekiwanej postaci."))
    return [p for p in props if isinstance(p, dict)]


def list_models(core):
    try:
        tags = core._http_json(core.OLLAMA_URL + "/api/tags", timeout=4.0)
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return [m.get("name") for m in tags.get("models", []) if m.get("name")]


# ----------------------------------------------------------------------------
# Build geometry
# ----------------------------------------------------------------------------
def cube_xy(cube, cubes, origin, pitch):
    """Cube position in the robot frame (mm). The saved build site is the centre of the structure's base."""
    cx = (min(c["x"] for c in cubes) + max(c["x"] for c in cubes)) / 2.0
    cy = (min(c["y"] for c in cubes) + max(c["y"] for c in cubes)) / 2.0
    return origin["x"] + (cube["x"] - cx) * pitch, origin["y"] + (cube["y"] - cy) * pitch


def fold_angle(deg):
    """Square angle folded into (-45, 45]: a cube looks the same every 90 degrees."""
    a = (deg + 45.0) % 90.0 - 45.0
    return 45.0 if a == -45.0 else a


def build_sequence(pick, angle, place, z_pick, z_place, z_travel, invert=False, base_comp=False):
    """Actions for the Runner: take the cube at pick=(x, y), rotate by -angle and place it at place=(x, y) at height z_place."""
    turn = (angle if invert else -angle)
    if base_comp:      # if the driver's R is relative to the arm, not the table: add the base rotation
        turn += math.degrees(math.atan2(pick[1], pick[0]) - math.atan2(place[1], place[0]))
    px, py, bx, by = float(pick[0]), float(pick[1]), float(place[0]), float(place[1])
    return [
        {"type": "move", "z": z_travel, "up_only": True},        # up only, never down at the current position
        {"type": "move", "x": px, "y": py, "z": z_travel, "r": 0.0},
        {"type": "move", "x": px, "y": py, "z": z_pick, "r": 0.0},
        {"type": "suction", "on": True},
        {"type": "wait", "seconds": 0.6},
        {"type": "move", "x": px, "y": py, "z": z_travel, "r": 0.0},
        {"type": "move", "x": bx, "y": by, "z": z_travel, "r": turn},
        {"type": "move", "x": bx, "y": by, "z": z_place + 2.0, "r": turn},
        {"type": "suction", "on": False},
        {"type": "wait", "seconds": 0.6},
        {"type": "move", "x": bx, "y": by, "z": z_travel, "r": turn},
    ]


# ----------------------------------------------------------------------------
# 3D view of the structure (drawn in the app window, no browser)
# ----------------------------------------------------------------------------
class StructureView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.cubes, self.done, self.current = [], None, None
        self.yaw, self._drag = math.radians(-35), None
        self.setMinimumHeight(250)
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def show_structure(self, cubes, done=None, current=None):
        """done: how many of the first cubes already stand (None = show the whole structure). current: index of the cube on its way."""
        self.cubes, self.done, self.current = list(cubes), done, current
        self.update()

    def mousePressEvent(self, e):
        self._drag = e.x()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.yaw += (e.x() - self._drag) * 0.012
            self._drag = e.x()
            self.update()

    def mouseReleaseEvent(self, _e):
        self._drag = None

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QtGui.QColor(14, 17, 20))
        if not self.cubes:
            p.setPen(QtGui.QColor(139, 152, 165))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, T("Tu pojawi się podgląd wybranej budowli."))
            return
        pitch, cy_, sy_ = math.radians(32), math.cos(self.yaw), math.sin(self.yaw)
        xs, ys, zs = [c["x"] for c in self.cubes], [c["y"] for c in self.cubes], [c["z"] for c in self.cubes]
        cx, cy = (min(xs) + max(xs) + 1) / 2.0, (min(ys) + max(ys) + 1) / 2.0
        span = max(max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
        height = max(zs) + 1
        scale = min(w / (span * 1.5 + 1.6), h / (height * math.cos(pitch) + span * 0.75 + 1.3))
        ox, oy = w / 2.0, h - 26 - span * 0.36 * scale

        def proj(X, Y, Z):
            X, Y = X - cx, Y - cy
            xr, yr = X * cy_ - Y * sy_, X * sy_ + Y * cy_
            return QtCore.QPointF(ox + xr * scale, oy + (yr * math.sin(pitch) - Z * math.cos(pitch)) * scale), yr * math.cos(pitch) + Z * math.sin(pitch)

        def quad(pts, color, pen):
            p.setPen(pen)
            p.setBrush(color)
            p.drawPolygon(QtGui.QPolygonF([proj(*q)[0] for q in pts]))

        m = 0.6                                              # base plate and the "away from the robot" arrow
        quad([(min(xs) - m, min(ys) - m, 0), (max(xs) + 1 + m, min(ys) - m, 0), (max(xs) + 1 + m, max(ys) + 1 + m, 0),
              (min(xs) - m, max(ys) + 1 + m, 0)], QtGui.QColor(36, 43, 50), QtGui.QPen(QtGui.QColor(70, 82, 94), 1))
        a0, a1 = proj(max(xs) + 1 + m * 0.2, cy, 0)[0], proj(max(xs) + 1 + m * 0.95, cy, 0)[0]
        p.setPen(QtGui.QPen(QtGui.QColor(139, 152, 165), 2))
        p.drawLine(a0, a1)
        p.drawEllipse(a1, 3, 3)

        order = sorted(range(len(self.cubes)), key=lambda i: proj(self.cubes[i]["x"] + 0.5, self.cubes[i]["y"] + 0.5, self.cubes[i]["z"] + 0.5)[1])
        for i in order:
            c = self.cubes[i]
            b, g, r = vision.DRAW.get(c["color"], (150, 150, 150))
            pending = self.done is not None and i >= self.done
            alpha = 70 if pending and i != self.current else 255
            x, y, z = c["x"], c["y"], c["z"]
            edge = QtGui.QPen(QtGui.QColor(255, 255, 255) if i == self.current else QtGui.QColor(10, 12, 14, alpha), 2 if i == self.current else 1)
            faces = [((0, 1), [(x + 1, y, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x + 1, y, z + 1)], sy_),       # +X
                     ((0, -1), [(x, y, z), (x, y + 1, z), (x, y + 1, z + 1), (x, y, z + 1)], -sy_),                    # -X
                     ((1, 1), [(x, y + 1, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], cy_),      # +Y
                     ((1, -1), [(x, y, z), (x + 1, y, z), (x + 1, y, z + 1), (x, y, z + 1)], -cy_)]                    # -Y
            for (axis, _s), pts, facing in faces:
                if facing > 1e-6:                            # face turned towards the viewer
                    k = 0.58 if axis == 0 else 0.76
                    quad(pts, QtGui.QColor(int(r * k), int(g * k), int(b * k), alpha), edge)
            quad([(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], QtGui.QColor(r, g, b, alpha), edge)
        p.setPen(QtGui.QColor(139, 152, 165))
        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(8, h - 8, T("Przeciągnij, aby obrócić. Kreska z kropką wskazuje kierunek od robota."))


# ----------------------------------------------------------------------------
# The tab
# ----------------------------------------------------------------------------
class BuildTab(QtWidgets.QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.core, self.cfg = app, app.core, app.cfg
        self.proposals = []
        self.job = None              # build in progress: {"cubes", "i", "moving", "paused"}
        self._result = None          # result from the thread that asks Ollama
        self._asking = False
        W = QtWidgets
        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        hint = W.QLabel(T("Ollama proponuje budowle z kostek, które widzi kamera (najwyżej 6). Wybierz jedną, obejrzyj podgląd pod obrazem z kamery i kliknij „Buduj”. Kalibrację wykonaj na tych samych kostkach."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#aab4be;")
        lay.addWidget(hint)

        row = W.QHBoxLayout()
        self.site_btn = W.QPushButton(T("Zapisz miejsce budowy"))
        self.site_btn.setToolTip(T("Postaw kostkę tam, gdzie ma stanąć budowla (poza polem roboczym), ustaw na niej przyssawkę i kliknij."))
        self.site_btn.clicked.connect(self.save_site)
        row.addWidget(self.site_btn)
        row.addWidget(W.QLabel(T("Kostka")))
        self.size = W.QSpinBox()
        self.size.setRange(15, 45)
        self.size.setSuffix(" mm")
        self.size.setValue(int(self.cfg["cube_size"]))
        self.size.valueChanged.connect(lambda v: self._set("cube_size", int(v)))
        row.addWidget(self.size)
        lay.addLayout(row)
        self.site_state = W.QLabel("")
        self.site_state.setWordWrap(True)
        lay.addWidget(self.site_state)

        row = W.QHBoxLayout()
        row.addWidget(W.QLabel(T("Model")))
        self.model = W.QComboBox()
        row.addWidget(self.model, 1)
        refresh = W.QPushButton(T("Odśwież"))
        refresh.clicked.connect(self.refresh_models)
        row.addWidget(refresh)
        lay.addLayout(row)
        self.wish = W.QLineEdit()
        self.wish.setPlaceholderText(T("Życzenie dla Ollamy, np. „coś wysokiego” (można zostawić puste)"))
        lay.addWidget(self.wish)
        self.ask_btn = W.QPushButton(T("Zaproponuj budowle"))
        self.ask_btn.clicked.connect(self.ask)
        lay.addWidget(self.ask_btn)
        self.stock_label = W.QLabel("")
        self.stock_label.setWordWrap(True)
        lay.addWidget(self.stock_label)

        self.list = W.QListWidget()
        self.list.setFixedHeight(92)
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self._select)
        lay.addWidget(self.list)
        self.desc = W.QLabel("")
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc)
        self.view = StructureView()          # the main window puts the preview below the camera image

        row = W.QHBoxLayout()
        self.build_btn = W.QPushButton(T("Buduj"))
        self.build_btn.setStyleSheet("font-weight:bold;")
        self.build_btn.clicked.connect(self.start)
        self.resume_btn = W.QPushButton(T("Wznów"))
        self.resume_btn.clicked.connect(self.resume)
        self.abort_btn = W.QPushButton(T("Przerwij budowę"))
        self.abort_btn.clicked.connect(lambda: self.abort(T("Budowa przerwana.")))
        for b in (self.build_btn, self.resume_btn, self.abort_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.progress = W.QLabel("")
        self.progress.setWordWrap(True)
        lay.addWidget(self.progress)

        box = W.QGroupBox(T("Korekta obrotu kostek"))
        b = W.QVBoxLayout(box)
        self.rot_inv = W.QCheckBox(T("Odwróć kierunek obrotu"))
        self.rot_base = W.QCheckBox(T("Uwzględnij obrót podstawy robota"))
        for chk, key in ((self.rot_inv, "rot_invert"), (self.rot_base, "rot_base")):
            chk.setChecked(bool(self.cfg[key]))
            chk.toggled.connect(lambda v, k=key: self._set(k, bool(v)))
            b.addWidget(chk)
        rot_hint = W.QLabel(T("Zostaw wyłączone, jeśli kostki stają równo. Pierwsze włącz, gdy stają obrócone w złą stronę. Drugie, gdy skrzywienie zależy od tego, skąd kostka została wzięta."))
        rot_hint.setWordWrap(True)
        rot_hint.setStyleSheet("color:#aab4be;")
        b.addWidget(rot_hint)
        lay.addWidget(box)
        lay.addStretch(1)
        self.refresh_models()
        self._site_text()

    # ------------------------------------------------------------------ settings
    def _set(self, key, value):
        self.cfg[key] = value
        self.app.save()

    def _site_text(self):
        s = self.cfg["build_site"]
        self.site_state.setText(T("Miejsce budowy: X {0:.0f}, Y {1:.0f}, Z {2:.0f} mm.").format(s['x'], s['y'], s['z']) if s else
                                T("Miejsce budowy nie jest ustawione. Postaw kostkę tam, gdzie ma stanąć budowla, ustaw na niej przyssawkę i kliknij „Zapisz miejsce budowy”."))

    def save_site(self):
        try:
            pose = self.app.bridge.fresh_pose()
        except self.core.RobotError as e:
            return self.app.say(str(e), "error")
        self.cfg["build_site"] = {"x": round(pose[0], 2), "y": round(pose[1], 2), "z": round(pose[2], 2)}
        self.app.save()
        self._site_text()
        self.app.say(T("Miejsce budowy zapisane. Zabierz z niego kostkę przed budową."))

    def refresh_models(self):
        models = list_models(self.core)
        current = self.cfg.get("ollama_model") or (models[0] if models else "")
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(models)
        if current in models:
            self.model.setCurrentText(current)
        self.model.blockSignals(False)
        self.model.currentTextChanged.connect(lambda m: self._set("ollama_model", m))
        if not models:
            self.model.setPlaceholderText(T("Ollama nie odpowiada"))

    # ------------------------------------------------------------------ cubes on the table
    def _free_cubes(self):
        """Cubes the robot can take: within reach and not on the build site."""
        site, out = self.cfg["build_site"], []
        for d in self.app.found_idle:
            if d.get("reach") or "xy" not in d:
                continue
            if site and math.hypot(d["xy"][0] - site["x"], d["xy"][1] - site["y"]) < GRID * self.pitch() / 2 + 25:
                continue
            out.append(d)
        return out

    def stock(self):
        counts = {}
        for d in self._free_cubes():
            counts[d["name"]] = counts.get(d["name"], 0) + 1
        return counts

    def pitch(self):
        return float(self.cfg["cube_size"]) + float(self.cfg["cube_gap"])

    def _angle(self, d):
        """Cube angle in the robot frame: mean of the four box edges mapped from the image onto the table."""
        h, w = self.app.work_shape[:2]
        pts = self.app.to_robot(np.array([[q[0] / w, q[1] / h] for q in d["box"]], np.float64))
        sx = sy = 0.0
        for i in range(4):
            e = pts[(i + 1) % 4] - pts[i]
            t = 4.0 * math.atan2(e[1], e[0])                 # a square repeats every 90 degrees
            sx, sy = sx + math.cos(t), sy + math.sin(t)
        return fold_angle(math.degrees(math.atan2(sy, sx)) / 4.0)

    # ------------------------------------------------------------------ proposals
    def ask(self):
        if self._asking:
            return
        if self.app.H is None:
            return self.app.say(T("Najpierw wykonaj kalibrację (zakładka 4)."), "warn")
        stock = self.stock()
        if not stock:
            return self.app.say(T("Nie widzę w polu żadnej kostki w zasięgu robota."), "warn")
        model = self.model.currentText().strip()
        self._asking, self._result = True, None
        self.ask_btn.setText(T("Ollama myśli… to może potrwać minutę"))
        wish = self.wish.text()

        def worker():
            try:
                if not model:
                    raise self.core.RobotError(T("Ollama nie odpowiada albo nie ma żadnego modelu. Sprawdź: ollama list"))
                self._result = ("ok", ask_ollama(self.core, model, stock, wish), stock)
            except self.core.RobotError as e:
                self._result = ("error", str(e), stock)
            except Exception as e:      # noqa: BLE001
                self._result = ("error", T("Nieoczekiwany błąd: {0}").format(e), stock)

        threading.Thread(target=worker, daemon=True).start()

    def _take_result(self):
        kind, payload, stock = self._result
        self._result, self._asking = None, False
        self.ask_btn.setText(T("Zaproponuj budowle"))
        props, seen = [], set()
        if kind == "ok":
            for raw in payload:
                cubes, notes = normalize_structure(raw.get("cubes"), stock)
                if len(cubes) >= 2 and shape_key(cubes) not in seen:
                    seen.add(shape_key(cubes))
                    props.append({"name": str(raw.get("name") or T("Budowla"))[:40], "description": str(raw.get("description") or "")[:200],
                                  "cubes": cubes, "notes": notes, "source": T("Ollama")})
        if kind == "error":
            self.app.say(payload + T(" Pokazuję wzorce wbudowane w program."), "warn")
        elif not props:
            self.app.say(T("Żadna propozycja Ollamy nie nadawała się do zbudowania. Pokazuję wzorce wbudowane w program."), "warn")
        else:
            self.app.say(T("Ollama zaproponowała budowle: {0}.").format(len(props)))
        if len(props) < 3:                                  # top up with templates so there is always a choice
            for t in templates(stock):
                if shape_key(t["cubes"]) not in seen and len(props) < 4:
                    seen.add(shape_key(t["cubes"]))
                    props.append(t)
        self.proposals = props
        self.list.clear()
        for pr in props:
            levels = max(c["z"] for c in pr["cubes"]) + 1
            self.list.addItem(T("{0}  ·  {1}, {2} poz.  ·  {3}").format(pr['name'], kostki(len(pr['cubes'])), levels, pr['source']))
        if props:
            self.list.setCurrentRow(0)

    def _select(self, row):
        if self.job or not (0 <= row < len(self.proposals)):
            return
        pr = self.proposals[row]
        text = pr["description"]
        if pr["notes"]:
            text += ("\n" if text else "") + T("Program poprawił plan: ") + ", ".join(pr["notes"]) + "."
        self.desc.setText(text)
        self.view.show_structure(pr["cubes"])

    # ------------------------------------------------------------------ building
    def _plan(self, cubes):
        """Placing order: level by level from the bottom, within a level from the farthest from the robot. Returns (plan, error)."""
        site, size = self.cfg["build_site"], float(self.cfg["cube_size"])
        if site is None:
            return None, T("Najpierw zapisz miejsce budowy.")
        if self.app.H is None or self.app.z_pick is None:
            return None, T("Najpierw wykonaj kalibrację (zakładka 4).")
        plan = []
        for c in cubes:
            x, y = cube_xy(c, cubes, site, self.pitch())
            z = site["z"] + c["z"] * size
            err = self.core.limit_error(x, y, z)
            if err:
                return None, T("Kostka na poziomie {0} nie mieści się w zasięgu robota: {1}. Przesuń miejsce budowy.").format(c['z'] + 1, err)
            plan.append(dict(c, tx=x, ty=y, tz=z))
        plan.sort(key=lambda c: (c["z"], -math.hypot(c["tx"], c["ty"])))
        top = site["z"] + max(c["z"] for c in cubes) * size + size + 15      # above the highest cube, with a cube under the suction cup
        if top > self.core.Z_MAX:
            return None, T("Budowla jest za wysoka dla robota w tym miejscu (potrzeba Z {0:.0f} mm, limit {1:.0f} mm).").format(top, self.core.Z_MAX)
        return plan, ""

    def start(self):
        row = self.list.currentRow()
        if self.job or not (0 <= row < len(self.proposals)):
            return
        pr = self.proposals[row]
        plan, err = self._plan(pr["cubes"])
        if plan is None:
            return self.app.say(err, "warn")
        if not self.app.robot_live():
            return self.app.say(T("Robot nie odpowiada. Uruchom sterownik w zakładce Start."), "warn")
        ok = QtWidgets.QMessageBox.question(self, T("Budowa"), T("Zbudować „{0}” ({1})?\n\nMiejsce budowy musi być puste, a przestrzeń wokół robota wolna.").format(pr['name'], kostki(len(plan))))
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self.job = {"cubes": plan, "i": 0, "moving": False, "paused": False, "name": pr["name"]}
        self.view.show_structure(plan, done=0, current=0)
        self.app.say(T("Zaczynam budowę: {0}.").format(pr['name']))

    def pause(self, msg):
        if self.job:
            self.job["paused"], self.job["moving"] = True, False
            self.app.say(msg + T(" Kliknij „Wznów” albo „Przerwij budowę”."), "warn")

    def resume(self):
        if self.job and self.job["paused"] and not self.app.runner.busy:
            self.job["paused"] = False

    def abort(self, msg=""):
        if self.job:
            self.job = None
            if self.app.runner.busy:
                self.app.runner.stop()
            if msg:
                self.app.say(msg, "warn")
            self._select(self.list.currentRow())

    def on_stop(self):
        """Called when STOP is pressed."""
        self.pause(T("Zatrzymano. Sprawdź, czy robot nie trzyma kostki (przycisk Przyssawka w zakładce Start)."))

    def _step(self):
        job, app = self.job, self.app
        if job is None:
            return
        if app.runner.busy:
            return
        if job["moving"]:                                   # the move with a cube has just finished
            job["moving"] = False
            if getattr(app.runner, "failed", False):
                return self.pause(T("Ruch się nie powiódł (szczegóły w dzienniku)."))
            job["i"] += 1
            if job["i"] >= len(job["cubes"]):
                self.view.show_structure(job["cubes"])
                app.say(T("Budowla „{0}” gotowa.").format(job['name']))
                self.job = None
                return
        if job["paused"] or time.time() - app.idle_since < 0.9:
            return
        c = job["cubes"][job["i"]]
        self.view.show_structure(job["cubes"], done=job["i"], current=job["i"])
        cands = [d for d in self._free_cubes() if d["name"] == c["color"]]
        if not cands:
            return self.pause(T("Nie widzę wolnej kostki w kolorze {0}. Dołóż ją do pola.").format(LABEL.get(c['color'], c['color'])))
        d = cands[0]
        size = float(self.cfg["cube_size"])
        placed_top = self.cfg["build_site"]["z"] + c["z"] * size        # suction cup height when placing this cube
        zt = min(max(app.z_pick + 70.0, placed_top + size + 15.0), self.core.Z_MAX - 2.0)   # 70 mm, same as in pick and sort
        seq = build_sequence(d["xy"], self._angle(d), (c["tx"], c["ty"]), app.z_pick, c["tz"], zt,
                             invert=self.cfg["rot_invert"], base_comp=self.cfg["rot_base"])
        label = T("Kostka {0} z {1}: {2}, poziom {3}.").format(job['i'] + 1, len(job['cubes']), LABEL.get(c['color'], c['color']), c['z'] + 1)
        if app.submit(seq, label):
            job["moving"] = True
        else:
            self.pause(T("Nie udało się wysłać ruchu do robota."))

    # ------------------------------------------------------------------ refresh
    def tick(self):
        if self._result is not None:
            self._take_result()
        self._step()
        stock = self.stock()
        self.stock_label.setText(T("Kostki do wzięcia: ") + (", ".join(f"{LABEL.get(k, k)} {v}" for k, v in stock.items()) or T("brak")) + ".")
        job, live = self.job, self.app.robot_live()
        self.ask_btn.setEnabled(not self._asking and job is None)
        self.site_btn.setEnabled(live and job is None)
        self.build_btn.setEnabled(job is None and live and not self.app.runner.busy and 0 <= self.list.currentRow() < len(self.proposals))
        self.resume_btn.setEnabled(bool(job and job["paused"]) and not self.app.runner.busy)
        self.abort_btn.setEnabled(job is not None)
        self.list.setEnabled(job is None)
        if job:
            self.progress.setText(T("Budowa „{0}”: postawiono {1} z {2}.").format(job['name'], job['i'], len(job['cubes'])) + (T(" Wstrzymana.") if job["paused"] else ""))
        else:
            self.progress.setText("")

    def overlay(self, p, w, h, label, to_px):
        """The build site on the camera image."""
        site = self.cfg["build_site"]
        if not site or self.app.H is None:
            return
        try:
            u, v = self.app.to_image([[site["x"], site["y"]]])[0]
        except np.linalg.LinAlgError:
            return
        if -0.2 < u < 1.2 and -0.2 < v < 1.2:
            c = to_px((min(max(u, 0.03), 0.97), min(max(v, 0.05), 0.97)))
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(90, 169, 255), 2))
            p.drawRect(QtCore.QRectF(c.x() - 16, c.y() - 16, 32, 32))
            label(T("budowa"), c.x() + 20, c.y() + 8, QtGui.QColor(90, 169, 255))
