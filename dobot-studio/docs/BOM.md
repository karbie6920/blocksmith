# Bill of materials

Prices are left out on purpose: they change quickly and differ by country. "Used here" is what this project was built with. "Alternatives" lists what should also work but was not tried.

## Core hardware

| # | Item | Qty | Used here | Notes and alternatives |
|---|---|---|---|---|
| 1 | Robot arm | 1 | Dobot Magician | Needs the suction cup kit (air pump box, suction cup, rotation servo). The driver talks to it over USB as `/dev/ttyACM0`. |
| 2 | Edge computer | 1 | NVIDIA Jetson Orin Nano Super Developer Kit, 8 GB | Any Jetson Orin on JetPack 6 should work. 8 GB limits Ollama to small models (3–4 B parameters). |
| 3 | Camera | 1 | Luxonis OAK-1 PoE | Only the colour camera is used. A USB OAK or any camera with a ROS 2 driver publishing JPEG `CompressedImage` can replace it (set `DOBOT_CAM_TOPIC`). |
| 4 | PoE power for the camera | 1 | Small PoE switch (802.3af) | The Jetson's Ethernet port does not supply PoE. A single-port PoE injector works too. |
| 5 | Ethernet cables | 2 | Cat 5e or better | Jetson to PoE switch, PoE switch to camera. |
| 6 | Storage | 1 | M.2 NVMe SSD, 512 GB (WD PC SN740, 2242 size) | Any M.2 NVMe drive. The carrier board has mounts for 2280 and 2230 only: a 2242 drive needs a 2242-to-2280 extension bracket. SATA M.2 drives do not work. |
| 7 | microSD card | 1 | 32 GB | Only for the first boot and for copying the system to the SSD. 64 GB or more is recommended by NVIDIA. |
| 8 | Power supply for the Jetson | 1 | Included with the developer kit | |
| 9 | Power supply for the robot | 1 | Included with the Dobot Magician | |
| 10 | USB cable, robot to Jetson | 1 | Included with the Dobot Magician | Use one of the Jetson's USB-A ports. Must be a data cable. |

## Workspace

| # | Item | Qty | Used here | Notes |
|---|---|---|---|---|
| 11 | Blocks | 6 or more | Painted wooden cubes, 27 mm | Saturated colours only: red, yellow, green, blue, purple. All the same height. The face must be flat and smooth enough for the suction cup. |
| 12 | Work surface | 1 | White paper on the table | White, grey or pale wood. A coloured or glossy surface gets detected as blocks. |
| 13 | Camera mount | 1 | Aluminium profile post and arm, camera looking down at the table | Rigid. If the camera or the robot moves, calibration must be repeated. |
| 14 | Common base | 1 (optional) | Aluminium profile frame | Fixing the robot and the camera mount to one frame keeps the calibration valid when the setup is moved. |
| 15 | Lighting | — | Room light | Even and constant. Hard shadows and reflections shift the detected colours. |

## For setup

| # | Item | Qty | Notes |
|---|---|---|---|
| 16 | Monitor with DisplayPort | 1 | The Jetson developer kit has DisplayPort, not HDMI. The app is a desktop window, so a screen is needed during use. |
| 17 | USB keyboard and mouse | 1 | |
| 18 | Internet access | — | Wi-Fi on the Jetson is enough. Needed for installation and for pulling an Ollama model; not needed while running. |

## Software

| Component | Version used | Source |
|---|---|---|
| JetPack / Jetson Linux | 6.2.1 / R36.4.7 (Ubuntu 22.04) | NVIDIA |
| ROS 2 | Humble | apt |
| Dobot driver | `magician_ros2`, main branch, with two small patches (see manual) | github.com/jkaniuka/magician_ros2 |
| Camera driver | `ros-humble-depthai-ros` | apt |
| Ollama | current release | ollama.com |
| LLM | any small chat model that fits in 8 GB | `ollama pull <model>` |
| Python packages | PyQt5, OpenCV, NumPy (system packages) | apt |

## Not needed

- No GPU workstation, no cloud account, no API keys.
- No calibration checkerboard: calibration uses a block and the robot itself.
- No depth camera, as long as all blocks have the same height.
