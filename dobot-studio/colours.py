#!/usr/bin/env python3
"""
Classifies blocks by colour on the OAK camera image, only inside the work area.

Run (with the camera driver running):
    python3 ~/dobot_web/colours.py

First use, in the preview window:
    1. Press p and click the 4 corners of the work area. Everything outside it is ignored.
    2. Put ONE block in the area and press the key of its colour:
           1 red   2 yellow   3 green   4 blue   5 purple
       Repeat for every colour you use. Only taught colours are looked for.

Other keys:
    0           forget all taught colours
    o           remove the work area (analyse the whole frame)
    + / -       saturation threshold (higher = fewer false detections, lower = catches paler colours)
    m           show / hide the mask (what the program treats as "coloured")
    q / Esc     quit

Settings are saved in colours.json next to the script.

Colour names are kept in Polish internally (czerwony, zolty, zielony, niebieski, fioletowy);
i18n.py translates them for display.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

CONFIG_FILE = Path(__file__).resolve().with_name("colours.json")
LEGACY_CONFIG_FILE = Path(__file__).resolve().with_name("kolory.json")      # name used before the files were renamed
PALETTE = ["czerwony", "zolty", "zielony", "niebieski", "fioletowy"]          # keys 1-5
DRAW = {"czerwony": (60, 60, 235), "zolty": (40, 210, 240), "zielony": (80, 200, 80),
        "niebieski": (235, 140, 40), "fioletowy": (210, 90, 170)}             # BGR
DEFAULTS = {
    "version": 2,
    "colors": {},       # taught colours: name -> {"hue": 0-179, "sat": 0-255}
    "roi": [],          # work area: 4 points as fractions of the frame width and height
    "s_min": 70,        # minimum saturation for a pixel to count as coloured
    "v_min": 50,        # minimum brightness
    "area_min": 0.0015, # smallest object as a fraction of the frame area
    "area_max": 0.08,   # largest object (rejects a hand, a sleeve)
}
WIDTH = 960             # width of the working image
MAX_TOL = 12            # largest allowed hue difference from the taught value


def fresh_config():
    return json.loads(json.dumps(DEFAULTS))


def load_config():
    cfg = fresh_config()
    try:
        saved = json.loads((CONFIG_FILE if CONFIG_FILE.exists() else LEGACY_CONFIG_FILE).read_text())
        if saved.get("version") == 2:
            cfg["colors"] = {k: {"hue": int(v["hue"]), "sat": int(v["sat"])}
                             for k, v in saved.get("colors", {}).items() if k in PALETTE}
            roi = saved.get("roi", [])
            if len(roi) == 4:
                cfg["roi"] = [[float(x), float(y)] for x, y in roi]
            for k in ("s_min", "v_min"):
                if k in saved:
                    cfg[k] = int(saved[k])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps({k: cfg[k] for k in ("version", "colors", "roi", "s_min", "v_min")}, indent=2))
    except OSError as e:
        print("Nie udalo sie zapisac ustawien:", e)


def hue_dist(h, ref):
    """Hue distance on the colour wheel (0-179 wraps around: 178 and 2 are close)."""
    d = np.abs(np.asarray(h).astype(np.int16) - int(ref))
    return np.minimum(d, 180 - d)


def mean_hue(h_values):
    ang = h_values.astype(np.float32) * (np.pi / 90.0)
    m = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
    return int(round((m if m >= 0 else m + 2 * np.pi) * 90.0 / np.pi)) % 180


def prepare(frame):
    h, w = frame.shape[:2]
    if w != WIDTH:
        frame = cv2.resize(frame, (WIDTH, int(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (7, 7), 0), cv2.COLOR_BGR2HSV)
    return frame, hsv


def roi_points(cfg, shape):
    if len(cfg["roi"]) != 4:
        return None
    h, w = shape[:2]
    return np.array([[int(x * w), int(y * h)] for x, y in cfg["roi"]], np.int32)


def roi_mask(cfg, shape):
    """Work area mask: 255 inside. The whole frame if no area is defined."""
    pts = roi_points(cfg, shape)
    mask = np.full(shape[:2], 255, np.uint8)
    if pts is not None:
        mask[:] = 0
        cv2.fillPoly(mask, [pts], 255)
    return mask


def colored_mask(hsv, cfg):
    m = ((hsv[..., 1] >= cfg["s_min"]) & (hsv[..., 2] >= cfg["v_min"])).astype(np.uint8) * 255
    return cv2.bitwise_and(m, roi_mask(cfg, hsv.shape))


def tolerances(cfg):
    """Hue tolerance: half the distance to the nearest other taught colour, at most MAX_TOL."""
    tol = {}
    for n, c in cfg["colors"].items():
        others = [int(hue_dist(c["hue"], o["hue"])) for k, o in cfg["colors"].items() if k != n]
        tol[n] = max(3, min(MAX_TOL, (min(others) - 1) // 2)) if others else MAX_TOL
    return tol


def area_limits(cfg, shape):
    a = shape[0] * shape[1]
    return cfg["area_min"] * a, cfg["area_max"] * a


def detect(frame, cfg):
    """Returns (working image, detections, mask). A detection has: name, box, centre, hue, area."""
    frame, hsv = prepare(frame)
    base = colored_mask(hsv, cfg)
    a_min, a_max = area_limits(cfg, frame.shape)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    tol = tolerances(cfg)
    found = []
    for name, c in cfg["colors"].items():
        # colour = hue close to the taught value AND saturation similar to the block (rejects skin, wood, pale background)
        match = (hue_dist(hsv[..., 0], c["hue"]) <= tol[name]) & (hsv[..., 1] >= 0.6 * c["sat"])
        mask = cv2.bitwise_and(base, match.astype(np.uint8) * 255)
        mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if not (a_min <= area <= a_max):
                continue
            rect = cv2.minAreaRect(cnt)
            (cx, cy), _, _ = rect
            blob = np.zeros(mask.shape, np.uint8)
            cv2.drawContours(blob, [cnt], -1, 255, -1)
            found.append({"name": name, "box": cv2.boxPoints(rect).astype(np.int32), "center": (int(cx), int(cy)),
                          "hue": mean_hue(hsv[..., 0][blob > 0]), "area": area})
    found.sort(key=lambda d: (d["center"][1] // 40, d["center"][0]))
    return frame, found, base


def sample_block(frame, cfg):
    """(hue, saturation) of the largest coloured blob in the work area, used to teach a colour."""
    frame, hsv = prepare(frame)
    mask = cv2.morphologyEx(colored_mask(hsv, cfg), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    a_min, a_max = area_limits(cfg, frame.shape)
    contours = [c for c in contours if a_min <= cv2.contourArea(c) <= a_max]
    if not contours:
        return None
    blob = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(blob, [max(contours, key=cv2.contourArea)], -1, 255, -1)
    return mean_hue(hsv[..., 0][blob > 0]), int(np.median(hsv[..., 1][blob > 0]))


def text(img, s, org, scale=0.6, color=(255, 255, 255), thick=1):
    (tw, th), base = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    x, y = int(org[0]), int(org[1])
    cv2.rectangle(img, (x - 4, y - th - 5), (x + tw + 4, y + base + 2), (20, 20, 20), -1)   # dark background under the text
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def annotate(frame, found, cfg, ui, mask=None):
    out = frame.copy()
    inside = roi_mask(cfg, out.shape)
    out[inside == 0] = (out[inside == 0] * 0.35).astype(np.uint8)          # dim what is outside the area
    if mask is not None:
        out[mask == 0] = (out[mask == 0] * 0.25).astype(np.uint8)
    pts = roi_points(cfg, out.shape)
    if pts is not None:
        cv2.polylines(out, [pts], True, (255, 255, 255), 1, cv2.LINE_AA)
    for p in ui.get("clicks", []):                                         # corners while marking
        cv2.circle(out, tuple(p), 6, (80, 220, 255), -1)
    for d in found:
        col = DRAW[d["name"]]
        cv2.drawContours(out, [d["box"]], -1, col, 2)
        cv2.circle(out, d["center"], 4, col, -1)
        x, y = d["box"][:, 0].min(), d["box"][:, 1].min()
        text(out, f"{d['name']}  H={d['hue']}", (int(x), max(18, int(y) - 8)), 0.55, col)
    y = 28
    for n in cfg["colors"]:
        text(out, f"{n}: {sum(1 for d in found if d['name'] == n)}", (12, y), 0.65, DRAW[n], 2)
        y += 30
    text(out, f"razem: {len(found)}   prog nasycenia: {cfg['s_min']}", (12, y), 0.55)
    h = out.shape[0]
    text(out, "p pole   1 czerw  2 zolty  3 ziel  4 nieb  5 fiol   0 zapomnij   m maska   q koniec", (12, h - 14), 0.5, (200, 200, 200))
    hint = ui.get("msg", "")
    if ui.get("picking"):
        hint = f"Kliknij rog pola roboczego ({len(ui['clicks']) + 1} z 4)"
    elif not hint and pts is None:
        hint = "Krok 1: nacisnij p i kliknij 4 rogi pola roboczego"
    elif not hint and not cfg["colors"]:
        hint = "Krok 2: poloz jeden klocek w polu i nacisnij klawisz koloru (1-5)"
    if hint:
        text(out, hint, (12, h - 44), 0.6, (80, 220, 255), 2)
    return out


def order_corners(points):
    """Orders 4 points around their centre so the polygon does not cross itself whatever the click order."""
    pts = np.array(points, np.float32)
    c = pts.mean(axis=0)
    return pts[np.argsort(np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0]))]


def add_click(x, y, shape, cfg, ui):
    """Handles a click while marking the area. shape = size of the working image."""
    if not ui.get("picking"):
        return
    ui["clicks"].append([int(x), int(y)])
    if len(ui["clicks"]) == 4:
        h, w = shape[:2]
        cfg["roi"] = [[round(float(px) / w, 4), round(float(py) / h, 4)] for px, py in order_corners(ui["clicks"])]
        ui.update(picking=False, clicks=[], msg="Pole robocze zapisane")
        save_config(cfg)


def handle_key(key, frame, cfg, ui):
    """Returns False when it is time to quit."""
    if key in (ord("q"), 27):
        return False
    ui["msg"] = ""
    if ord("1") <= key <= ord("5"):
        name = PALETTE[key - ord("1")]
        sample = sample_block(frame, cfg)
        if sample is None:
            ui["msg"] = "Nie widze klocka w polu roboczym. Poloz jeden i sprobuj ponownie."
        else:
            close = [n for n, c in cfg["colors"].items() if n != name and hue_dist(sample[0], c["hue"]) < 8]
            cfg["colors"][name] = {"hue": sample[0], "sat": sample[1]}
            save_config(cfg)
            ui["msg"] = f"Zapisano: {name} (odcien {sample[0]}, nasycenie {sample[1]})"
            if close:
                ui["msg"] += f"  UWAGA: bardzo blisko koloru {close[0]}, beda sie mylic"
    elif key == ord("0"):
        cfg["colors"] = {}; save_config(cfg); ui["msg"] = "Zapomniano wszystkie kolory"
    elif key == ord("p"):
        ui.update(picking=True, clicks=[])
    elif key == ord("o"):
        cfg["roi"] = []; ui.update(picking=False, clicks=[], msg="Usunieto pole robocze"); save_config(cfg)
    elif key in (ord("+"), ord("=")):
        cfg["s_min"] = min(250, cfg["s_min"] + 5); save_config(cfg)
    elif key in (ord("-"), ord("_")):
        cfg["s_min"] = max(10, cfg["s_min"] - 5); save_config(cfg)
    elif key == ord("m"):
        ui["mask"] = not ui.get("mask")
    return True


def run_image(path, cfg, out_path):
    frame = cv2.imread(path)
    if frame is None:
        sys.exit(f"Nie moge wczytac obrazu: {path}")
    small, found, _ = detect(frame, cfg)
    for d in found:
        print(f"{d['name']:10s} srodek={d['center']} odcien={d['hue']} powierzchnia={int(d['area'])}")
    print("razem:", len(found))
    if out_path:
        cv2.imwrite(out_path, annotate(small, found, cfg, {}))
        print("zapisano", out_path)


def run_camera(topic, cfg):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import CompressedImage

    class Grabber(Node):
        def __init__(self):
            super().__init__("block_colours")
            self.frame = None
            self.create_subscription(CompressedImage, topic, self.on_image, qos_profile_sensor_data)

        def on_image(self, msg):
            img = cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                self.frame = img

    rclpy.init()
    node = Grabber()
    ui = {"mask": False, "msg": "", "picking": False, "clicks": []}
    shown = {"shape": None}
    window = "Kolory klockow"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and shown["shape"] is not None:
            add_click(x, y, shown["shape"], cfg, ui)

    cv2.setMouseCallback(window, on_mouse)
    print(f"Czekam na obraz z tematu {topic} ...")
    waited = 0
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.03)
            if node.frame is None:
                waited += 1
                if waited == 150:
                    print("Nadal brak obrazu. Czy sterownik kamery dziala?  (ros2 topic hz " + topic + ")")
                blank = np.zeros((360, 640, 3), np.uint8)
                text(blank, "Czekam na obraz z kamery...", (20, 180))
                cv2.imshow(window, blank)
            else:
                small, found, mask = detect(node.frame, cfg)
                shown["shape"] = small.shape
                cv2.imshow(window, annotate(small, found, cfg, ui, mask if ui["mask"] else None))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key != 255 and node.frame is not None:
                handle_key(key, node.frame, cfg, ui)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    ap = argparse.ArgumentParser(description="Klasyfikacja klockow po kolorze w polu roboczym")
    ap.add_argument("--topic", default="/oak/rgb/image_raw/compressed", help="temat ROS z obrazem JPEG")
    ap.add_argument("--image", help="zamiast kamery: plik ze zdjeciem (uzywa zapisanych ustawien)")
    ap.add_argument("--out", help="z --image: zapisz obraz z ramkami do pliku")
    args = ap.parse_args()
    cfg = load_config()
    if args.image:
        run_image(args.image, cfg, args.out)
    else:
        run_camera(args.topic, cfg)


if __name__ == "__main__":
    main()
