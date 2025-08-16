# rabbit

- **Aluminum Gantry Plate** - A plate made of aluminum that serves as a structural component in the assembly of a machine or device.
- **PCB** - Printed Circuit Board
- **Third hand** - A tool used to hold objects in place while soldering or assembling components.
- **PCB vertical/horizontal mount** - A mounting solution for PCBs that allows them to be oriented either vertically or horizontally.

When `Cannot find terminfo entry for 'xterm-ghostty'` do `export TERM=xterm-256color`

```
python3 -m venv ~/rabbit-venv

wg-quick down wg0
wg-quick up wg0

mutagen sync terminate rabbit-workspace
mutagen project start
mutagen sync flush --all
```

Blue - RX - S1
Green - TX - S2

docker compose -f compose.jetson.dev.yaml up --build rabbit-roboclaw

# Cameras

- https://caddxfpv.com/products/caddxfpv-gm1-gm2-gm3?variant=48924891611438
- Raspberry pi v2, imx219 and Raspberry pi v3, imx477
- imx477
- https://marketplace.nvidia.com/en-us/enterprise/robotics-edge/?category=cameras&page=1&limit=15
- https://forums.developer.nvidia.com/t/csi-camera-compatibility/267033
- https://shop.siyi.biz/products/siyi-a8-mini-gimbal-camera

```
docker run --rm -it \
  --privileged \
  --runtime nvidia \
  -v /tmp/argus_socket:/tmp/argus_socket \
  -v ./zed/resources:/usr/local/zed/resources \
  -v ./zed/config:/usr/local/zed/config \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all \
  stereolabs/zed:5.0-tools-devel-jetson-jp6.0.0 bash
```

### ZED SDK stubs

```
curl -sL https://download.stereolabs.com/zedsdk/5.0/whl/linux_aarch64/pyzed-5.0-cp310-cp310-linux_aarch64.whl | bsdtar -xOf - pyzed/sl.pyi > workspaces/rabbit/src/pyzed/sl.pyi
```

# INA

$ i2cdetect -y -r 7
0 1 2 3 4 5 6 7 8 9 a b c d e f
00: -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: 40 41 -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- --

41 - INA4235

# nvblox

```
cd /workspaces/nvblox
rm -rf build
mkdir build && cd build

cmake .. \
    -DBUILD_PYTORCH_WRAPPER=ON \
    -DCMAKE_PREFIX_PATH=$(python3 -c 'import torch;print(torch.utils.cmake_prefix_path)')

make -j$(nproc)

cd ../nvblox_torch
pip3 install --editable .

```
