#!/usr/bin/env python3
"""
Dobot Web Console
-----------------
One process that:
  * connects to a running magician_ros2 driver (topics, PTP action, services),
  * serves index.html (3D view in Three.js, manual control, chat),
  * turns text commands into robot moves through a local model in Ollama.

BlockSmith (dobot_app.py) imports this module for its ROS 2 bridge and motion queue.

Run as a web console (with the Dobot driver running):
    python3 ~/dobot_web/dobot_web.py

Environment variables (optional):
    DOBOT_WEB_PORT   HTTP port                (default 8080)
    OLLAMA_URL       Ollama address           (default http://127.0.0.1:11434)
    OLLAMA_MODEL     model name               (default: first from `ollama list`)
    DOBOT_Z_MIN      lowest allowed Z in mm   (default -70)
    DOBOT_CAM_TOPIC  topic with JPEG images   (default /oak/rgb/image_raw/compressed)

No extra packages: only ROS 2 and the Python standard library.
"""

import json
import math
import os
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from i18n import T

import rclpy
from action_msgs.msg import GoalStatus
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, JointState
from std_msgs.msg import Float64MultiArray

from dobot_msgs.action import PointToPoint
from dobot_msgs.srv import ExecuteHomingProcedure, SuctionCupControl

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
PORT = int(os.environ.get("DOBOT_WEB_PORT", "8080"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "").strip()

HOME = [150.0, 0.0, 100.0, 0.0]          # mm, mm, mm, degrees
Z_MIN = float(os.environ.get("DOBOT_Z_MIN", "-70"))
Z_MAX = 160.0
R_MIN = 120.0                             # minimum horizontal distance from the base axis
R_MAX = 315.0
MAX_ACTIONS = 12
DEFAULT_VEL = 0.5
ACC_RATIO = 0.3

CAM_TOPIC = os.environ.get("DOBOT_CAM_TOPIC", "/oak/rgb/image_raw/compressed")

INDEX_FILE = Path(__file__).resolve().parent / "index.html"


class RobotError(Exception):
    """An error that is shown to the user."""


class Busy(Exception):
    pass


# ----------------------------------------------------------------------------
# Pure functions: validating and describing actions
# ----------------------------------------------------------------------------
def limit_error(x, y, z):
    """Returns a description of the violated limit, or None."""
    r = math.hypot(x, y)
    if r < R_MIN:
        return T("punkt za blisko podstawy ({0:.0f} mm, minimum {1:.0f} mm)").format(r, R_MIN)
    if r > R_MAX:
        return T("punkt poza zasięgiem ({0:.0f} mm, maksimum {1:.0f} mm)").format(r, R_MAX)
    if z < Z_MIN:
        return T("Z={0:.0f} mm jest poniżej limitu {1:.0f} mm").format(z, Z_MIN)
    if z > Z_MAX:
        return T("Z={0:.0f} mm jest powyżej limitu {1:.0f} mm").format(z, Z_MAX)
    return None


def _as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "on", "1", "yes", "tak"):
            return True
        if s in ("false", "off", "0", "no", "nie"):
            return False
    raise ValueError(T("pole „on” musi być true albo false"))


def normalize_actions(raw, allow_homing=False):
    """Turns any JSON from the model or the browser into a safe list of actions."""
    out, errs = [], []
    if raw is None:
        return out, errs
    if not isinstance(raw, list):
        return out, [T("Lista akcji ma zły format.")]
    if len(raw) > MAX_ACTIONS:
        errs.append(T("Plan skrócony do {0} kroków.").format(MAX_ACTIONS))
    for i, a in enumerate(raw[:MAX_ACTIONS], start=1):
        try:
            if not isinstance(a, dict):
                raise ValueError(T("krok nie jest obiektem"))
            t = str(a.get("type", "")).strip().lower()
            if t == "move":
                item = {"type": "move"}
                for k in ("x", "y", "z", "r"):
                    if a.get(k) is not None:
                        item[k] = float(a[k])
                if len(item) == 1:
                    raise ValueError(T("ruch bez współrzędnych"))
            elif t == "move_rel":
                item = {"type": "move_rel"}
                for k in ("dx", "dy", "dz", "dr"):
                    v = float(a.get(k) or 0.0)
                    if v:
                        item[k] = v
                if len(item) == 1:
                    raise ValueError(T("przesunięcie o zero"))
            elif t == "joint_rel":
                joint = int(a["joint"])
                if joint not in (1, 2, 3, 4):
                    raise ValueError(T("przegub musi być z zakresu 1-4"))
                item = {"type": "joint_rel", "joint": joint, "delta": float(a["delta"])}
            elif t == "suction":
                item = {"type": "suction", "on": _as_bool(a.get("on"))}
            elif t == "wait":
                item = {"type": "wait", "seconds": min(max(float(a.get("seconds", 1)), 0.0), 10.0)}
            elif t == "home":
                item = {"type": "home"}
            elif t == "homing" and allow_homing:
                item = {"type": "homing"}
            else:
                raise ValueError(T("nieznany typ akcji „{0}”").format(t))
            for v in item.values():
                if isinstance(v, float) and not math.isfinite(v):
                    raise ValueError(T("wartość nie jest liczbą"))
            out.append(item)
        except (KeyError, TypeError, ValueError) as e:
            errs.append(T("Krok {0} pominięty: {1}").format(i, e))
    return out, errs


def _fmt(v, unit=""):
    return f"{v:+.0f}{unit}" if abs(v - round(v)) < 0.05 else f"{v:+.1f}{unit}"


def describe(a):
    t = a["type"]
    if t == "move":
        parts = [f"{k.upper()}={a[k]:.0f}" for k in ("x", "y", "z") if k in a]
        if "r" in a:
            parts.append(f"R={a['r']:.0f}°")
        return T("Ruch do ") + ", ".join(parts)
    if t == "move_rel":
        names = {"dx": "X", "dy": "Y", "dz": "Z", "dr": "R"}
        parts = [f"{names[k]} {_fmt(a[k], '°' if k == 'dr' else ' mm')}" for k in ("dx", "dy", "dz", "dr") if k in a]
        return T("Przesunięcie: ") + ", ".join(parts)
    if t == "joint_rel":
        return T("Obrót przegubu J{0} o {1}").format(a['joint'], _fmt(a['delta'], '°'))
    if t == "suction":
        return T("Przyssawka: ") + (T("włącz") if a["on"] else T("wyłącz"))
    if t == "wait":
        return T("Pauza {0:g} s").format(a['seconds'])
    if t == "home":
        return T("Powrót do pozycji domowej")
    if t == "homing":
        return T("Bazowanie")
    return t


def resolve_target(a, cur):
    """Cartesian target [x,y,z,r] of a move action, given the current pose cur."""
    t = a["type"]
    if t == "move":
        return [a.get(k, cur[i]) for i, k in enumerate(("x", "y", "z", "r"))]
    if t == "move_rel":
        return [cur[i] + a.get(k, 0.0) for i, k in enumerate(("dx", "dy", "dz", "dr"))]
    if t == "home":
        return list(HOME)
    return None


def simulate(actions, pose):
    """Plan preview: target points and limit warnings (the robot does not move)."""
    pts, warns = [], []
    cur = list(pose) if pose else None
    for a in actions:
        if cur is None:
            break
        if a["type"] == "joint_rel":
            cur = None           # after a joint move the pose is unknown without kinematics
            continue
        tgt = resolve_target(a, cur)
        if tgt is None:
            continue
        err = limit_error(*tgt[:3])
        if err:
            warns.append(f"{describe(a)}: {err}")
        pts.append([round(v, 1) for v in tgt[:3]])
        cur = tgt
    return pts, warns


# ----------------------------------------------------------------------------
# Bridge to ROS 2
# ----------------------------------------------------------------------------
class DobotBridge(Node):
    def __init__(self):
        super().__init__("dobot_web_console")
        self._lock = threading.Lock()
        self._pose = None        # [x mm, y mm, z mm, r deg]
        self._pose_t = 0.0
        self._joints = None      # [deg x4]
        self._goal_handle = None
        self._cancel_req = False
        self._jpeg = None        # latest camera frame (JPEG bytes)
        self._jpeg_t = 0.0

        self.create_subscription(CompressedImage, CAM_TOPIC, self._on_image, qos_profile_sensor_data)
        self.create_subscription(Float64MultiArray, "dobot_pose_raw", self._on_pose, 10)
        self.create_subscription(JointState, "dobot_joint_states", self._on_joints, 10)
        self._ptp = ActionClient(self, PointToPoint, "PTP_action")
        self._suction = self.create_client(SuctionCupControl, "dobot_suction_cup_service")
        self._homing = self.create_client(ExecuteHomingProcedure, "dobot_homing_service")

    # --- reading state -------------------------------------------------------
    def _on_pose(self, msg):
        d = list(msg.data)
        if len(d) >= 4:
            with self._lock:
                self._pose = [d[0] * 1000.0, d[1] * 1000.0, d[2] * 1000.0, d[3]]
                self._pose_t = time.time()

    def _on_joints(self, msg):
        p = list(msg.position)
        if len(p) >= 4:
            with self._lock:
                self._joints = [math.degrees(v) for v in p[:4]]

    def _on_image(self, msg):
        data = bytes(msg.data)
        with self._lock:
            self._jpeg = data
            self._jpeg_t = time.time()

    def frame(self):
        """The latest JPEG frame, unless it is older than 2 s."""
        with self._lock:
            if self._jpeg is None or time.time() - self._jpeg_t > 2.0:
                return None
            return self._jpeg

    def pose(self):
        with self._lock:
            return list(self._pose) if self._pose else None

    def pose_age(self):
        with self._lock:
            return (time.time() - self._pose_t) if self._pose_t else None

    def joints(self):
        with self._lock:
            return list(self._joints) if self._joints else None

    def fresh_pose(self):
        age = self.pose_age()
        if age is None or age > 2.0:
            raise RobotError(T("Brak danych o pozycji. Sprawdź, czy sterownik Dobota jest uruchomiony."))
        return self.pose()

    # --- motion ---------------------------------------------------------------
    def ptp(self, motion_type, target, vel, timeout=45.0):
        if not self._ptp.wait_for_server(timeout_sec=2.0):
            raise RobotError(T("Serwer ruchu /PTP_action nie odpowiada. Uruchom sterownik Dobota."))
        self._cancel_req = False
        goal = PointToPoint.Goal()
        goal.motion_type = int(motion_type)
        goal.target_pose = [float(v) for v in target]
        goal.velocity_ratio = float(vel)
        goal.acceleration_ratio = float(ACC_RATIO)

        done = threading.Event()
        box = {}

        def on_result(fut):
            try:
                box["status"] = fut.result().status
            except Exception as e:      # noqa: BLE001
                box["error"] = str(e)
            done.set()

        def on_goal(fut):
            try:
                gh = fut.result()
            except Exception as e:      # noqa: BLE001
                box["error"] = str(e)
                done.set()
                return
            if not gh.accepted:
                box["rejected"] = True
                done.set()
                return
            with self._lock:
                self._goal_handle = gh
            gh.get_result_async().add_done_callback(on_result)
            if self._cancel_req:            # STOP arrived before the driver accepted the goal
                gh.cancel_goal_async()

        self._ptp.send_goal_async(goal).add_done_callback(on_goal)
        finished = done.wait(timeout)
        with self._lock:
            gh, self._goal_handle = self._goal_handle, None
        if not finished:
            if gh is not None:
                gh.cancel_goal_async()
            raise RobotError(T("Ruch nie zakończył się w oczekiwanym czasie."))
        if box.get("rejected"):
            where = ""
            if int(motion_type) == 1:       # the log should show which point was rejected
                where = " [X={0:.0f} Y={1:.0f} Z={2:.0f} R={3:.0f}]".format(*[float(v) for v in target][:4])
            raise RobotError(T("Sterownik odrzucił cel (poza zasięgiem albo limitami przegubów).") + where)
        if "error" in box:
            raise RobotError(T("Błąd akcji ruchu: ") + box["error"])
        status = box.get("status")
        if status == GoalStatus.STATUS_CANCELED:
            raise RobotError(T("Ruch przerwany."))
        if status != GoalStatus.STATUS_SUCCEEDED:
            raise RobotError(T("Ruch nie powiódł się (status {0}).").format(status))

    def cancel(self):
        self._cancel_req = True
        with self._lock:
            gh = self._goal_handle
        if gh is not None:
            gh.cancel_goal_async()

    def _call(self, client, request, name, timeout=15.0):
        if not client.wait_for_service(timeout_sec=2.0):
            raise RobotError(T("Usługa {0} nie odpowiada. Uruchom sterownik Dobota.").format(name))
        done = threading.Event()
        fut = client.call_async(request)
        fut.add_done_callback(lambda _f: done.set())
        if not done.wait(timeout):
            raise RobotError(T("Usługa {0} nie odpowiedziała w czasie.").format(name))
        if fut.exception() is not None:
            raise RobotError(T("Usługa {0}: {1}").format(name, fut.exception()))
        return fut.result()

    def suction(self, on):
        req = SuctionCupControl.Request()
        req.enable_suction = bool(on)
        self._call(self._suction, req, T("przyssawki"))

    def homing(self):
        self._call(self._homing, ExecuteHomingProcedure.Request(), T("bazowania"), timeout=60.0)

    def wait_until_still(self, timeout=45.0, settle=1.5, eps=0.3):
        """Waits until the pose stops changing (e.g. after homing)."""
        t_end = time.time() + timeout
        last = self.pose()
        t_still = time.time()
        while time.time() < t_end:
            time.sleep(0.1)
            cur = self.pose()
            if cur is None or last is None:
                last, t_still = cur, time.time()
                continue
            if max(abs(c - l) for c, l in zip(cur, last)) > eps:
                last, t_still = cur, time.time()
            elif time.time() - t_still >= settle:
                return


# ----------------------------------------------------------------------------
# Execution queue: one sequence at a time
# ----------------------------------------------------------------------------
class Runner:
    def __init__(self, bridge, log):
        self.bridge = bridge
        self.log = log
        self.vel = DEFAULT_VEL
        self.suction_on = False
        self.current = None           # description of the step being executed
        self.failed = False           # whether the last sequence was interrupted or failed
        self._busy = False
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._q = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def busy(self):
        return self._busy

    def submit(self, actions, label):
        if not actions:
            raise RobotError(T("Brak kroków do wykonania."))
        with self._lock:
            if self._busy:
                raise Busy()
            self._busy = True
        self._abort.clear()
        self._q.put((label, actions))

    def stop(self):
        self._abort.set()
        self.bridge.cancel()
        self.log(T("STOP: przerwano bieżącą sekwencję."), "warn")

    def _loop(self):
        while True:
            label, actions = self._q.get()
            self.failed = False
            try:
                if label:
                    self.log(label)
                for a in actions:
                    if self._abort.is_set():
                        break
                    self.current = describe(a)
                    self._run(a)
                    if self._abort.is_set():
                        self.failed = True
                        break
                    self.log("✓ " + describe(a))
            except RobotError as e:
                self.failed = True
                if not self._abort.is_set():
                    self.log("✗ " + str(e), "error")
            except Exception as e:      # noqa: BLE001
                self.failed = True
                self.log(T("✗ Nieoczekiwany błąd: {0}").format(e), "error")
            finally:
                self.current = None
                self._busy = False

    def _run(self, a):
        b = self.bridge
        t = a["type"]
        if t in ("move", "move_rel", "home"):
            cur = b.fresh_pose()
            tgt = resolve_target(a, cur)
            if a.get("up_only") and cur[2] >= tgt[2] - 1.0:
                return                      # the arm is already high enough: do not lower it needlessly
            err = limit_error(*tgt[:3])
            if err:
                raise RobotError(f"{describe(a)}: {err}.")
            b.ptp(1, tgt, self.vel)
        elif t == "joint_rel":
            b.fresh_pose()
            j = b.joints()
            if j is None:
                raise RobotError(T("Brak danych o kątach przegubów."))
            j[a["joint"] - 1] += a["delta"]
            b.ptp(4, j, self.vel)
        elif t == "suction":
            b.suction(a["on"])
            self.suction_on = a["on"]
        elif t == "wait":
            t_end = time.time() + a["seconds"]
            while time.time() < t_end and not self._abort.is_set():
                time.sleep(0.05)
        elif t == "homing":
            b.homing()
            time.sleep(2.0)
            b.wait_until_still()
        else:
            raise RobotError(T("Nieobsługiwana akcja: {0}").format(t))


# ----------------------------------------------------------------------------
# Ollama
# ----------------------------------------------------------------------------
SYSTEM_PROMPT = """You control a Dobot Magician: a small 4-axis desktop robot arm with a suction cup.
Translate the user's request into robot actions. Reply with ONE JSON object and nothing else:
{"say": "<one short sentence for the user, in the user's language>", "actions": [ ... ]}

Coordinate frame, in millimetres: X points forward from the robot base, Y points to the robot's left,
Z points up. R is the tool rotation in degrees.
Workspace limits: horizontal distance from the base sqrt(x^2+y^2) must stay between __RMIN__ and __RMAX__;
Z must stay between __ZMIN__ and __ZMAX__. Home is x=150, y=0, z=100, r=0. The table is near z=__ZMIN__.

Allowed actions (use only these):
{"type":"move","x":200,"y":0,"z":50,"r":0}   absolute target; leave out a coordinate to keep its current value
{"type":"move_rel","dx":0,"dy":0,"dz":20,"dr":0}   move relative to the current position
{"type":"joint_rel","joint":1,"delta":30}   rotate one joint by degrees; joint 1 is the base, positive turns left (towards +Y)
{"type":"suction","on":true}   switch the suction cup on or off
{"type":"wait","seconds":1}
{"type":"home"}   go back to the home position

Direction words: up/higher = +dz, down/lower = -dz, forward = +dx, back = -dx, left = +dy, right = -dy.
If the user gives no distance, use 20 mm. If the user gives centimetres, convert to millimetres.
To pick something up: move above it, move down, suction on, wait 1 second, move up.
To put something down: move above the place, move down, suction off, wait 1 second, move up.
Use at most 10 actions. Never plan a target outside the workspace limits; if the request is impossible,
unsafe or unclear, return "actions": [] and explain or ask in "say".
If the user only asks a question, answer in "say" and return "actions": [].

Current robot state: __STATE__"""


def _http_json(url, body=None, timeout=10.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Llm:
    def __init__(self):
        self.model = OLLAMA_MODEL
        self.history = deque(maxlen=8)
        self._lock = threading.Lock()

    def ensure_model(self):
        if self.model:
            return self.model
        try:
            tags = _http_json(OLLAMA_URL + "/api/tags", timeout=4.0)
        except (urllib.error.URLError, OSError, ValueError):
            raise RobotError(T("Ollama nie odpowiada pod adresem ") + OLLAMA_URL + T(". Uruchom ją poleceniem „ollama serve”."))
        models = [m.get("name") for m in tags.get("models", []) if m.get("name")]
        if not models:
            raise RobotError(T("W Ollamie nie ma żadnego modelu. Pobierz go, np. „ollama pull qwen2.5:3b”."))
        self.model = models[0]
        return self.model

    def plan(self, prompt, pose, joints, suction_on):
        model = self.ensure_model()
        if pose:
            state = (f"x={pose[0]:.0f}, y={pose[1]:.0f}, z={pose[2]:.0f}, r={pose[3]:.0f}; "
                     f"suction is {'on' if suction_on else 'off'}")
            if joints:
                state += f"; base joint angle {joints[0]:.0f} degrees"
        else:
            state = "unknown (the robot driver is not running)"
        system = (SYSTEM_PROMPT.replace("__RMIN__", f"{R_MIN:.0f}").replace("__RMAX__", f"{R_MAX:.0f}")
                  .replace("__ZMIN__", f"{Z_MIN:.0f}").replace("__ZMAX__", f"{Z_MAX:.0f}")
                  .replace("__STATE__", state))
        with self._lock:
            messages = [{"role": "system", "content": system}] + list(self.history) + \
                       [{"role": "user", "content": prompt}]
            body = {"model": model, "messages": messages, "stream": False, "format": "json",
                    "keep_alive": "15m", "options": {"temperature": 0.1}}
            try:
                resp = _http_json(OLLAMA_URL + "/api/chat", body, timeout=240.0)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:200]
                raise RobotError(T("Ollama zwróciła błąd {0}: {1}").format(e.code, detail))
            except (urllib.error.URLError, OSError) as e:
                raise RobotError(T("Brak połączenia z Ollamą: {0}").format(e))
            content = (resp.get("message") or {}).get("content", "")
            parsed = self._parse(content)
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        return parsed

    @staticmethod
    def _parse(content):
        text = content.strip()
        try:
            obj = json.loads(text)
        except ValueError:
            a, b = text.find("{"), text.rfind("}")
            try:
                obj = json.loads(text[a:b + 1]) if a >= 0 and b > a else None
            except ValueError:
                obj = None
        if not isinstance(obj, dict):
            return {"say": T("Model nie zwrócił poprawnej odpowiedzi. Spróbuj sformułować polecenie inaczej."),
                    "actions": []}
        say = obj.get("say")
        return {"say": say if isinstance(say, str) else "", "actions": obj.get("actions") or []}


# ----------------------------------------------------------------------------
# Application + HTTP
# ----------------------------------------------------------------------------
class App:
    def __init__(self, bridge):
        self.bridge = bridge
        self._log = deque(maxlen=80)
        self._log_id = 0
        self._log_lock = threading.Lock()
        self.runner = Runner(bridge, self.log)
        self.llm = Llm()

    def log(self, msg, level="info"):
        with self._log_lock:
            self._log_id += 1
            self._log.append({"id": self._log_id, "t": time.strftime("%H:%M:%S"), "msg": msg, "level": level})
        print(f"[{level}] {msg}", flush=True)

    def state(self):
        b = self.bridge
        age = b.pose_age()
        live = age is not None and age < 2.0
        with self._log_lock:
            log = list(self._log)[-30:]
        return {
            "live": live,
            "pose": b.pose(),
            "joints": b.joints(),
            "camera": b.frame() is not None,
            "busy": self.runner.busy,
            "current": self.runner.current,
            "suction": self.runner.suction_on,
            "vel": self.runner.vel,
            "model": self.llm.model,
            "limits": {"r_min": R_MIN, "r_max": R_MAX, "z_min": Z_MIN, "z_max": Z_MAX},
            "home": HOME,
            "log": log,
        }

    def run_actions(self, raw, label, allow_homing=False):
        actions, errs = normalize_actions(raw, allow_homing=allow_homing)
        if not actions:
            raise RobotError(errs[0] if errs else T("Brak kroków do wykonania."))
        self.runner.submit(actions, label)
        return {"ok": True, "count": len(actions), "warnings": errs}

    def chat(self, prompt):
        prompt = (prompt or "").strip()
        if not prompt:
            raise RobotError(T("Puste polecenie."))
        age = self.bridge.pose_age()
        pose = self.bridge.pose() if (age is not None and age < 2.0) else None
        parsed = self.llm.plan(prompt, pose, self.bridge.joints(), self.runner.suction_on)
        actions, errs = normalize_actions(parsed["actions"])
        preview, warns = simulate(actions, pose)
        for a in actions:
            a["text"] = describe(a)
        return {"say": parsed["say"], "actions": actions, "preview": preview,
                "warnings": errs + warns, "model": self.llm.model}


APP = None


class Handler(BaseHTTPRequestHandler):
    server_version = "DobotWeb/1.0"

    def log_message(self, *_args):        # keep the terminal quiet
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        data = json.loads(self.rfile.read(n).decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                self._send(200, INDEX_FILE.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, b"Brak pliku index.html obok dobot_web.py", "text/plain; charset=utf-8")
        elif path == "/three.min.js":
            try:
                self._send(200, INDEX_FILE.with_name("three.min.js").read_bytes(), "application/javascript")
            except OSError:
                self._send(404, b"not found", "text/plain")
        elif path == "/api/camera.jpg":
            jpeg = APP.bridge.frame()
            if jpeg is None:
                self._send(503, b"brak obrazu", "text/plain; charset=utf-8")
            else:
                self._send(200, jpeg, "image/jpeg")
        elif path == "/api/state":
            self._json(APP.state())
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self._body()
            if path == "/api/jog":
                delta = float(body.get("delta", 0))
                if body.get("mode") == "joint":
                    act = {"type": "joint_rel", "joint": int(body.get("joint", 0)), "delta": delta}
                else:
                    axis = str(body.get("axis", "")).lower()
                    if axis not in ("x", "y", "z", "r"):
                        raise RobotError(T("Nieznana oś."))
                    act = {"type": "move_rel", "d" + axis: delta}
                self._json(APP.run_actions([act], None))
            elif path == "/api/home":
                self._json(APP.run_actions([{"type": "home"}], None))
            elif path == "/api/homing":
                self._json(APP.run_actions([{"type": "homing"}], T("Bazowanie…"), allow_homing=True))
            elif path == "/api/suction":
                self._json(APP.run_actions([{"type": "suction", "on": bool(body.get("on"))}], None))
            elif path == "/api/execute":
                self._json(APP.run_actions(body.get("actions"), T("Wykonuję plan z polecenia.")))
            elif path == "/api/stop":
                APP.runner.stop()
                self._json({"ok": True})
            elif path == "/api/speed":
                APP.runner.vel = min(max(float(body.get("vel", DEFAULT_VEL)), 0.05), 1.0)
                self._json({"ok": True, "vel": APP.runner.vel})
            elif path == "/api/chat":
                self._json(APP.chat(body.get("prompt")))
            else:
                self._json({"error": T("Nieznany adres.")}, 404)
        except Busy:
            self._json({"error": T("Robot wykonuje jeszcze poprzedni ruch.")}, 409)
        except RobotError as e:
            self._json({"error": str(e)}, 400)
        except (ValueError, TypeError) as e:
            self._json({"error": T("Błędne dane: {0}").format(e)}, 400)
        except Exception as e:      # noqa: BLE001
            self._json({"error": T("Błąd serwera: {0}").format(e)}, 500)


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "ADRES_JETSONA"


def main():
    global APP
    rclpy.init()
    bridge = DobotBridge()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(bridge)
    threading.Thread(target=executor.spin, daemon=True).start()

    APP = App(bridge)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    APP.log(T("Konsola działa: http://{0}:{1}").format(_local_ip(), PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        executor.shutdown()
        bridge.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
