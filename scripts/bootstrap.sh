#!/bin/bash

set -euo pipefail

WIFI_SSID="richbitch"
WIFI_PASS="maza1maza"
PUBLIC_KEY="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC7EPXIvxtZEOnQ8mQn/5jGJKj8OaBrL9/lWgBciwdMrq5ub48Yyc+OwMqyAkH2lCUii0bmDmxpKB00Rw3zPDkOe4Z61HM5ZhxpCmxb7FEmNnoHAqdJ1OctORerjhjD0MdX3xoR6sLk4D4VLLD8UiXl7vA+lv8f06ZnTRkHVX+we/n+MdEvPaWSPFCoJ2Zv9sefFJuc4k7JLGVwWTUX1xeVz6yN/MEZhLzNg3W826T63Hghe+z8SRtLtvRUSYyMxE3aSWJEQWCe0U2c3BnMZn6smulx8abwC13XN/DmZI81sW5vCAZ85mR7GVLm1eQMRpoDy+PlaXcgl9evnTqDkeWlFwKSSHrCcvPOpkb/5IMVInVrLFeGWPrhfUrw5vmuTXTRw8IhjQq4dgcCyzaXwQy0/osaNmzP9gXD/mQ1q2Gxbd20Z4+OE7Z1Fjd/suJSKfBT+nRJZRaDdfU9Yp+uvalGjGy9NjWp1ZqTNxOa2al5kxSPlf2iSRPUyBytFVkhkwMGzncoGwbViu87d9DxDOCnF94hT7qhg7CijIwu1pJ+I5imBOrrdmVLSG+XWD6TyaLtude4yAK+v5BSJI2eu4+xI7Rmtr0ZRkTk5drRYY60+5Ub14DPiPyz/1n+wJc2tXmfJIMW22lvcaPXE7jn6ET+PXKhpeNqflMXLYmaj4sumQ=="

sudo -i

# apt
apt-get update

# wifi
echo "Connecting to Wi-Fi network: $WIFI_SSID"
nmcli device wifi connect "$WIFI_SSID" password "$WIFI_PASS" || {
    echo "Failed to connect to Wi-Fi"
    exit 1
}

# ssh server
echo "Setting up ssh server"
apt-get install -y openssh-server
mkdir -p /root/.ssh
chmod 700 /root/.ssh
echo "$PUBLIC_KEY" >/root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# rabbit
hostnamectl set-hostname rabbit

# jetson-stats
pip install jetson-stats
systemctl restart jtop.service


# downgrading Docker to version 5:27.5
# https://forums.developer.nvidia.com/t/iptables-error-message/333007
apt-get install -y docker-ce=5:27.5* docker-ce-cli=5:27.5* --allow-downgrades

# downgrading snapd to version 2.47.4
# https://forums.developer.nvidia.com/t/chromium-other-browsers-not-working-after-flashing-or-updating-heres-why-and-quick-fix/338891
snap download snapd --revision=24724
snap ack snapd_24724.assert
snap install snapd_24724.snap
apt-mark hold snapd

# chromium
snap install chromium

# allow containers to communicate with X server
xhost +si:localuser:root

# pull ZED Docker images
docker pull stereolabs/zed:4.2-devel-jetson-jp6.0.0


# Install VNC
mkdir -p /lib/firmware/edid
curl -s https://raw.githubusercontent.com/linuxhw/EDID/refs/heads/master/Digital/AOC/AOC2401/405E4A30B5B3 \
  | grep -E '^([a-fA-F0-9]{32}|[a-fA-F0-9 ]{47})$' \
  | tr -d '[:space:]' \
  | xxd -r -p \
  > /lib/firmware/edid/EDID.bin

cat >/etc/X11/xorg.conf <<EOF
Section "Module"
    Disable     "dri"
    SubSection  "extmod"
        Option  "omit xfree86-dga"
    EndSubSection
EndSection

Section "Device"
    Identifier  "Tegra0"
    Driver      "nvidia"
    Option      "PrimaryGPU" "Yes"
    Option      "AllowEmptyInitialConfiguration" "true"
    Option      "ConnectedMonitor" "DFP-0"
    Option      "CustomEDID" "DFP-0:/lib/firmware/edid/EDID.bin"
    Option      "UseDisplayDevice" "DFP-0"
    Option      "IgnoreEDIDChecksum" "DFP-0"
    Option      "AllowNonEdidModes" "true"
EndSection

Section "Monitor"
    Identifier "Monitor0"
    VendorName "FakeVendor"
    ModelName  "1440x900"
EndSection

Section "Screen"
    Identifier "Screen0"
    Device     "Tegra0"
    Monitor    "Monitor0"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Modes "1440x900"
    EndSubSection
EndSection
EOF

systemctl set-default graphical.target
sed -i '/^\[daemon\]/a AutomaticLoginEnable=true\nAutomaticLogin=rabbit' /etc/gdm3/custom.conf

apt-get install -y x11vnc
sudo -u rabbit mkdir -p /home/rabbit/.vnc
sudo -u rabbit x11vnc -storepasswd "Maza1Maza" /home/rabbit/.vnc/passwd
chown rabbit:rabbit /home/rabbit/.vnc/passwd
chmod 600 /home/rabbit/.vnc/passwd

cat >/etc/systemd/system/x11vnc.service <<EOF
[Unit]
Description=Start x11vnc at startup
After=graphical.target
Requires=graphical.target

[Service]
Type=simple
User=rabbit
ExecStart=/usr/bin/x11vnc -usepw -display :0 -forever -auth guess -ncache 10 -ncache_cr -noxdamage
Restart=on-failure

[Install]
WantedBy=graphical.target
EOF

systemctl daemon-reexec
systemctl daemon-reload
systemctl enable x11vnc.service

echo "Setup complete. Reboot to activate everything."