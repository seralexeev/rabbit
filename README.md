# rabbit [rabbit0.dev](https://rabbit0.dev)

The robot code (`workspaces/rabbit`), the web HUD (`workspaces/web`, served by the robot at https://jetson.rabbit on the LAN and publicly at https://live.rabbit0.dev through revocable links from `scripts/links.sh`) and Forge, its telemetry analytics and agent (`workspaces/forge`). `AGENTS.md` and the skills in `.claude/skills` explain how to run, deploy and develop all of it. The notes below are hardware and setup scratch notes.

## Work log and blog

Every piece of significant work leaves two traces, written as part of the work, not afterwards:

1. **Engineering log** in `docs/` (English, factual): `docs/log/YYYY-MM-DD-<topic>.md` with the goal, what was tried and dropped and why, what worked, numbers, root causes and open questions; `docs/README.md` keeps the current state of the system up to date, and `docs/lessons.md` collects the rules learned the hard way.
2. **Blog post** at [rabbit0.dev](https://rabbit0.dev), repo [seralexeev/rabbit0](https://github.com/seralexeev/rabbit0) (cloned at `~/projects/rabbit0`): short entries in the author's voice in `README.ru.md`, the English version in `README.md`, media in `static/media/<id>-<n>.jpg|mp4`. Build with `npm ci --registry=https://registry.npmjs.org/` once, then `OPENAI_API_KEY=unused node src/index.ts` (the key is only needed when an entry has no English version yet), and publish by pushing `main`: Cloudflare serves the result.

## Access links

The public HUD at https://live.rabbit0.dev opens only through a personal link; the LAN address stays open. Ask the agent "give me a link" (optionally "for Alice") or "remove Alice's link", or run it yourself:

```sh
scripts/links.sh              # list: name, date, link
scripts/links.sh add alice    # create a link, prints https://live.rabbit0.dev/k/<token>
scripts/links.sh rm alice     # revoke it: the open HUD is cut off within ~5 s
```

The registry lives only on the robot, in `/root/rabbit/workspaces/links/links.map`. Details are in the `rabbit-robot` skill.

![whiteboard excalidraw](https://github.com/user-attachments/assets/90191113-4795-4add-820a-ea3d4afff8f1)

![146-1](https://github.com/user-attachments/assets/46094498-2394-4d8f-b6d4-94cd619eff84)


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

scripts/deploy.sh rabbit-roboclaw

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
  stereolabs/zed:5.2-tools-devel-jetson-jp6.1.0 bash
```

### ZED SDK stubs

```
curl -sL https://download.stereolabs.com/zedsdk/5.5/whl/linux_aarch64/pyzed-5.5-cp310-cp310-linux_aarch64.whl | bsdtar -xOf - pyzed/sl.pyi > workspaces/rabbit/src/pyzed/sl.pyi
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
