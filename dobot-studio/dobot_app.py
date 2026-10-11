#!/usr/bin/env python3
"""
Dobot Studio: one window for working with a Dobot Magician and an OAK camera.

Tabs:
  1. Start        start and stop the robot and camera drivers, homing, log
  2. Area         four clicks on the image; everything outside the work area is ignored
  3. Colours      teach the block colours
  4. Calibration  link the camera image to robot coordinates, set the drop-off spot
  5. Work         pick blocks of a chosen colour
  6. Build        Ollama proposes structures, the robot builds them (see build_tab.py)

Run:
    bash ~/dobot_web/dobot-app.sh

Needs dobot_web.py, colours.py, i18n.py and build_tab.py in the same directory.
Settings are saved in dobot_app.json.

Interface texts are written in Polish in the code and translated by i18n.T().
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

import i18n
from i18n import T
import colours as vision
import build_tab

VERSION = "10.12"

APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "dobot_app.json"
CAM_PARAMS_FILE = APP_DIR / "oak_params.yaml"
LABEL = i18n.ColorNames()      # colour names in the current language
DEFAULTS = {
    "version": 1,
    "colors": {}, "roi": [], "s_min": 70, "v_min": 50, "area_min": 0.0015, "area_max": 0.08,   # same as in colours.py
    "calib": [],            # calibration points: {"px": [u, v] (fractions of the frame), "xy": [x, y] mm, "z": mm}
    "drop": None,           # drop-off spot: {"x", "y", "z"} mm
    "drop_height": 40,      # height above the drop-off spot from which the block is released, mm
    "camera_ip": "169.254.1.222",
    "autostart": False,
    "speed": 50,
    "reach_min": 120,       # robot reach: smallest and largest distance from the base axis, mm
    "reach_max": 315,
    "show_reach": True,
    "lang": "pl",           # interface language: pl or en
    "build_site": None,     # build site: {"x", "y", "z"} mm, suction cup on a cube standing on the table
    "cube_size": 27,        # cube edge, mm
    "cube_gap": 2,          # horizontal gap between cubes, mm
    "rot_invert": False,
    "rot_base": False,
    "ollama_model": "",
}
TRAVEL_ABOVE_PICK = 70      # mm above the pick height at which the arm carries a block
TRAVEL_Z_MAX = 130


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(CONFIG_FILE.read_text())
        for k in DEFAULTS:
            if k in saved:
                cfg[k] = saved[k]
    except (OSError, ValueError):
        old = vision.load_config()                       # first run: take over the settings from colours.py
        for k in ("colors", "roi", "s_min", "v_min"):
            cfg[k] = old[k]
    cfg["colors"] = {k: v for k, v in cfg["colors"].items() if k in vision.PALETTE}
    return cfg


def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps({k: cfg[k] for k in DEFAULTS}, indent=2))
    except OSError as e:
        print(T("Nie udalo sie zapisac ustawien:"), e)


# ----------------------------------------------------------------------------
# Camera -> robot calibration (homography of the plane the blocks lie on)
# ----------------------------------------------------------------------------
def apply_h(H, pts):
    return cv2.perspectiveTransform(np.asarray(pts, np.float64).reshape(-1, 1, 2), H).reshape(-1, 2)


def fit_calibration(points):
    """Returns (H, rms_error_mm, problem_description). H maps frame fractions to mm in the robot frame."""
    if len(points) < 4:
        return None, None, T("Potrzeba co najmniej 4 punktów (jest {0}).").format(len(points))
    src = np.array([p["px"] for p in points], np.float64)
    dst = np.array([p["xy"] for p in points], np.float64)
    if cv2.contourArea(cv2.convexHull(src.astype(np.float32))) < 0.01 or \
            cv2.contourArea(cv2.convexHull(dst.astype(np.float32))) < 900:
        return None, None, T("Punkty leżą zbyt blisko siebie albo w jednej linii. Rozstaw je w rogach pola.")
    H, _ = cv2.findHomography(src, dst, 0)
    if H is None:
        return None, None, T("Nie udało się wyliczyć kalibracji z tych punktów.")
    err = np.linalg.norm(apply_h(H, src) - dst, axis=1)
    return H, float(np.sqrt((err ** 2).mean())), ""


def klocki(n):
    """Count with the noun in the current language: 1 block, 2 blocks."""
    return i18n.count(n, "klocek")


def pick_sequence(x, y, z_pick, drop, drop_height):
    """Action list for the Runner: pick the block at (x, y) and put it down at the drop-off spot."""
    zt = min(max(z_pick, drop["z"]) + TRAVEL_ABOVE_PICK, TRAVEL_Z_MAX)
    return [
        {"type": "move", "z": zt, "up_only": True},                  # straight up first (never down)
        {"type": "move", "x": x, "y": y, "z": zt},
        {"type": "move", "x": x, "y": y, "z": z_pick},
        {"type": "suction", "on": True},
        {"type": "wait", "seconds": 0.6},
        {"type": "move", "x": x, "y": y, "z": zt},
        {"type": "move", "x": drop["x"], "y": drop["y"], "z": zt},
        {"type": "move", "x": drop["x"], "y": drop["y"], "z": min(drop["z"] + drop_height, zt)},
        {"type": "suction", "on": False},
        {"type": "wait", "seconds": 0.5},
        {"type": "move", "x": drop["x"], "y": drop["y"], "z": zt},  # end above the drop-off spot, outside the work area
    ]


# ----------------------------------------------------------------------------
# Drivers started from the app
# ----------------------------------------------------------------------------
class ManagedProcess:
    def __init__(self, name, make_cmd, log):
        self.name, self.make_cmd, self.log = name, make_cmd, log
        self.proc = None
        self.started = 0.0
        self.stopping = False

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def exit_code(self):
        return None if self.proc is None else self.proc.poll()

    def start(self):
        if self.alive():
            return
        env = dict(os.environ)
        env.setdefault("MAGICIAN_TOOL", "suction_cup")
        env["LC_NUMERIC"] = "en_US.UTF-8"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            self.proc = subprocess.Popen(self.make_cmd(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, errors="replace", start_new_session=True, env=env)
        except OSError as e:
            self.log(T("[{0}] Nie udało się uruchomić: {1}").format(T(self.name), e), "error")
            return
        self.started, self.stopping = time.time(), False
        self.log(T("[{0}] uruchamiam…").format(T(self.name)))
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self.log(f"[{T(self.name)}] {line}", "error" if "ERROR" in line or "Traceback" in line else "info")
        code = proc.wait()
        if not self.stopping:
            self.log(T("[{0}] zakończył się sam (kod {1}).").format(T(self.name), code), "error" if code else "warn")

    def stop(self, wait=False):
        if not self.alive():
            return None
        self.stopping = True
        proc = self.proc
        self.log(T("[{0}] zatrzymuję…").format(T(self.name)))

        def group_alive():
            try:
                os.killpg(proc.pid, 0)
                return True
            except (ProcessLookupError, PermissionError):
                return False

        def worker():
            # The signal goes to the whole process group; we wait until the child processes (ROS nodes) are gone too.
            for sig, pause in ((signal.SIGINT, 7), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
                try:
                    os.killpg(proc.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                t_end = time.time() + pause
                while time.time() < t_end and (proc.poll() is None or group_alive()):
                    time.sleep(0.1)
                if proc.poll() is not None and not group_alive():
                    break
            self.log(T("[{0}] zatrzymany.").format(T(self.name)))

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        if wait:
            t.join(14)
        return t


# ----------------------------------------------------------------------------
# Image view
# ----------------------------------------------------------------------------
class ImageView(QtWidgets.QLabel):
    clicked = QtCore.pyqtSignal(float, float)       # click position as fractions of the image width and height

    def __init__(self):
        super().__init__()
        self._pix = None
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setStyleSheet("background:#0b0d10; color:#8b98a5; font-size:15px;")

    def show_image(self, qimg):
        self._pix = QtGui.QPixmap.fromImage(qimg)
        self._refresh()

    def show_text(self, text):
        self._pix = None
        self.setPixmap(QtGui.QPixmap())
        self.setText(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        if self._pix is not None:
            self.setPixmap(self._pix.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def mousePressEvent(self, e):
        if self._pix is None or e.button() != QtCore.Qt.LeftButton:
            return
        shown = self._pix.size().scaled(self.size(), QtCore.Qt.KeepAspectRatio)
        x = (e.x() - (self.width() - shown.width()) / 2) / max(shown.width(), 1)
        y = (e.y() - (self.height() - shown.height()) / 2) / max(shown.height(), 1)
        if 0 <= x <= 1 and 0 <= y <= 1:
            self.clicked.emit(x, y)


def lamp(color):
    return f"background:{color}; border-radius:7px; min-width:14px; max-width:14px; min-height:14px; max-height:14px;"


LAMP = {"off": "#5b6672", "starting": "#f2a900", "on": "#3ecf8e", "error": "#ff5d5d"}


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
class DobotApp(QtWidgets.QMainWindow):
    TAB_START, TAB_ROI, TAB_COLORS, TAB_CALIB, TAB_WORK, TAB_BUILD = range(6)

    def __init__(self, core, bridge, runner=None, lang=None):
        super().__init__()
        self.core, self.bridge = core, bridge
        self.cfg = load_config()
        if lang:
            self.cfg["lang"] = lang
        i18n.set_language(self.cfg["lang"])
        self._log = deque()
        self.runner = runner or core.Runner(bridge, self.log)
        self.runner.vel = self.cfg["speed"] / 100.0
        self._apply_reach()
        self.robot_proc = ManagedProcess("robot", lambda: ["ros2", "launch", "dobot_bringup",
                                                           "dobot_magician_control_system.launch.py"], self._robot_log)
        self._params_missed = set()
        self.camera_proc = ManagedProcess("kamera", self._camera_cmd, self.log)

        self.frame = None               # latest frame (BGR, full resolution)
        self.work_shape = (540, 960, 3)  # size of the working image the detection boxes refer to
        self._last_jpeg = None
        self.found = []                 # detections from the current frame
        self.found_idle = []            # detections from when the robot stood still (arm not in the way)
        self.idle_since = time.time()
        self.roi_clicks = None          # clicks collected while marking the work area, or None
        self.pending_px = None          # remembered block position waiting for the robot pose
        self.H = self.z_pick = self.calib_rms = None
        self.auto = None                # sorting in progress: {"color": name or None, "count": n, "last": (x, y), "repeat": n}

        self.setWindowTitle(T("Dobot Studio  ·  wersja {0}").format(VERSION))
        self.resize(1500, 900)
        self._build_ui()
        self._refit()
        self._rebuild_color_rows()
        self._rebuild_work_buttons()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        if self.cfg["autostart"]:
            QtCore.QTimer.singleShot(300, self.start_all)

    # ------------------------------------------------------------------ helpers
    def log(self, msg, level="info"):
        self._log.append((time.strftime("%H:%M:%S"), msg, level))       # also called from other threads

    # The driver loads its parameter files 5 s after start. On a busy Jetson the node may not be up yet
    # ("Node not found"), which leaves e.g. the axis limits at their tighter defaults. We load them again.
    ROBOT_PARAMS = {
        "axis_limits.yaml": ("/dobot_trajectory_validation_server", "dobot_kinematics"),
        "homing_params.yaml": ("/dobot_homing_srv", "dobot_homing"),
        "PTP_motion_params.yaml": ("/dobot_PTP_server", "dobot_motion"),
    }

    def _robot_log(self, msg, level="info"):
        self.log(msg, level)
        if "Node not found" in msg:
            for name in self.ROBOT_PARAMS:
                if name in msg and name not in self._params_missed:
                    self._params_missed.add(name)
                    threading.Thread(target=self._reload_params, args=([name],), daemon=True).start()
        elif msg.endswith("…"):                     # driver started or stopped from the app
            self._params_missed = set()

    def _reload_params(self, names):
        try:
            from ament_index_python.packages import get_package_share_directory
        except Exception:      # noqa: BLE001
            return
        for name in names:
            node, pkg = self.ROBOT_PARAMS[name]
            ok = False
            try:
                path = os.path.join(get_package_share_directory(pkg), "config", name)
                for _ in range(6):
                    time.sleep(4.0)
                    if name not in self._params_missed or not self.robot_proc.alive():
                        return                      # the driver was stopped in the meantime
                    r = subprocess.run(["ros2", "param", "load", node, path], capture_output=True, text=True, timeout=30)
                    if r.returncode == 0 and "not found" not in (r.stdout + r.stderr):
                        ok = True
                        break
            except Exception:      # noqa: BLE001
                ok = False
            if ok:
                self.log(T("[robot] Parametry sterownika wczytane ponownie: {0}").format(name))
            else:
                self.log(T("[robot] Nie udało się wczytać parametrów sterownika: {0}. Uruchom sterownik ponownie.").format(name), "error")

    def say(self, msg, level="info"):
        self.log(msg, level)

    def save(self):
        save_config(self.cfg)

    def _apply_reach(self):
        """The reach limits from the settings also apply when every move is checked."""
        self.core.R_MIN, self.core.R_MAX = float(self.cfg["reach_min"]), float(self.cfg["reach_max"])

    def _reach_changed(self):
        lo, hi = self.reach_min.value(), self.reach_max.value()
        if lo >= hi:
            return
        self.cfg["reach_min"], self.cfg["reach_max"] = lo, hi
        self._apply_reach()
        self.save()

    def _reach_word(self, d):
        """Short note for the block label saying why the robot will not take it."""
        r = float(np.hypot(d["xy"][0], d["xy"][1]))
        if r < self.cfg["reach_min"]:
            return T("za blisko robota")
        if r > self.cfg["reach_max"]:
            return T("za daleko")
        return T("zła wysokość chwytu")

    def robot_live(self):
        age = self.bridge.pose_age()
        return age is not None and age < 2.0

    def camera_live(self):
        return self.bridge.frame() is not None

    def _camera_cmd(self):
        CAM_PARAMS_FILE.write_text(
            '/oak:\n  ros__parameters:\n    camera:\n'
            f'      i_ip: "{self.cfg["camera_ip"].strip()}"\n      i_pipeline_type: RGB\n      i_nn_type: none\n')
        self.log(T("[kamera] adres w ustawieniach: „{0}”").format(self.cfg['camera_ip']) if self.cfg["camera_ip"].strip()
                 else T("[kamera] bez adresu: łączę z pierwszą znalezioną kamerą"))
        return ["ros2", "launch", "depthai_ros_driver", "camera.launch.py", f"params_file:={CAM_PARAMS_FILE}"]

    def submit(self, actions, label=None):
        try:
            self.runner.submit(actions, label)
            return True
        except self.core.Busy:
            self.say(T("Robot wykonuje jeszcze poprzedni ruch."), "warn")
        except self.core.RobotError as e:
            self.say(str(e), "error")
        return False

    # ------------------------------------------------------------------ window layout
    def _build_ui(self):
        W = QtWidgets
        central = W.QWidget()
        self.setCentralWidget(central)
        root = W.QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        left = W.QVBoxLayout()
        self.view = ImageView()
        self.view.clicked.connect(self.on_image_click)
        left.addWidget(self.view, 1)
        self.message = W.QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("font-size:14px; padding:4px 2px;")
        left.addWidget(self.message)
        root.addLayout(left, 1)

        right = W.QVBoxLayout()
        self.stop_btn = W.QPushButton("STOP")
        self.stop_btn.setStyleSheet("background:#e5383b; color:white; font-weight:bold; font-size:18px; padding:12px; border-radius:8px;")
        self.stop_btn.clicked.connect(self.stop_all_motion)
        right.addWidget(self.stop_btn)

        self.robot_lamp, self.camera_lamp = W.QLabel(), W.QLabel()
        self.robot_state, self.camera_state = W.QLabel(T("Robot: wyłączony")), W.QLabel(T("Kamera: wyłączona"))
        for lamp_w, text in ((self.robot_lamp, self.robot_state), (self.camera_lamp, self.camera_state)):
            status = W.QHBoxLayout()
            status.addWidget(lamp_w)
            status.addWidget(text, 1)
            right.addLayout(status)
        self.pose_label = W.QLabel(T("Pozycja: —"))
        self.pose_label.setStyleSheet("font-family:monospace;")
        right.addWidget(self.pose_label)

        self.tabs = W.QTabWidget()
        self.tabs.setUsesScrollButtons(False)
        for title, builder in ((T("Start"), self._tab_start), (T("Pole"), self._tab_roi), (T("Kolory"), self._tab_colors),
                               (T("Kalibracja"), self._tab_calib), (T("Praca"), self._tab_work), (T("Budowa"), self._tab_build)):
            page = W.QWidget()
            builder(W.QVBoxLayout(page))
            scroll = W.QScrollArea()                     # on a low screen the tab scrolls instead of being squeezed
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(W.QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
        self.tabs.currentChanged.connect(self._tab_changed)
        right.addWidget(self.tabs, 1)
        left.insertWidget(1, self.build_tab.view)          # structure preview below the image, visible on the Build tab
        self.build_tab.view.setFixedHeight(300)
        self.build_tab.view.hide()
        holder = W.QWidget()
        holder.setLayout(right)
        holder.setFixedWidth(540)
        root.addWidget(holder)

    def _hint(self, layout, text):
        lab = QtWidgets.QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("color:#aab4be;")
        layout.addWidget(lab)
        return lab

    def _button(self, text, slot, layout=None):
        b = QtWidgets.QPushButton(text)
        b.clicked.connect(slot)
        if layout is not None:
            layout.addWidget(b)
        return b

    def _tab_start(self, lay):
        W = QtWidgets
        for title, start, stop in ((T("Sterownik robota"), self.start_robot, self.robot_proc.stop),
                                   (T("Sterownik kamery"), self.start_camera, self.camera_proc.stop)):
            box = W.QGroupBox(title)
            row = W.QHBoxLayout(box)
            self._button(T("Uruchom"), start, row)
            self._button(T("Zatrzymaj"), lambda _=False, s=stop: s(), row)
            lay.addWidget(box)
        row = W.QHBoxLayout()
        self.homing_btn = self._button(T("Bazowanie"), self.do_homing, row)
        self.home_btn = self._button(T("Pozycja domowa"), lambda: self.submit([{"type": "home"}]), row)
        self.suction_btn = self._button(T("Przyssawka"), self.toggle_suction, row)
        lay.addLayout(row)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel(T("Adres kamery")))
        self.ip_edit = W.QLineEdit(self.cfg["camera_ip"])
        self.ip_edit.setPlaceholderText(T("puste = pierwsza znaleziona kamera"))
        self.ip_edit.editingFinished.connect(self._ip_changed)
        row.addWidget(self.ip_edit)
        lay.addLayout(row)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel("Język / Language"))
        self.lang_box = W.QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.lang_box.addItem(name, code)
        self.lang_box.setCurrentIndex(self.lang_box.findData(i18n.language()))
        self.lang_box.currentIndexChanged.connect(lambda _i: self.change_language(self.lang_box.currentData()))
        row.addWidget(self.lang_box)
        row.addStretch(1)
        lay.addLayout(row)
        self.autostart_box = W.QCheckBox(T("Uruchamiaj oba sterowniki automatycznie przy starcie programu"))
        self.autostart_box.setChecked(bool(self.cfg["autostart"]))
        self.autostart_box.toggled.connect(lambda v: (self.cfg.__setitem__("autostart", bool(v)), self.save()))
        lay.addWidget(self.autostart_box)
        self._hint(lay, T("Sterownik robota startuje około 20 sekund. Po włączeniu robota wykonaj bazowanie, przy pustej przestrzeni wokół ramienia. Zamknięcie programu zatrzymuje oba sterowniki."))
        self.log_view = W.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(600)
        self.log_view.setStyleSheet("font-family:monospace; font-size:11px;")
        lay.addWidget(self.log_view, 1)

    def _tab_roi(self, lay):
        self._hint(lay, T("Pole robocze to obszar stołu, w którym program szuka klocków. Wszystko poza nim jest ignorowane.\n\nKliknij „Zaznacz pole”, a potem cztery rogi pola na obrazie, w dowolnej kolejności."))
        self.roi_btn = self._button(T("Zaznacz pole"), self.start_roi, lay)
        self._button(T("Usuń pole"), self.clear_roi, lay)
        self.roi_state = QtWidgets.QLabel("")
        lay.addWidget(self.roi_state)
        lay.addStretch(1)

    def _tab_colors(self, lay):
        W = QtWidgets
        self._hint(lay, T("Połóż w polu roboczym JEDEN klocek i kliknij „Naucz” przy jego kolorze. Program szuka tylko nauczonych kolorów."))
        self.color_rows = W.QVBoxLayout()
        lay.addLayout(self.color_rows)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel(T("Próg nasycenia")))
        self.sat_slider = W.QSlider(QtCore.Qt.Horizontal)
        self.sat_slider.setRange(10, 250)
        self.sat_slider.setValue(int(self.cfg["s_min"]))
        self.sat_value = W.QLabel(str(self.cfg["s_min"]))
        self.sat_slider.valueChanged.connect(self._sat_changed)
        row.addWidget(self.sat_slider, 1)
        row.addWidget(self.sat_value)
        lay.addLayout(row)
        self._hint(lay, T("Wyżej: mniej fałszywych wykryć. Niżej: łapie bledsze kolory."))
        self.mask_box = W.QCheckBox(T("Pokaż, co program uznaje za kolorowe"))
        lay.addWidget(self.mask_box)
        lay.addStretch(1)

    def _tab_calib(self, lay):
        W = QtWidgets
        self._hint(lay, T("Powtórz dla 4 miejsc blisko rogów pola, najlepiej dodaj piąte na środku.\nA. Połóż jeden klocek tak, żeby ramię go nie zasłaniało, i kliknij przycisk 1.\nB. Ustaw przyssawkę na środku klocka: ręką z wciśniętym Unlock albo przyciskami.\nC. Kliknij przycisk 2."))
        row = W.QHBoxLayout()
        self.calib_a = self._button(T("1. Zapamiętaj klocek"), self.calib_remember, row)
        self.calib_b = self._button(T("2. Zapisz pozycję robota"), self.calib_save_point, row)
        lay.addLayout(row)

        jog = W.QGridLayout()
        self.jog_step = W.QComboBox()
        self.jog_step.addItems(["1 mm", "5 mm", "10 mm", "20 mm"])
        self.jog_step.setCurrentIndex(1)
        jog.addWidget(W.QLabel(T("Krok")), 0, 0)
        jog.addWidget(self.jog_step, 0, 1, 1, 2)
        self.jog_buttons = []
        for r, (axis, minus, plus) in enumerate((("x", T("X −  tył"), T("X +  przód")), ("y", T("Y −  prawo"), T("Y +  lewo")),
                                                 ("z", T("Z −  dół"), T("Z +  góra"))), start=1):
            for c, (text, sign) in enumerate(((minus, -1), (plus, 1))):
                b = self._button(text, lambda _=False, a=axis, s=sign: self.jog(a, s))
                jog.addWidget(b, r, c + 1)
                self.jog_buttons.append(b)
        lay.addLayout(jog)

        row = W.QHBoxLayout()
        self._button(T("Usuń ostatni punkt"), self.calib_undo, row)
        self._button(T("Wyczyść kalibrację"), self.calib_clear, row)
        lay.addLayout(row)
        self.calib_state = W.QLabel("")
        self.calib_state.setWordWrap(True)
        lay.addWidget(self.calib_state)
        self.calib_test = self._button(T("Sprawdź: najedź nad klocek"), self.calib_check, lay)

        reach = W.QGroupBox(T("Zasięg robota"))
        rl = W.QVBoxLayout(reach)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel(T("Od")))
        self.reach_min, self.reach_max = W.QSpinBox(), W.QSpinBox()
        for spin, key, lo, hi in ((self.reach_min, "reach_min", 60, 250), (self.reach_max, "reach_max", 200, 340)):
            spin.setRange(lo, hi)
            spin.setSingleStep(5)
            spin.setSuffix(" mm")
            spin.setValue(int(self.cfg[key]))
            spin.valueChanged.connect(lambda _v: self._reach_changed())
        row.addWidget(self.reach_min)
        row.addWidget(W.QLabel(T("do")))
        row.addWidget(self.reach_max)
        row.addWidget(W.QLabel(T("od osi podstawy")))
        row.addStretch(1)
        rl.addLayout(row)
        self.reach_box = W.QCheckBox(T("Pokaż zasięg na obrazie (zielony pierścień)"))
        self.reach_box.setChecked(bool(self.cfg["show_reach"]))
        self.reach_box.toggled.connect(lambda v: (self.cfg.__setitem__("show_reach", bool(v)), self.save()))
        rl.addWidget(self.reach_box)
        self._hint(rl, T("Pierścień pojawia się po kalibracji. Jeśli sterownik odrzuca ruchy przy krawędzi, zmniejsz górną granicę."))
        lay.addWidget(reach)

        box = W.QGroupBox(T("Miejsce odkładania"))
        b = W.QVBoxLayout(box)
        self._hint(b, T("Połóż klocek tam, gdzie robot ma odkładać (poza polem roboczym), ustaw na nim przyssawkę i kliknij."))
        self.drop_btn = self._button(T("Zapisz miejsce odkładania"), self.save_drop, b)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel(T("Puść klocek z wysokości")))
        self.drop_h = W.QSpinBox()
        self.drop_h.setRange(0, 80)
        self.drop_h.setSuffix(" mm")
        self.drop_h.setValue(int(self.cfg["drop_height"]))
        self.drop_h.valueChanged.connect(lambda v: (self.cfg.__setitem__("drop_height", int(v)), self.save()))
        row.addWidget(self.drop_h)
        b.addLayout(row)
        self.drop_state = W.QLabel("")
        b.addWidget(self.drop_state)
        lay.addWidget(box)
        lay.addStretch(1)

    def _tab_work(self, lay):
        W = QtWidgets
        self._hint(lay, T("Robot podnosi klocek wybranego koloru i odkłada go w miejscu odkładania. Zielony pierścień to zasięg robota: klocki poza nim są pomijane."))
        self.work_rows = W.QVBoxLayout()
        lay.addLayout(self.work_rows)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel(T("Prędkość")))
        self.speed = W.QSlider(QtCore.Qt.Horizontal)
        self.speed.setRange(10, 100)
        self.speed.setValue(int(self.cfg["speed"]))
        self.speed_value = W.QLabel(f"{self.cfg['speed']}%")
        self.speed.valueChanged.connect(self._speed_changed)
        row.addWidget(self.speed, 1)
        row.addWidget(self.speed_value)
        lay.addLayout(row)
        self.work_state = W.QLabel("")
        self.work_state.setWordWrap(True)
        lay.addWidget(self.work_state)
        lay.addStretch(1)

    def _tab_build(self, lay):
        self.build_tab = build_tab.BuildTab(self)
        lay.addWidget(self.build_tab)

    def to_robot(self, norm_pts):
        """Frame fractions -> mm in the robot frame."""
        return apply_h(self.H, norm_pts)

    def to_image(self, robot_pts):
        """mm in the robot frame -> frame fractions."""
        return apply_h(np.linalg.inv(self.H), robot_pts)

    # ------------------------------------------------------------------ rows that depend on the colours
    @staticmethod
    def _clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)                        # disappears at once, not on the next pass of the event loop
                w.deleteLater()
            elif item.layout():
                DobotApp._clear(item.layout())

    def _rebuild_color_rows(self):
        W = QtWidgets
        self._clear(self.color_rows)
        for name in vision.PALETTE:
            row = W.QHBoxLayout()
            sw = W.QLabel()
            learned = self.cfg["colors"].get(name)
            if learned:
                rgb = cv2.cvtColor(np.uint8([[[learned["hue"], max(learned["sat"], 120), 225]]]), cv2.COLOR_HSV2RGB)[0, 0]
                sw.setStyleSheet(f"background:rgb({rgb[0]},{rgb[1]},{rgb[2]}); border-radius:4px;")
            else:
                sw.setStyleSheet("border:1px dashed #5b6672; border-radius:4px;")
            sw.setFixedSize(26, 26)
            row.addWidget(sw)
            row.addWidget(W.QLabel(LABEL[name] + (T("   (odcień {0})").format(learned['hue']) if learned else T("   nie nauczony"))), 1)
            self._button(T("Naucz"), lambda _=False, n=name: self.teach_color(n), row)
            rm = self._button(T("Usuń"), lambda _=False, n=name: self.forget_color(n), row)
            rm.setEnabled(bool(learned))
            self.color_rows.addLayout(row)

    def _rebuild_work_buttons(self):
        self._clear(self.work_rows)
        self.work_buttons = []
        for name in self.cfg["colors"]:
            b = self._button(T("Zabierz jeden: {0}").format(LABEL[name]), lambda _=False, n=name: self.pick_one(n), self.work_rows)
            b2 = self._button(T("Zabierz wszystkie: {0}").format(LABEL[name]), lambda _=False, n=name: self.start_auto(n), self.work_rows)
            self.work_buttons += [b, b2]
        if self.cfg["colors"]:
            self.work_buttons.append(self._button(T("Zabierz wszystkie klocki"), lambda: self.start_auto(None), self.work_rows))

    # ------------------------------------------------------------------ Start tab
    def change_language(self, code):
        """Switches the language and rebuilds the window. Settings, drivers and calibration stay."""
        if code == i18n.language():
            return
        if self.runner.busy or self.build_tab.job is not None or self.auto is not None:
            self.lang_box.blockSignals(True)
            self.lang_box.setCurrentIndex(self.lang_box.findData(i18n.language()))
            self.lang_box.blockSignals(False)
            return self.say(T("Zmiana języka jest możliwa, gdy robot stoi i nie trwa budowa."), "warn")
        self.cfg["lang"] = code
        self.save()
        i18n.set_language(code)
        QtCore.QTimer.singleShot(0, self._rebuild_ui)      # after the list click handler has returned

    def _rebuild_ui(self):
        tab = self.tabs.currentIndex()
        log_text = self.log_view.toPlainText()
        self.roi_clicks = self.pending_px = None
        old = self.centralWidget()
        self.setWindowTitle(T("Dobot Studio  ·  wersja {0}").format(VERSION))
        self._build_ui()
        if old is not None and old is not self.centralWidget():
            old.hide()
            old.setParent(None)
            old.deleteLater()
        self.log_view.setPlainText(log_text)
        self._refit()
        self._rebuild_color_rows()
        self._rebuild_work_buttons()
        self.tabs.setCurrentIndex(tab)
        self.message.setText("")

    def start_robot(self):
        if self.robot_live() and not self.robot_proc.alive():
            return self.say(T("Sterownik robota już działa, uruchomiony poza programem (np. w terminalu). Nie uruchamiam drugiego."), "warn")
        self.robot_proc.start()

    def start_camera(self):
        if self.camera_live() and not self.camera_proc.alive():
            return self.say(T("Sterownik kamery już działa, uruchomiony poza programem (np. w terminalu). Nie uruchamiam drugiego."), "warn")
        self.camera_proc.start()

    def start_all(self):
        self.start_robot()
        self.start_camera()

    def _ip_changed(self):
        ip = "".join(self.ip_edit.text().split())            # no spaces or invisible whitespace
        self.ip_edit.setText(ip)
        if ip != self.cfg["camera_ip"]:
            self.cfg["camera_ip"] = ip
            self.save()
            self.say(T("Adres kamery zapisany. Zadziała po ponownym uruchomieniu sterownika kamery.") if ip else
                     T("Adres kamery usunięty: sterownik połączy się z pierwszą kamerą, jaką znajdzie."))

    def do_homing(self):
        ok = QtWidgets.QMessageBox.question(self, T("Bazowanie"), T("Bazowanie obraca ramię w pełnym zakresie.\nCzy przestrzeń wokół robota jest pusta?"))
        if ok == QtWidgets.QMessageBox.Yes:
            self.submit([{"type": "homing"}], T("Bazowanie…"))

    def toggle_suction(self):
        self.submit([{"type": "suction", "on": not self.runner.suction_on}])

    def stop_all_motion(self):
        self.auto = None
        self.runner.stop()
        self.build_tab.on_stop()

    # ------------------------------------------------------------------ Area tab
    def start_roi(self):
        if self.frame is None:
            return self.say(T("Brak obrazu z kamery. Uruchom sterownik kamery w zakładce Start."), "warn")
        self.roi_clicks = []
        self.say(T("Kliknij pierwszy róg pola roboczego na obrazie."))

    def clear_roi(self):
        self.cfg["roi"], self.roi_clicks = [], None
        self.save()
        self.say(T("Usunięto pole robocze. Program analizuje cały kadr."))

    def on_image_click(self, fx, fy):
        if self.roi_clicks is None:
            return
        self.roi_clicks.append([fx, fy])
        if len(self.roi_clicks) < 4:
            return self.say(T("Kliknij róg {0} z 4.").format(len(self.roi_clicks) + 1))
        self.cfg["roi"] = [[round(float(x), 4), round(float(y), 4)] for x, y in vision.order_corners(self.roi_clicks)]
        self.roi_clicks = None
        self.save()
        self.say(T("Pole robocze zapisane."))

    # ------------------------------------------------------------------ Colours tab
    def teach_color(self, name):
        if self.frame is None:
            return self.say(T("Brak obrazu z kamery."), "warn")
        sample = vision.sample_block(self.frame, self.cfg)
        if sample is None:
            return self.say(T("Nie widzę klocka w polu roboczym. Połóż jeden i spróbuj ponownie."), "warn")
        close = [n for n, c in self.cfg["colors"].items() if n != name and int(vision.hue_dist(sample[0], c["hue"])) < 8]
        self.cfg["colors"][name] = {"hue": int(sample[0]), "sat": int(sample[1])}
        self.save()
        self._rebuild_color_rows()
        self._rebuild_work_buttons()
        msg = T("Nauczono: {0} (odcień {1}, nasycenie {2}).").format(LABEL[name], sample[0], sample[1])
        if close:
            msg += T(" Uwaga: bardzo blisko koloru {0}, będą się mylić.").format(LABEL[close[0]])
        self.say(msg, "warn" if close else "info")

    def forget_color(self, name):
        self.cfg["colors"].pop(name, None)
        self.save()
        self._rebuild_color_rows()
        self._rebuild_work_buttons()

    def _sat_changed(self, v):
        self.cfg["s_min"] = int(v)
        self.sat_value.setText(str(v))
        self.save()

    # ------------------------------------------------------------------ Calibration tab
    def _refit(self):
        pts = self.cfg["calib"]
        self.H, self.calib_rms, problem = fit_calibration(pts)
        self.z_pick = float(np.mean([p["z"] for p in pts])) if pts else None
        if self.H is None:
            text = T("Punkty: {0}. {1}").format(len(pts), problem)
        elif len(pts) == 4:
            text = (T("Kalibracja gotowa z 4 punktów. Przy 4 punktach nie da się policzyć błędu: dodaj piąty punkt albo użyj przycisku „Sprawdź”."))
        else:
            text = T("Kalibracja gotowa z {0} punktów. Średni błąd dopasowania: {1:.1f} mm.").format(len(pts), self.calib_rms)
            if self.calib_rms > 5:
                text += T(" To dużo: któryś punkt jest niedokładny. Wyczyść i powtórz.")
        if self.z_pick is not None:
            text += T("\nWysokość chwytu: Z = {0:.1f} mm.").format(self.z_pick)
        self.calib_state.setText(text)
        d = self.cfg["drop"]
        self.drop_state.setText(T("Zapisane: X {0:.0f}, Y {1:.0f}, Z {2:.0f} mm").format(d['x'], d['y'], d['z']) if d else T("Nie ustawiono."))

    def calib_remember(self):
        if self.runner.busy:
            return self.say(T("Poczekaj, aż robot skończy ruch."), "warn")
        if not self.cfg["colors"]:
            return self.say(T("Najpierw naucz co najmniej jeden kolor w zakładce Kolory."), "warn")
        if len(self.found) != 1:
            return self.say(T("W polu musi być widoczny dokładnie jeden klocek (widzę {0}). Sprawdź też, czy ramię go nie zasłania.").format(len(self.found)), "warn")
        self.pending_px = list(self.found[0]["norm"])
        self.say(T("Położenie klocka zapamiętane. Teraz ustaw przyssawkę na środku klocka i kliknij „2. Zapisz pozycję robota”."))

    def calib_save_point(self):
        if self.pending_px is None:
            return self.say(T("Najpierw kliknij „1. Zapamiętaj klocek”."), "warn")
        try:
            pose = self.bridge.fresh_pose()
        except self.core.RobotError as e:
            return self.say(str(e), "error")
        self.cfg["calib"].append({"px": [round(v, 5) for v in self.pending_px],
                                  "xy": [round(pose[0], 2), round(pose[1], 2)], "z": round(pose[2], 2)})
        self.pending_px = None
        self.save()
        self._refit()
        self.say(T("Punkt {0} zapisany. Podnieś ramię, przełóż klocek w kolejne miejsce i powtórz.").format(len(self.cfg['calib'])))

    def calib_undo(self):
        if self.cfg["calib"]:
            self.cfg["calib"].pop()
            self.save()
            self._refit()

    def calib_clear(self):
        self.cfg["calib"], self.pending_px = [], None
        self.save()
        self._refit()

    def jog(self, axis, sign):
        step = float(self.jog_step.currentText().split()[0])
        self.submit([{"type": "move_rel", "d" + axis: sign * step}])

    def calib_check(self):
        target = self._target(None)
        if target:
            x, y = float(target["xy"][0]), float(target["xy"][1])
            zt = min(self.z_pick + TRAVEL_ABOVE_PICK, TRAVEL_Z_MAX)
            self.submit([{"type": "move", "z": zt}, {"type": "move", "x": x, "y": y, "z": zt},
                         {"type": "move", "x": x, "y": y, "z": self.z_pick + 15}],
                        T("Sprawdzenie: najeżdżam 15 mm nad klocek ({0}).").format(LABEL[target['name']]))

    def save_drop(self):
        try:
            pose = self.bridge.fresh_pose()
        except self.core.RobotError as e:
            return self.say(str(e), "error")
        self.cfg["drop"] = {"x": round(pose[0], 2), "y": round(pose[1], 2), "z": round(pose[2], 2)}
        self.save()
        self._refit()
        self.say(T("Miejsce odkładania zapisane."))

    # ------------------------------------------------------------------ Work tab
    def _speed_changed(self, v):
        self.cfg["speed"] = int(v)
        self.runner.vel = v / 100.0
        self.speed_value.setText(f"{v}%")
        self.save()

    def _target(self, color, quiet=False):
        """First reachable block of the given colour (None = any), from the image taken while the robot stood still."""
        if self.H is None:
            if not quiet:
                self.say(T("Najpierw wykonaj kalibrację (zakładka 4)."), "warn")
            return None
        if not self.robot_live():
            if not quiet:
                self.say(T("Robot nie odpowiada. Uruchom sterownik w zakładce Start."), "warn")
            return None
        cands = [d for d in self.found_idle if color in (None, d["name"])]
        ok = [d for d in cands if not d.get("reach")]
        if not ok and not quiet:
            self.say(T("Nie widzę takiego klocka w polu.") if not cands else
                     T("Klocek jest poza zasięgiem robota: ") + cands[0]["reach"] + ".", "warn")
        return ok[0] if ok else None

    def _pick(self, target):
        if self.cfg["drop"] is None:
            self.say(T("Najpierw ustaw miejsce odkładania (zakładka 4)."), "warn")
            return False
        x, y = target["xy"]
        return self.submit(pick_sequence(float(x), float(y), self.z_pick, self.cfg["drop"], self.cfg["drop_height"]),
                           T("Zabieram klocek: {0} z X {1:.0f}, Y {2:.0f}.").format(LABEL[target['name']], x, y))

    def pick_one(self, color):
        target = self._target(color)
        if target:
            self._pick(target)

    def start_auto(self, color):
        if self._target(color) and self.cfg["drop"] is not None:
            self.auto = {"color": color, "count": 0, "last": None, "repeat": 0}
        elif self.cfg["drop"] is None and self.H is not None:
            self.say(T("Najpierw ustaw miejsce odkładania (zakładka 4)."), "warn")

    def _auto_step(self):
        """Called on every tick: once the robot is still and the image has refreshed, takes the next block."""
        a = self.auto
        if a is None or self.runner.busy or time.time() - self.idle_since < 0.8:
            return
        target = self._target(a["color"], quiet=True)
        if target is None:
            self.auto = None
            return self.say(T("Koniec: zabrano {0}.").format(klocki(a['count'])) if a["count"] else T("Nie ma czego zabrać."))
        xy = np.array(target["xy"])
        a["repeat"] = a["repeat"] + 1 if a["last"] is not None and np.linalg.norm(xy - a["last"]) < 8 else 0
        if a["repeat"] >= 2 or a["count"] >= 40:
            self.auto = None
            return self.say(T("Przerywam: ten sam klocek nie dał się podnieść trzy razy z rzędu. Sprawdź przyssawkę i wysokość chwytu.") if a["repeat"] >= 2 else T("Przerywam po 40 klockach."), "warn")
        a["last"] = xy
        if self._pick(target):
            a["count"] += 1
        else:
            self.auto = None

    # ------------------------------------------------------------------ refresh loop
    def _tab_changed(self, i):
        self.roi_clicks = None
        self.build_tab.view.setVisible(i == self.TAB_BUILD)

    def _drain_log(self):
        last = None
        while self._log:
            t, msg, level = self._log.popleft()
            self.log_view.appendPlainText(f"{t}  {msg}")
            if not msg.startswith("["):                      # driver messages go to the log only
                last = (msg, level)
        if last:
            color = {"error": "#ff7b7b", "warn": "#f2c14e"}.get(last[1], "#dfe4e8")
            self.message.setStyleSheet(f"font-size:14px; padding:4px 2px; color:{color};")
            self.message.setText(last[0])

    def _proc_state(self, proc, live, word):
        """(lamp key, description) for a driver."""
        if live:
            return "on", T("działa") + ("" if proc.alive() else T(" (uruchomiony poza programem)"))
        if proc.alive():
            return ("starting", T("uruchamia się…")) if time.time() - proc.started < 60 else ("error", T("nie odpowiada"))
        code = proc.exit_code()
        if code not in (None, 0) and not proc.stopping:
            return "error", T("błąd, zobacz dziennik")
        return "off", word

    def tick(self):
        self._drain_log()
        robot_live = self.robot_live()
        if self.runner.busy:
            self.idle_since = time.time()

        jpeg = self.bridge.frame()
        if jpeg is None:
            self.frame, self._last_jpeg, self.found = None, None, []
            self.view.show_text(T("Brak obrazu z kamery.\nUruchom sterownik kamery w zakładce Start."))
        else:
            if jpeg is not self._last_jpeg:
                img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    self.frame, self._last_jpeg = img, jpeg
            if self.frame is not None:
                small, found, mask = vision.detect(self.frame, self.cfg)
                self.work_shape = small.shape
                h, w = small.shape[:2]
                for d in found:
                    d["norm"] = (d["center"][0] / w, d["center"][1] / h)
                    if self.H is not None:
                        d["xy"] = tuple(apply_h(self.H, [d["norm"]])[0])
                        d["reach"] = self.core.limit_error(d["xy"][0], d["xy"][1], self.z_pick)
                self.found = found
                if not self.runner.busy and time.time() - self.idle_since > 0.5:
                    self.found_idle = found
                self.view.show_image(self._render(small, found, mask))

        key, text = self._proc_state(self.robot_proc, robot_live, T("wyłączony"))
        self.robot_lamp.setStyleSheet(lamp(LAMP[key]))
        self.robot_state.setText(T("Robot: ") + text)
        key, text = self._proc_state(self.camera_proc, jpeg is not None, T("wyłączona"))
        self.camera_lamp.setStyleSheet(lamp(LAMP[key]))
        self.camera_state.setText(T("Kamera: ") + text)
        pose = self.bridge.pose() if robot_live else None
        self.pose_label.setText(T("Pozycja: X {:.1f}  Y {:.1f}  Z {:.1f} mm").format(*pose[:3]) if pose else T("Pozycja: —"))

        free = robot_live and not self.runner.busy
        for b in [self.homing_btn, self.home_btn, self.suction_btn, self.calib_test, *self.jog_buttons, *self.work_buttons]:
            b.setEnabled(free)
        self.suction_btn.setText(T("Przyssawka: ") + (T("wł.") if self.runner.suction_on else T("wył.")))
        self.calib_b.setEnabled(robot_live and self.pending_px is not None)
        self.drop_btn.setEnabled(robot_live)
        self.roi_btn.setText(T("Zaznaczanie… (kliknij rogi na obrazie)") if self.roi_clicks is not None else T("Zaznacz pole"))
        self.roi_state.setText(T("Pole jest ustawione.") if len(self.cfg["roi"]) == 4 else T("Pole nie jest ustawione: program analizuje cały kadr."))
        counts = ", ".join(f"{LABEL[n]}: {sum(1 for d in self.found if d['name'] == n)}" for n in self.cfg["colors"])
        busy = (self.runner.current or T("ruch…")) if self.runner.busy else ""
        self.work_state.setText((T("Widzę: {0}.").format(counts) if counts else T("Brak nauczonych kolorów.")) +
                                (T("\nRobot: {0}").format(busy) if busy else "") + (T("\nSortowanie w toku.") if self.auto else ""))
        self._auto_step()
        self.build_tab.tick()

    # ------------------------------------------------------------------ drawing the overlay
    def _render(self, small, found, mask):
        tab = self.tabs.currentIndex()
        img = small.copy()
        inside = vision.roi_mask(self.cfg, img.shape)
        img[inside == 0] = (img[inside == 0] * 0.35).astype(np.uint8)
        if tab == self.TAB_COLORS and self.mask_box.isChecked():
            img[mask == 0] = (img[mask == 0] * 0.25).astype(np.uint8)
        show_reach = self.H is not None and self.cfg["show_reach"] and tab != self.TAB_COLORS
        reach_state = self._tint_reach(img) if show_reach else None
        h, w = img.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()
        p = QtGui.QPainter(qimg)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        font = QtGui.QFont()
        font.setPixelSize(15)
        p.setFont(font)

        def label(text, x, y, color):
            rect = p.fontMetrics().boundingRect(text).adjusted(-5, -3, 5, 3)
            rect.moveTo(int(min(max(x, 2), w - rect.width() - 2)), int(min(max(y - rect.height(), 2), h - rect.height() - 2)))
            p.fillRect(rect, QtGui.QColor(18, 20, 24, 220))
            p.setPen(color)
            p.drawText(rect, QtCore.Qt.AlignCenter, text)

        def to_px(norm):
            return QtCore.QPointF(norm[0] * w, norm[1] * h)

        if show_reach:
            self._draw_reach(p, w, h, label, reach_state)

        if len(self.cfg["roi"]) == 4:
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1.5))
            p.drawPolygon(QtGui.QPolygonF([to_px(c) for c in self.cfg["roi"]]))
        for c in self.roi_clicks or []:
            p.setBrush(QtGui.QColor(80, 220, 255))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(to_px(c), 6, 6)
        p.setBrush(QtCore.Qt.NoBrush)

        for d in found:
            b, g, r = vision.DRAW[d["name"]]
            out = bool(d.get("reach"))
            color = QtGui.QColor(150, 158, 166) if out else QtGui.QColor(r, g, b)
            p.setPen(QtGui.QPen(color, 2.5, QtCore.Qt.DashLine if out else QtCore.Qt.SolidLine))
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(float(x), float(y)) for x, y in d["box"]]))
            text = LABEL[d["name"]] + ("  ·  " + self._reach_word(d) if out else "")
            if tab == self.TAB_COLORS:
                text += T("  ·  odcień {0}").format(d['hue'])
            label(text, d["box"][:, 0].min(), d["box"][:, 1].min() - 6, color)

        if tab == self.TAB_CALIB:
            for i, pt in enumerate(self.cfg["calib"], start=1):
                c = to_px(pt["px"])
                p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
                p.drawEllipse(c, 9, 9)
                label(str(i), c.x() + 12, c.y() + 8, QtGui.QColor(255, 255, 255))
            if self.pending_px is not None:
                c = to_px(self.pending_px)
                p.setPen(QtGui.QPen(QtGui.QColor(80, 220, 255), 2))
                p.drawLine(QtCore.QPointF(c.x() - 16, c.y()), QtCore.QPointF(c.x() + 16, c.y()))
                p.drawLine(QtCore.QPointF(c.x(), c.y() - 16), QtCore.QPointF(c.x(), c.y() + 16))
                label(T("tu ustaw przyssawkę"), c.x() + 14, c.y() - 12, QtGui.QColor(80, 220, 255))
        if tab == self.TAB_BUILD:
            self.build_tab.overlay(p, w, h, label, to_px)
        if tab in (self.TAB_CALIB, self.TAB_WORK) and self.H is not None and self.cfg["drop"]:
            try:
                u, v = apply_h(np.linalg.inv(self.H), [[self.cfg["drop"]["x"], self.cfg["drop"]["y"]]])[0]
                if -0.2 < u < 1.2 and -0.2 < v < 1.2:
                    c = to_px((min(max(u, 0.02), 0.98), min(max(v, 0.04), 0.98)))
                    p.setPen(QtGui.QPen(QtGui.QColor(242, 169, 0), 2))
                    p.drawRect(QtCore.QRectF(c.x() - 12, c.y() - 12, 24, 24))
                    label(T("odkładanie"), c.x() + 16, c.y() + 8, QtGui.QColor(242, 169, 0))
            except np.linalg.LinAlgError:
                pass
        p.end()
        return qimg

    def _reach_mask(self, shape):
        """Reach mask in image pixels: every pixel is mapped to the robot frame and checked against the limits.

        Computed from the image side, so it also works when part of the reach circle lies outside the frame
        or beyond the horizon of a tilted camera.
        """
        key = (self.H.tobytes(), self.cfg["reach_min"], self.cfg["reach_max"], shape[:2])
        if getattr(self, "_reach_cache", (None,))[0] != key:
            h, w = shape[:2]
            u, v = np.meshgrid((np.arange(w) + 0.5) / w, (np.arange(h) + 0.5) / h)
            H = self.H
            den = H[2, 0] * u + H[2, 1] * v + H[2, 2]
            den_ref = H[2, 0] * 0.5 + H[2, 1] * 0.5 + H[2, 2]                # sign of the denominator at the centre of the frame
            ok = den * np.sign(den_ref) > 1e-9
            den = np.where(ok, den, 1.0)
            r = np.hypot((H[0, 0] * u + H[0, 1] * v + H[0, 2]) / den, (H[1, 0] * u + H[1, 1] * v + H[1, 2]) / den)
            mask = (ok & (r >= self.cfg["reach_min"]) & (r <= self.cfg["reach_max"])).astype(np.uint8) * 255
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
            self._reach_cache = (key, mask, contours)
        return self._reach_cache[1], self._reach_cache[2]

    def _tint_reach(self, img):
        """Green reach area and its outline, drawn on a BGR image. Returns a point for the label, or None."""
        mask, contours = self._reach_mask(img.shape)
        inside = mask > 0
        if not inside.any():
            return "none"
        img[inside] = (img[inside] * 0.82 + np.array([142, 207, 62]) * 0.18).astype(np.uint8)
        h, w = img.shape[:2]
        for c in contours:                                   # only the parts inside the frame, without the image border
            pts = c.reshape(-1, 2)
            edge = (pts[:, 0] <= 0) | (pts[:, 1] <= 0) | (pts[:, 0] >= w - 1) | (pts[:, 1] >= h - 1)
            start = 0
            for i in range(len(pts) + 1):
                if i == len(pts) or edge[i]:
                    if i - start > 2:
                        cv2.polylines(img, [pts[start:i].reshape(-1, 1, 2)], False, (142, 207, 62), 2, cv2.LINE_AA)
                    start = i + 1
        if inside.all():
            return "all"
        return None

    def _draw_reach(self, p, w, h, label, state):
        """Reach labels: the robot axis (if in the frame) and a note when the ring is not visible."""
        green = QtGui.QColor(62, 207, 142)
        try:
            base = np.linalg.inv(self.H) @ np.array([0.0, 0.0, 1.0])
            if abs(base[2]) > 1e-9:
                bx, by = base[0] / base[2] * w, base[1] / base[2] * h
                if 0 <= bx <= w and 0 <= by <= h:
                    p.setPen(QtGui.QPen(green, 2))
                    p.drawLine(QtCore.QPointF(bx - 10, by), QtCore.QPointF(bx + 10, by))
                    p.drawLine(QtCore.QPointF(bx, by - 10), QtCore.QPointF(bx, by + 10))
                    label(T("oś robota"), bx + 12, by - 8, green)
        except np.linalg.LinAlgError:
            pass
        text = {"none": T("Cały kadr jest poza zasięgiem robota"), "all": T("Cały kadr jest w zasięgu robota")}.get(
            state, T("zielone: zasięg robota {0}–{1} mm").format(self.cfg['reach_min'], self.cfg['reach_max']))
        label(text, w - 8 - p.fontMetrics().boundingRect(text).width() - 10, h - 8, green)

    # ------------------------------------------------------------------ closing
    def closeEvent(self, e):
        self.timer.stop()
        self.auto = None
        self.build_tab.job = None
        if self.runner.busy:
            self.runner.stop()
        for t in [proc.stop() for proc in (self.robot_proc, self.camera_proc)]:   # both at once, then wait
            if t is not None:
                t.join(14)
        e.accept()


def apply_dark_theme(app):
    app.setStyle("Fusion")
    pal = QtGui.QPalette()
    C = QtGui.QColor
    for role, color in ((pal.Window, C(28, 33, 39)), (pal.WindowText, C(226, 231, 236)), (pal.Base, C(18, 21, 25)),
                        (pal.AlternateBase, C(28, 33, 39)), (pal.Text, C(226, 231, 236)), (pal.Button, C(44, 52, 61)),
                        (pal.ButtonText, C(226, 231, 236)), (pal.Highlight, C(242, 169, 0)), (pal.HighlightedText, C(20, 16, 0)),
                        (pal.ToolTipBase, C(28, 33, 39)), (pal.ToolTipText, C(226, 231, 236))):
        pal.setColor(role, color)
    pal.setColor(pal.Disabled, pal.ButtonText, C(120, 128, 136))
    pal.setColor(pal.Disabled, pal.WindowText, C(120, 128, 136))
    app.setPalette(pal)
    app.setStyleSheet("QPushButton { padding: 7px 10px; } "
                      "QGroupBox { margin-top: 20px; padding-top: 6px; border: 1px solid #3a444e; border-radius: 6px; } "
                      "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 8px; top: 2px; } "
                      "QTabBar::tab { padding: 6px 11px; }")


def main():
    try:
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        import dobot_web as core
    except ImportError as e:
        sys.exit(T("Brak środowiska ROS albo pliku dobot_web.py ({0}).\nUruchom program przez:  bash ~/dobot_web/dobot-app.sh").format(e))
    rclpy.init()
    bridge = core.DobotBridge()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(bridge)
    threading.Thread(target=executor.spin, daemon=True).start()

    app = QtWidgets.QApplication(sys.argv)
    apply_dark_theme(app)
    lang = None
    if "--lang" in sys.argv[1:-1]:
        lang = sys.argv[sys.argv.index("--lang") + 1]
    win = DobotApp(core, bridge, lang=lang)
    win.show()
    signal.signal(signal.SIGINT, lambda *_: win.close())
    keepalive = QtCore.QTimer()
    keepalive.timeout.connect(lambda: None)      # lets Python handle Ctrl+C in the terminal
    keepalive.start(200)
    code = app.exec_()
    executor.shutdown()
    bridge.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
