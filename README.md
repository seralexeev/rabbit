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