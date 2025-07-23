# rabbit

- 🌍 [VPN + SSH](./docs/vpn_ssh.md)
- 🌚 [TIL](./docs/til.md)
- 💡 [Ideas](./docs/ideas.md)
- 📚 [ROS2](./docs/ros.md)

```
python3 -m venv ~/rabbit-venv

wg-quick down wg0
wg-quick up wg0

mutagen sync terminate rabbit-workspace
mutagen project start
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