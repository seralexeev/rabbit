#!/usr/bin/env bash
# One-time host setup of the Rabbit 2.0 body (Raspberry Pi 4, Raspberry Pi OS 64-bit), run as root on the Pi
# after the first boot and after scripts/deploy.sh --body has synced /root/rabbit/workspaces.
set -euo pipefail

REMOTE=/root/rabbit/workspaces
CONFIG=/boot/firmware/config.txt
CMDLINE=/boot/firmware/cmdline.txt

ensure_line() {
  grep -qxF "$2" "$1" || echo "$2" >> "$1"
}

for line in \
  "dtparam=i2c_arm=on,i2c_arm_baudrate=400000" \
  "dtoverlay=i2c3,pins_4_5,baudrate=400000" \
  "dtoverlay=i2c4,pins_6_7,baudrate=400000" \
  "dtoverlay=i2c5,pins_10_11,baudrate=400000" \
  "dtoverlay=i2c6,pins_22_23,baudrate=400000" \
  "dtoverlay=disable-bt" \
  "dtoverlay=uart4" \
  "dtoverlay=uart5" \
  "dtoverlay=i2c-rtc,ds3231" \
  "dtoverlay=gpio-poweroff,gpiopin=17" \
  "dtparam=watchdog=on"; do
  ensure_line "$CONFIG" "$line"
done

grep -q "pinctrl_bcm2835.persist_gpio_outputs=n" "$CMDLINE" || sed -i '1 s/$/ pinctrl_bcm2835.persist_gpio_outputs=n/' "$CMDLINE"
sed -i 's/ console=serial0,[0-9]*//' "$CMDLINE"
systemctl disable --now serial-getty@ttyAMA0.service 2> /dev/null || true

mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=15\n' > /etc/systemd/system.conf.d/rabbit-watchdog.conf

nmcli connection show rabbit-brain > /dev/null 2>&1 \
  || nmcli connection add type ethernet ifname eth0 con-name rabbit-brain ipv4.method manual ipv4.addresses 10.77.0.1/30 ipv6.method disabled

apt-get update
apt-get install -y chrony python3-venv i2c-tools zstd rsync
cat > /etc/chrony/conf.d/rabbit.conf <<'EOF'
allow 10.77.0.0/30
local stratum 10
rtcsync
EOF
systemctl restart chrony

command -v docker > /dev/null || curl -fsSL https://get.docker.com | sh

python3 -m venv /opt/rabbit-host
/opt/rabbit-host/bin/pip install --quiet nats-py "gpiod>=2.2"

install -m 644 "$REMOTE/body/rabbit-power.service" /etc/systemd/system/rabbit-power.service
systemctl daemon-reload
systemctl enable rabbit-power.service

echo "Reboot to apply config.txt, cmdline.txt and the watchdog; then check:"
echo "  cat /sys/module/pinctrl_bcm2835/parameters/persist_gpio_outputs   (must be N)"
echo "  ls /dev/ttyAMA* /dev/i2c-*                                       (ttyAMA0 RoboClaw, the UART4 device for LIDAR_PORT, i2c-1/3/4/5/6)"
