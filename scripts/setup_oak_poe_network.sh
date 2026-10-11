#!/bin/bash
# Gives the Jetson's Ethernet port a link-local address (169.254.x.x) so it can reach
# an OAK PoE camera connected directly through a PoE injector or PoE switch, without a router.
# Wi-Fi keeps providing internet access.
#
# Usage: bash setup_oak_poe_network.sh [interface]
set -e

IFACE="${1:-$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="ethernet" && $1 !~ /^usb/ {print $1; exit}')}"
[ -n "$IFACE" ] || { echo "No Ethernet interface found. Pass its name as the first argument (see: nmcli device status)."; exit 1; }
echo "Using interface: $IFACE"

if nmcli -t -f NAME connection show | grep -qx "oak"; then
  echo "Connection 'oak' already exists."
else
  sudo nmcli connection add type ethernet ifname "$IFACE" con-name oak ipv4.method link-local ipv6.method ignore
fi
sudo nmcli connection modify oak connection.autoconnect-priority 10
sudo nmcli connection up oak

ip -br addr show "$IFACE"
echo "Now try:  ping -c 4 169.254.1.222   (the camera needs about 30 s after power-up)"
