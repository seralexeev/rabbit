# Jetson host diet and Python 3.12 prep

Date: 2026-10-03. Prepared offline while the robot was off; nothing has run on the robot yet.

## Host diet

The audit (`docs/reports/2026-10-03-jetson-audit.md`) found services a headless robot does not need: snapd with chromium, cups, gnome and mesa snaps (27 MB anonymous, about 550 MB page cache, 2.3 GB of disk, and snap refreshes on the live robot five minutes after boot), cups listening on 0.0.0.0:631, rpcbind on :111, ModemManager (no modem), networkd-dispatcher (the network is NetworkManager's), nvargus-daemon (no CSI camera), apport, unattended upgrades; `logrotate.service` failing on every run because `/etc/logrotate.d/jetson-logging` (Jetson Platform Services, unused) names a missing user; and a volatile journal, so nothing survives a reboot.

`workspaces/jetson/diet.sh` does all of it, idempotently, with `--dry-run`:

- removes the snaps over up to three passes (content snaps can only go after the apps that use them), then purges `snapd` and the `chromium-browser` transitional package only when `apt-get -s purge` shows nothing else would be removed; otherwise it keeps the package and masks `snapd.service`, `snapd.socket` and `snapd.seeded.service`. An apt pin keeps snapd from coming back;
- stops and masks the services (masked, because ModemManager and cups are D-Bus or socket activated), and the apt-daily timers, with `20auto-upgrades` set to 0 (backup in `/var/backups/rabbit-diet/`);
- persistent journal capped at 500 MB, keeping 2 GB free;
- moves `jetson-logging` out of `/etc/logrotate.d` and resets the failed unit.

Tested in an Ubuntu 22.04 arm64 container running systemd with the same packages and a broken `jetson-logging`: the first run made 19 changes, the second none; with `ubuntu-server-minimal` installed (which depends on snapd) the purge is refused and snapd masked instead. `shellcheck` is clean. Expected gain from the audit: about 60–80 MB of anonymous memory and 650 MB of page cache, 2.3 GB of disk, ports 111 and 631 closed, no background snap or apt activity. The `uv run` wrappers the audit also counted (about 240 MB) are a separate compose change.

`scripts/deploy.sh` now ends with `docker image prune -f` (dangling images only): every `--build` left the previous 11 GB `rabbit` image behind, 77 GB in total on 3 October.

## Python 3.12

`docs/reports/2026-10-03-python312.md` and `.patch`: Python 3.10 support ends on 2026-10-31. The patch moves the robot code to a uv-managed CPython 3.12.11 inside the existing JetPack 6.1 image, installs the Stereolabs cp312 pyzed wheel into `/opt/pyzed`, builds `rabbit_nvblox` against 3.12 and pins `requires-python` with a re-resolved lock. The test suite passes under 3.12 (on the Mac and on Linux arm64) apart from two simulator cases that fail identically under 3.10; the simulator used about 10 % less CPU under 3.12. Not applied yet: applying only the `pyproject.toml` half would make `uv sync` in the old image switch the nodes to a 3.12 venv without pyzed.
