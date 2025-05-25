# 🖥️ VPN + SSH (WireGuard + NUC)

## Что хочу

-   Подключаться к своему NUC и Raspberry Pi 4 по SSH из интернета
-   Поднять VPN-сервер на NUC (через WireGuard) для ROS2 в будущем
-   Автоматически подключать Pi к VPN при старте
-   Всё должно работать и снаружи, и внутри домашней сети
-   У меня есть внешний статический IP: `180.150.8.37`

## Устройства

-   💻 MacBook (vpn: `10.32.0.2`)
-   🖥️ Intel NUC (rabbit-server, VPN-сервер, vpn: `10.32.0.1`)
-   🐰 Raspberry Pi 4 (rabbit, VPN-клиент, vpn: `10.32.0.3`)

## IP + порты (через UniFi: Settings -> Security -> Port Forwarding)

| Назначение        | IP внутри    | Порт снаружи | Порт внутри | Устройство   |
| ----------------- | ------------ | ------------ | ----------- | ------------ |
| rabbit-server-vpn | 192.168.1.50 | 51820        | 51820 (UDP) | NUC (сервер) |
| rabbit-server-ssh | 192.168.1.50 | 2222         | 22          | NUC          |
| rabbit-ssh        | 192.168.1.51 | 2223         | 22          | Raspberry Pi |

## WireGuard сервер (NUC)

```ini
[Interface]
Address = 10.32.0.1/24
PrivateKey = <NUC_PRIVATE_KEY>
ListenPort = 51820
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT

# Mac
[Peer]
PublicKey = <MAC_PUBLIC_KEY>
AllowedIPs = 10.32.0.2/32

# Raspberry Pi
[Peer]
PublicKey = <PI_PUBLIC_KEY>
AllowedIPs = 10.32.0.3/32
```

## WireGuard на Mac

```ini
[Interface]
PrivateKey = <MAC_PRIVATE_KEY>
Address = 10.32.0.2/24
DNS = 1.1.1.1

[Peer]
PublicKey = <NUC_PUBLIC_KEY>
Endpoint = 180.150.8.37:51820
AllowedIPs = 10.32.0.0/24
PersistentKeepalive = 25
```

## WireGuard на Raspberry Pi

```ini
[Interface]
PrivateKey = <PI_PRIVATE_KEY>
Address = 10.32.0.3/24
DNS = 1.1.1.1

[Peer]
PublicKey = <NUC_PUBLIC_KEY>
Endpoint = 180.150.8.37:51820
AllowedIPs = 10.32.0.0/24
PersistentKeepalive = 25
```

## SSH алиасы

`~/.ssh/config` на Mac:

```sshconfig
Host rabbit-server
    HostName 180.150.8.37
    Port 2222
    User root
    IdentityFile ~/.ssh/id_rsa

Host rabbit
    HostName 180.150.8.37
    Port 2223
    User root
    IdentityFile ~/.ssh/id_rsa
```

Теперь можно:

```bash
ssh rabbit
ssh rabbit-server
```

## Как всё запускать

### Генерация ключей:

```bash
wg genkey | tee privatekey | wg pubkey > publickey
```

### Установка WireGuard:

```bash
sudo apt install wireguard wireguard-tools
```

## Автозапуск VPN

На Pi и на сервере (NUC):

```bash
sudo systemctl enable wg-quick@wg0
sudo wg-quick up wg0
sudo wg-quick down wg0
```

## UFW

```bash
sudo ufw allow 51820/udp
sudo ufw allow in on wg0
sudo ufw allow out on wg0
sudo ufw route allow in on wg0 out on eth0
```

## Отладка

-   `sudo wg` — показывает статус туннеля
-   `ping 10.32.0.1` с Mac / Pi
-   `ping 10.32.0.2`, `10.32.0.3` с NUC
-   `ssh root@10.32.0.1` из VPN — работает → 🔥

## Грабли по пути

-   ❌ Не работал ping/ssh → виноват `ufw`
-   ❌ Не было `resolvconf` → warning, но не критично
-   ❌ `wg` не работал → просто не был установлен
-   ❌ На Mac ping шёл мимо VPN → поправил `AllowedIPs` и перезапустил туннель
