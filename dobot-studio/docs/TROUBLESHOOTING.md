# Troubleshooting

Problems that came up while building this project, with what fixed them.

## Robot

**The robot lamp stays red, log says "Dobot is disconnected!"**
The driver did not find the robot on USB. Check that the robot is switched on (the USB cable does not power it), that the cable is a data cable in a USB-A port, and that `lsusb | grep 1a86` shows a device. If the USB ID differs from `1a86:55d4`, add it to the check as `scripts/install_dobot_driver.sh` does.

**`/dev/ttyACM0` does not exist**
Reconnect the USB cable and look at `sudo dmesg | tail`. If the device appears on another port, change the port in `dobot_driver/dobot_driver/dobot_handle.py` and rebuild the workspace.

**"Permission denied" on the serial port**
Your user is not in the `dialout` group yet. Run `sudo usermod -a -G dialout $USER` and reboot.

**The robot's LED is red**
The controller is in an alarm state. Power the robot off and on, then run Homing.

**Moves near the edge are rejected ("The driver rejected the target")**
The driver's own kinematics check refused the point. Lower the upper reach limit in the Calibration tab, or move the work area closer to the robot.

**Many blocks are labelled "too far" or "too close to the robot"**
The work area is larger than the robot's reach. Look at the green ring and mark the work area inside it, or move the robot.

**Blocks are labelled "wrong pick height"**
The pick height from calibration is outside the allowed Z range. Repeat the calibration, or adjust `DOBOT_Z_MIN`.

**The robot misses blocks by a constant offset**
The camera or the robot has moved since calibration, or the blocks have a different height from the one used for calibration. Recalibrate with the blocks you are using.

**Cubes end up rotated in the build**
Use the two "Cube rotation correction" switches in the Build tab. Rotation is estimated from the image to within a few degrees, so tall towers can twist slightly.

## Camera

**Log repeats "Ignoring device info: MXID: ..., Name: 169.254.1.222"**
The camera was found, but the address in the app's **Camera address** field does not match it exactly. Retype the address or clear the field.

**`X_LINK_DEVICE_NOT_FOUND`**
The driver cannot reach the camera. Check `ping 169.254.1.222`. Close OAK Viewer or any other program using the camera: it accepts one connection only.

**The Ethernet port shows "connecting (getting IP configuration)" forever**
The camera is connected directly, so there is no DHCP server. Run `scripts/setup_oak_poe_network.sh` to give the port a link-local address.

**Ping to the camera drops packets or answers only once**
Another program keeps connecting to the camera, which reboots it each time. Find it with `pgrep -a -f "oak-viewer|depthai|component_container"` and stop it. If nothing is running, suspect the PoE power.

**Things outside the table are detected as blocks**
Mark the work area. Only the inside is analysed.

**Wrong colours are detected, or the table is detected**
Teach the colours again under the current lighting, and raise the saturation threshold. Use "Show what the app treats as coloured" to see what is being picked up.

## Ollama

**The model list is empty**
Ollama is not running or has no model. Check `ollama list`; pull a model with `ollama pull <name>`, then click Refresh.

**Proposals are all "built-in template"**
Ollama did not answer in time, returned something unusable, or returned fewer than three buildable plans. Try a different model. Small models sometimes ignore the JSON format.

**Proposals take very long**
The first request loads the model into memory. Later requests are faster. Use a smaller model if it stays slow.

## Jetson

**Chromium or other snap apps do not start on JetPack 6**
A known problem with newer `snapd` versions on Jetson. Pinning `snapd` to revision 24724 fixed it here:

```bash
snap download snapd --revision=24724
sudo snap ack snapd_24724.assert
sudo snap install snapd_24724.snap
sudo snap refresh --hold snapd
```

**`pip3 install -r requirements.txt` of the Dobot driver fails on PyQt5**
PyQt5 does not build from pip on ARM. Install the other requirements and use the system package (`python3-pyqt5`), as the install script does.

**ROS tools print or parse numbers with a comma**
Set `export LC_NUMERIC=en_US.UTF-8` in `~/.bashrc`. `dobot-app.sh` sets it for the app.

**After copying the system from SD to NVMe the Jetson stops at "can't find UUID"**
On this setup two things were needed, done while booted from the SD card: grow the root partition on the SSD (`growpart`, `resize2fs`), and set `root=/dev/nvme0n1p1` in `/boot/extlinux/extlinux.conf` on the SSD. Also finish any interrupted `apt` upgrade (`sudo dpkg --configure -a`) before copying, so that the boot image is rebuilt.

## App

**The window does not open: "ROS environment or dobot_web.py not found"**
Start the app with `bash dobot-app.sh`, not with `python3 dobot_app.py`, so that ROS and the Dobot workspace are sourced.

**A driver lamp says "running (started outside the app)"**
The driver is already running in a terminal. The app will not start a second copy. Stop the terminal one if you want the app to manage it.

**Start over**
Delete `dobot_app.json` next to the app. All settings, colours and calibration are reset.
