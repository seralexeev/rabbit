#!/usr/bin/env bash
set -euo pipefail

DRY=0
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
    DRY=1
elif [[ $# -gt 0 ]]; then
    echo "usage: $0 [--dry-run]" >&2
    exit 2
fi

if [[ $EUID -ne 0 ]]; then
    echo "run as root" >&2
    exit 1
fi

BACKUP=/var/backups/rabbit-diet
CHANGED=0

say() { printf '%-7s %s\n' "$1" "$2"; }

act() {
    local what=$1
    shift
    CHANGED=$((CHANGED + 1))
    if [[ $DRY -eq 1 ]]; then
        say would "$what"
    else
        say change "$what"
        "$@"
    fi
}

unit_exists() { [[ -n "$(systemctl list-unit-files --no-legend "$1" 2>/dev/null)" ]]; }

KEEP=(jtop.service NetworkManager.service docker.service containerd.service ssh.service rabbit-performance.service nvpmodel.service)

STOP=(
    ModemManager.service
    networkd-dispatcher.service
    nvargus-daemon.service
    rpcbind.service
    rpcbind.socket
    lpd.service
    cups.service
    cups.socket
    cups.path
    cups-browsed.service
    apport.service
    apport-autoreport.path
    apport-autoreport.timer
    whoopsie.service
    whoopsie.path
    unattended-upgrades.service
    apt-daily.timer
    apt-daily-upgrade.timer
)

echo "== memory before"
free -m

echo "== snap"
if command -v snap >/dev/null 2>&1; then
    remaining=$(snap list 2>/dev/null | awk 'NR > 1 && $1 != "snapd" {print $1}' | grep -vxE 'core[0-9]*|bare' || true)
    remaining="$remaining $(snap list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -xE 'core[0-9]*|bare' || true)"
    for pass in 1 2 3; do
        left=""
        for name in $remaining; do
            if [[ $DRY -eq 1 ]]; then
                act "snap remove --purge $name" true
            elif snap remove --purge "$name" >/dev/null 2>&1; then
                act "snap remove --purge $name" true
            else
                left="$left $name"
            fi
        done
        remaining=$left
        [[ -z "${remaining// /}" || $DRY -eq 1 ]] && break
        say retry "pass $pass left:$remaining"
    done
    if [[ -n "${remaining// /}" ]]; then
        say warn "could not remove snaps:$remaining"
    fi
else
    say ok "no snap command"
fi
snapd_gone=1
purge=()
for package in snapd chromium-browser; do
    if [[ "$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null)" == installed ]]; then
        purge+=("$package")
    fi
done
if [[ ${#purge[@]} -gt 0 ]]; then
    removes=$(apt-get -s purge "${purge[@]}" 2>/dev/null | awk '$1 == "Purg" {print $2}' | sort)
    extra=$(grep -vxE 'snapd|chromium-browser' <<<"$removes" || true)
    if [[ -n "$extra" ]]; then
        say warn "keeping the snapd package: apt would also remove $(tr '\n' ' ' <<<"$extra")"
        snapd_gone=0
        for unit in snapd.service snapd.socket snapd.seeded.service; do
            if [[ "$(systemctl is-enabled "$unit" 2>/dev/null || true)" != masked ]]; then
                act "stop and mask $unit instead" sh -c "systemctl stop '$unit' 2>/dev/null || true; systemctl mask '$unit' >/dev/null"
            fi
        done
    else
        if apt-mark showhold 2>/dev/null | grep -qx snapd; then
            act "apt-mark unhold snapd" apt-mark unhold snapd
        fi
        act "apt-get purge ${purge[*]}" env DEBIAN_FRONTEND=noninteractive apt-get purge -y "${purge[@]}"
    fi
else
    say ok "snapd is not installed"
fi
if [[ $snapd_gone -eq 0 ]]; then
    :
elif [[ ! -f /etc/apt/preferences.d/no-snapd.pref ]]; then
    act "pin snapd out of apt (/etc/apt/preferences.d/no-snapd.pref)" \
        sh -c 'printf "Package: snapd\nPin: release a=*\nPin-Priority: -10\n" > /etc/apt/preferences.d/no-snapd.pref'
else
    say ok "snapd pinned out of apt"
fi
if [[ $snapd_gone -eq 1 && ( -d /var/lib/snapd || -d /snap ) ]]; then
    act "remove /var/lib/snapd and /snap leftovers" rm -rf /var/lib/snapd /snap
fi

echo "== services"
for unit in "${STOP[@]}"; do
    if ! unit_exists "$unit"; then
        say ok "$unit not installed"
        continue
    fi
    if [[ "$(systemctl is-enabled "$unit" 2>/dev/null || true)" == masked ]] && ! systemctl is-active --quiet "$unit"; then
        say ok "$unit masked"
        continue
    fi
    act "stop and mask $unit" sh -c "systemctl stop '$unit' 2>/dev/null || true; systemctl mask '$unit' >/dev/null"
done
if [[ -f /etc/apt/apt.conf.d/20auto-upgrades ]] && grep -q '"1"' /etc/apt/apt.conf.d/20auto-upgrades; then
    act "turn off periodic apt updates and unattended upgrades (20auto-upgrades)" \
        sh -c "mkdir -p '$BACKUP' && cp -n /etc/apt/apt.conf.d/20auto-upgrades '$BACKUP/' && printf 'APT::Periodic::Update-Package-Lists \"0\";\nAPT::Periodic::Unattended-Upgrade \"0\";\n' > /etc/apt/apt.conf.d/20auto-upgrades"
else
    say ok "periodic apt upgrades are off"
fi

echo "== journald"
JOURNALD=/etc/systemd/journald.conf.d/rabbit.conf
WANT=$'[Journal]\nStorage=persistent\nSystemMaxUse=500M\nSystemKeepFree=2G\n'
if [[ "$(cat "$JOURNALD" 2>/dev/null)"$'\n' != "$WANT" ]]; then
    act "persistent journal capped at 500 MB ($JOURNALD)" \
        sh -c "mkdir -p /etc/systemd/journald.conf.d && printf '%s' '$WANT' > '$JOURNALD' && mkdir -p /var/log/journal && systemd-tmpfiles --create --prefix /var/log/journal && systemctl restart systemd-journald && journalctl --flush"
else
    say ok "persistent journal configured"
fi

echo "== logrotate"
if [[ -f /etc/logrotate.d/jetson-logging ]]; then
    act "move /etc/logrotate.d/jetson-logging (unused Jetson Platform Services, breaks logrotate) to $BACKUP" \
        sh -c "mkdir -p '$BACKUP' && mv /etc/logrotate.d/jetson-logging '$BACKUP/jetson-logging' && systemctl reset-failed logrotate.service 2>/dev/null || true"
else
    say ok "jetson-logging logrotate entry removed"
fi
if [[ $DRY -eq 0 ]]; then
    if logrotate --debug /etc/logrotate.conf >/dev/null 2>&1; then
        say ok "logrotate config parses"
    else
        say warn "logrotate --debug still reports errors"
    fi
fi

echo "== kept"
for unit in "${KEEP[@]}"; do
    if unit_exists "$unit"; then
        say ok "$unit $(systemctl is-enabled "$unit" 2>/dev/null || true) $(systemctl is-active "$unit" 2>/dev/null || true)"
    fi
done

if [[ $DRY -eq 1 ]]; then
    echo "== dry run: $CHANGED change(s) pending"
else
    echo "== $CHANGED change(s) made; memory after"
    free -m
fi
