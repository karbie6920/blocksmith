#!/bin/bash
# Installs the magician_ros2 driver for the Dobot Magician into ~/dobot_ros_ws
# and applies the changes needed on a Jetson (ARM, robot on /dev/ttyACM0).
#
# Requires ROS 2 Humble (ros-humble-desktop, ros-dev-tools) to be installed first.
# Assembled from steps that were run by hand; review before running on a new system.
set -e

WS="$HOME/dobot_ros_ws"
PORT="/dev/ttyACM0"          # serial port of the robot
USB_ID="1a86:55d4"           # USB ID of the robot's serial adapter (see: lsusb)

source /opt/ros/humble/setup.bash

sudo apt update
sudo apt install -y ros-humble-diagnostic-aggregator ros-humble-rqt-robot-monitor \
  ros-humble-tf-transformations python3-pykdl python3-pip python3-pyqt5 usbutils

mkdir -p "$WS"
[ -d "$WS/src/.git" ] || git clone https://github.com/jkaniuka/magician_ros2.git "$WS/src"

# 1. Serial port: the driver defaults to /dev/ttyUSB0
sed -i "s|/dev/ttyUSB0|$PORT|" "$WS/src/dobot_driver/dobot_driver/dobot_handle.py"

# 2. "Is the robot connected" check: add this adapter's USB ID
grep -rl 'QinHeng Electronics"' "$WS/src" | xargs -r sed -i "s/QinHeng Electronics\"/QinHeng Electronics|$USB_ID\"/"

# 3. Python requirements without PyQt5 (does not build from pip on ARM; the apt package is used)
grep -v -i pyqt5 "$WS/src/requirements.txt" > /tmp/dobot_requirements.txt
pip3 install -r /tmp/dobot_requirements.txt      # pybullet compiles here and can take 20-40 minutes

sudo rosdep init 2>/dev/null || true
rosdep update
cd "$WS"
rosdep install -i --from-path src --rosdistro humble -y
colcon build

# 4. Access to the serial port without sudo (needs a reboot or re-login)
sudo usermod -a -G dialout "$USER"

# 5. Environment for new terminals
grep -q "dobot_ros_ws/install/setup.bash" ~/.bashrc || cat >> ~/.bashrc <<'RC'
export LC_NUMERIC=en_US.UTF-8
export MAGICIAN_TOOL=suction_cup
source ~/dobot_ros_ws/install/setup.bash
RC

echo
echo "Done. Reboot, connect the robot, then check:  lsusb | grep ${USB_ID%%:*}   and   ls /dev/ttyACM*"
