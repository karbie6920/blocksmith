#!/bin/bash
# Starts Dobot Studio with the full ROS environment (also works from a desktop icon).
source /opt/ros/humble/setup.bash
[ -f "$HOME/dobot_ros_ws/install/setup.bash" ] && source "$HOME/dobot_ros_ws/install/setup.bash"
export LC_NUMERIC=en_US.UTF-8
export MAGICIAN_TOOL="${MAGICIAN_TOOL:-suction_cup}"
cd "$(dirname "$(readlink -f "$0")")"
exec python3 dobot_app.py "$@"
