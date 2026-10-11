#!/usr/bin/env python3
"""Logic tests that need no robot, camera or ROS.

Run:  python3 tests/test_logic.py      (or: python3 -m pytest tests)
"""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import cv2
import numpy as np

import build_tab as B
import dobot_app as A
import i18n
import colours

STOCK = {"czerwony": 3, "niebieski": 2, "zolty": 1}


def buildable(cubes, stock=STOCK):
    pos = {(c["x"], c["y"], c["z"]) for c in cubes}
    used = {}
    for c in cubes:
        used[c["color"]] = used.get(c["color"], 0) + 1
    return (len(pos) == len(cubes) <= B.MAX_CUBES
            and all(c["z"] == 0 or (c["x"], c["y"], c["z"] - 1) in pos for c in cubes)
            and all(n <= stock.get(k, 0) for k, n in used.items())
            and all(0 <= c["x"] < B.GRID and 0 <= c["y"] < B.GRID for c in cubes))


def test_plan_repair_makes_any_answer_buildable():
    cases = [
        [{"x": 0, "y": 0, "z": 0, "color": "red"}, {"x": 0, "y": 0, "z": 3, "color": "blue"}],          # floating cube
        [{"x": x, "y": 0, "z": z, "color": "czerwony"} for x in range(3) for z in range(3)],              # too many
        [{"x": 0, "y": 0, "z": z, "color": "zielony"} for z in range(4)],                                 # colour not available
        [{"x": "a"}, "junk", {"x": 9, "y": 9, "z": 0, "color": "czerwony"}, {"x": 1, "y": 1, "z": 0, "color": "ŻÓŁTY"}],
        [{"x": -2, "y": 5, "z": 0, "color": "czerwony"}, {"x": -1, "y": 5, "z": 1.0, "color": "zolty"}],  # negative, float
    ]
    for raw in cases:
        cubes, _notes = B.normalize_structure(raw, STOCK)
        assert cubes and buildable(cubes), raw
    assert B.normalize_structure(None, STOCK)[0] == []
    assert B.normalize_structure([], {})[0] == []


def test_templates_are_buildable_and_distinct():
    t = B.templates(STOCK)
    assert len(t) == 4 and all(buildable(p["cubes"]) for p in t)
    assert len({B.shape_key(p["cubes"]) for p in t}) == 4
    assert B.templates({}) == []
    assert len(B.templates({"czerwony": 1})) == 1


def test_square_angle_folding():
    for deg, want in [(0, 0), (30, 30), (46, -44), (90, 0), (135, 45), (-60, 30), (200, 20)]:
        assert abs(B.fold_angle(deg) - want) < 1e-9


def test_calibration_recovers_a_known_mapping():
    H_true = np.array([[420.0, 30.0, 110.0], [-25.0, -510.0, 190.0], [0.05, 0.02, 1.0]])
    px = [[0.2, 0.2], [0.8, 0.25], [0.75, 0.8], [0.25, 0.75], [0.5, 0.5]]
    pts = [{"px": p, "xy": list(A.apply_h(H_true, [p])[0]), "z": -45.0} for p in px]
    H, rms, problem = A.fit_calibration(pts)
    assert problem == "" and rms < 0.01
    assert np.allclose(A.apply_h(H, [[0.4, 0.6]]), A.apply_h(H_true, [[0.4, 0.6]]), atol=0.05)
    assert A.fit_calibration(pts[:3])[0] is None                                    # too few points
    line = [{"px": [0.1 * i, 0.1 * i], "xy": [100 + 10 * i, 10 * i], "z": 0} for i in range(5)]
    assert A.fit_calibration(line)[0] is None                                       # points in a line


def test_pick_and_build_sequences():
    drop = {"x": 60.0, "y": -230.0, "z": -45.0}
    seq = A.pick_sequence(200.0, 50.0, -45.0, drop, 40)
    assert [a["type"] for a in seq].count("suction") == 2
    assert seq[0] == {"type": "move", "z": seq[1]["z"], "up_only": True}                             # lift straight up first
    assert seq[2]["z"] == -45.0 and seq[-1]["x"] == 60.0                            # down to the block, end above drop-off
    seq = B.build_sequence((200, 50), 20.0, (60, -230), -45.0, -18.0, 40.0)
    assert seq[2]["r"] == 0.0 and seq[6]["r"] == -20.0                              # rotate by minus the cube's angle
    assert seq[7]["z"] == -16.0                                                     # release 2 mm above the target height
    assert B.build_sequence((200, 50), 20.0, (60, -230), -45.0, -18.0, 40.0, invert=True)[6]["r"] == 20.0


def test_build_positions_are_centred_on_the_site():
    cubes = [{"x": x, "y": 0, "z": 0, "color": "czerwony"} for x in range(3)]
    xs = [B.cube_xy(c, cubes, {"x": 200.0, "y": 0.0}, 29.0)[0] for c in cubes]
    assert xs == [171.0, 200.0, 229.0]


def test_colour_detection_on_a_synthetic_image():
    img = np.full((720, 1280, 3), (150, 152, 155), np.uint8)
    cv2.rectangle(img, (300, 300), (380, 380), (28, 40, 196), -1)                   # red (BGR)
    cv2.rectangle(img, (700, 200), (780, 280), (168, 87, 0), -1)                    # blue
    cv2.rectangle(img, (20, 20), (120, 120), (168, 87, 0), -1)                      # blue, outside the work area
    cfg = colours.fresh_config()
    cfg["roi"] = [[0.15, 0.15], [0.85, 0.15], [0.85, 0.85], [0.15, 0.85]]
    cfg["colors"] = {"czerwony": {"hue": 2, "sat": 219}, "niebieski": {"hue": 104, "sat": 255}}
    _small, found, _mask = colours.detect(img, cfg)
    assert sorted(d["name"] for d in found) == ["czerwony", "niebieski"]
    cfg["roi"] = []
    assert len(colours.detect(img, cfg)[1]) == 3


def test_translations():
    i18n.set_language("pl")
    assert i18n.T("Buduj") == "Buduj" and i18n.count(2, "klocek") == "2 klocki" and A.LABEL["zolty"] == "żółty"
    i18n.set_language("en")
    assert i18n.T("Buduj") == "Build" and i18n.count(1, "kostka") == "1 cube" and i18n.count(5, "kostka") == "5 cubes"
    assert A.LABEL["zolty"] == "yellow" and B.LABEL.get("czerwony") == "red"
    assert i18n.T("tekst bez tłumaczenia") == "tekst bez tłumaczenia"              # falls back to the Polish text
    import re
    for pl, en in i18n.EN.items():                                                 # placeholders must match
        assert sorted(re.findall(r"\{[^}]*\}", pl)) == sorted(re.findall(r"\{[^}]*\}", en)), pl
    i18n.set_language("pl")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print("ok  ", name)
    print(f"{len(tests)} tests passed")
