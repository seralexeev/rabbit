# Аудит Jetson робота Rabbit: софт, ресурсы, обновления

Дата: 2026-10-03 (AEST), робот `rabbit` (192.168.1.53). Аудит только на чтение: ничего не ставилось, не перезапускалось, в NATS ничего не публиковалось.
Снимок «сейчас» сделан через ~8–14 минут после загрузки, когда камера в режиме ожидания (`Async task capture: 1.00 tps`, GPU 0%). Цифры под нагрузкой взяты из Forge (`forge.jetson`, `forge.jetson_containers`) за 2026-10-01…02.

---

## 0. Коротко

| # | Вывод | Важность |
|---|---|---|
| 1 | В apt-кеше хоста лежит обновление L4T **36.4.4 → 36.4.7** (48 пакетов nvidia-l4t-*). В 36.4.7 есть известная регрессия: `unable to allocate CUDA0 buffer`. Обычный `apt upgrade` может сломать ZED/nvblox/TensorRT | **высокая, легко предотвратить** |
| 2 | **OC3 срабатывает ~28 раз в секунду даже в простое** (709 → 1131 за 15 с; `oc3_throt_en=1`). 2026-10-02 с 00:06 до ~01:30 UTC после пика 17 Вт клоки держались ниже нормы ~85 минут: CPU кластер 0 = 730–1574 МГц, GPU = 306–714 МГц вместо 1728/1020. Безопасно для железа, но производительность это снижает | высокая (производительность) |
| 3 | Snap-ы (chromium, cups, gnome, mesa) **сами обновляются на живом роботе**: последнее обновление 07:48 сегодня, через 5 минут после загрузки | средняя |
| 4 | Девять обёрток `uv run` висят родительскими процессами и занимают **~240 МБ PSS** RAM, при том что под нагрузкой RAM уже 7.0–7.7 ГБ из 7.6, а swap доходил до 3 ГБ | средняя, почти без риска |
| 5 | Docker: 232 образа, **77 ГБ можно освободить**, плюс 1.9 ГБ build cache. Каждый деплой оставляет по безымянному образу на 11 ГБ | низкая (диск заполнен на 18%), но это гигиена |
| 6 | JetPack 7.2.1 (L4T 39.2.1, CUDA 13.2, Ubuntu 24.04) уже поддерживает Orin Nano, но переход требует полной перепрошивки и пересборки всего. **Сейчас не обновляться.** Разумный шаг — JetPack 6.2.3 (L4T 36.5.2) через apt, когда будет окно для работ | — |
| 7 | ZED SDK 5.5.0 — последняя версия, патчей 5.5.x нет. Явного исправления «трансляция в мм после релокализации» или «зависание grab() после релокализации» в release notes нет | — |
| 8 | Журнал systemd не сохраняется между перезагрузками, а RTC не держит время: после загрузки часы сначала идут неверно (2026-03-25, затем 23:17 вместо 07:43), пока NTP их не исправит. Поэтому разобрать троттлинг 00:06 по логам задним числом нельзя | средняя (диагностика) |

---

## 1. Версии

### Хост
| Компонент | Версия | Комментарий |
|---|---|---|
| Модуль | Jetson Orin Nano Engineering Reference Developer Kit **Super** (p3767-0003 / p3768) | nvpmodel → `nvpmodel_p3767_0003_super.conf` |
| L4T | **R36.4.4** (GCID 41062509, 2025-06-16) = **JetPack 6.2.1** | `nvidia-l4t-core 36.4.4-20250616085344` |
| Метапакет `nvidia-jetpack` | не установлен | компоненты поставлены по отдельности |
| Bootloader / QSPI | **36.4.4**, слот A активен, оба слота `normal`, capsule status 0 | |
| Ядро | 5.15.148-tegra (OOT-вариант), PREEMPT | |
| Ubuntu | 22.04.5 LTS | |
| CUDA | 12.6 (nvcc V12.6.68, toolkit 12.6.11) | |
| cuDNN | 9.3.0.75 | |
| TensorRT | 10.3.0.30 (+cuda12.5) | |
| VPI | 3.2.4 | |
| OpenCV (хост) | 4.8.0 (NVIDIA) + 4.5.4 из Ubuntu | |
| Docker | 27.5.1 (rootless-extras 28.3.2), compose 2.38.2, buildx 0.25.0 | |
| containerd | 1.7.27 | |
| nvidia-container-toolkit | **1.16.2** | старая версия, см. §4 |
| apt-источники NVIDIA | `repo.download.nvidia.com/jetson/{common,t234,ffmpeg} r36.4` | |
| Режим питания | MAXN_SUPER (mode 2), `jetson_clocks` активен: CPU 1728 МГц (6 ядер), GPU 1020 МГц, EMC 3199 МГц | |
| Wi-Fi | rtl8822ce `v5.14.0.4-250-g5d0d248cc.20240517`, из пакета `nvidia-l4t-kernel-oot-modules`; `/etc/modprobe.d/rabbit-wifi.conf: options rtl8822ce rtw_tx_pwr_lmt_enable=0`; 5 ГГц, 80 МГц, −58 dBm, TX 780 Мбит/с | при обновлении L4T модуль будет заменён (см. §3) |

### Контейнеры
| Контейнер | Образ / версия |
|---|---|
| rabbit-zed (и все `rabbit-*`) | `rabbit:latest`, база `stereolabs/zed:5.5.0-tools-devel-jetson-jp6.1.0` (Ubuntu 22.04.3, CUDA 12.6) |
| ZED SDK | **5.5.0** (`sl.Camera.get_sdk_version()`) |
| Прошивка ZED 2i | **1523**, S/N 31819002, USB 3 (5 Гбит/с) через встроенный хаб Realtek 0bda:0489 |
| Python в venv | **CPython 3.10.0** (uv python-build-standalone; `requires-python = "==3.10.0"`); venv создан uv 0.8.14, в образе uv 0.12.22 |
| numba / llvmlite / numpy | 0.68.0 / 0.50.0 / 2.2.6 |
| opencv-python | 4.12.0 |
| tensorrt / torch в venv | нет (TensorRT берётся из системы через PYTHONPATH `/usr/local/lib/python3.10/dist-packages`) |
| nvblox | исходники с коммита 23d35fc, nanobind-обёртка `/opt/rabbit_nvblox` |
| forge-writer / forge-chat | `node:26-alpine`, Node **v26.10.0**, pnpm 12.4.1 |
| forge-clickhouse | **26.1.12.23** (`26.1-alpine`) |
| nats | **v2.11.6** (`nats:latest`, скачан 2025-07-01) |
| rabbit-web | nginx 1.29.8 (`1.29-alpine`) |
| tunnel | cloudflared 2026.9.0 |
| nats-dashboard | `mdawar/nats-dashboard:latest` (образ двухлетней давности) |
| nats-init | `bitnami/natscli:latest` (Bitnami перенёс бесплатные образы в `bitnamilegacy`, обновлений там не будет) |

### Накопитель
Samsung 990 PRO 1 ТБ (NVMe): `critical_warning 0`, износ 0%, запас 100%, 0 media errors, 40/48 °C, 63 часа работы, **93 небезопасных выключения из 104 циклов питания**. Робот почти всегда выключается без shutdown. Для ext4 и ClickHouse это риск, и стоит выключать штатно (скилл `rabbit-robot` умеет).
`/` ext4 915 ГБ, занято 150 ГБ (18%). `/mnt/32GB.swap` — 33 ГБ, `/var/lib/snapd` — 2.3 ГБ, `/root` — 18 ГБ (`/root/nvblox` 4.1 ГБ и `/root/nvblox_deps` 3.9 ГБ, похоже, остались от старых сборок).

---

## 2. Ресурсы

### Память
Сейчас (простой): used 4.3 ГБ, available 3.1 ГБ из 7.6 ГБ, swap 0. CMA 256 МБ (свободно 14 МБ).
Swap: zram 6 × 635 МБ (lzo-rle, prio 5) + файл `/mnt/32GB.swap` 32 ГБ (prio −2), `vm.swappiness=10` (из `rabbit-performance`). PSI в ядре выключен.

**Под нагрузкой (Forge):**

| Час UTC | CPU avg % | GPU avg % | RAM max ГБ | swap max МБ |
|---|---|---|---|---|
| 10-01 22:00–23:00 | 50–52 | 25 | 6.7–7.05 | ~1000 |
| 10-02 00:00–01:00 | 56–57 | 51–54 | 6.2–6.9 | 350–1070 |
| 10-02 07:00 | 66 | 29 | **7.73** | **2982** |
| 10-02 08:00–13:00 | 21–38 | 4–18 | 5.8–7.2 | 250–620 |

Память на пределе. Пики swap в основном вызваны разовыми dev-контейнерами (nvblox-build, zedlab, zedtest и десятки `happy_gagarin`-подобных: до 3.6 ГБ каждый, по 200% CPU), запущенными рядом со штатным стеком. Штатный стек сам по себе укладывается в ~4–5 ГБ.

Память по контейнерам (окно 10-01 22:00 – 10-02 14:00 UTC; p50 / max, МБ):

| Контейнер | p50 | max | CPU avg / p95, % ядра |
|---|---|---|---|
| rabbit-zed | 1977 | **4651** | 17 / 221 |
| forge-clickhouse | 862 | 944 (лимит 900m) | 15 / 46 |
| rabbit-planner | 168 | 253 | 12 / 95 |
| forge-chat | 120 | 250 | 2 / 3 |
| rabbit-explore | 65 | 242 | 2 / 3 |
| forge-writer | 109 | 204 | 7 / 13 |
| rabbit-telemetry | 68 | 307 | 2 / 2 |
| nav / nats / roboclaw / tunnel / ina / steering | 46–57 | 57–93 | 1–10 |
| nats-dashboard / rabbit-web | 11–14 | 21–44 | 0–2 |

Топ RSS сейчас: zed.py 1.9 ГБ (nvmap ~550 МБ), clickhouse 630 МБ, explore.py и planner.py по ~250 МБ (numba/LLVM), forge writer 164 МБ, chat 145 МБ, dockerd 134 МБ, containerd 54 МБ, snapd 53 МБ.

**Находка: обёртки `uv run`.** В каждом из 9 `rabbit-*` контейнеров `uv run src/node/X.py` остаётся родителем python-процесса: RSS ~46–53 МБ, Private_Dirty 22–31 МБ, **PSS ~27–33 МБ на каждую, итого ~240 МБ**. Кроме того, при каждом старте uv проверяет и при необходимости синхронизирует venv, то есть делает лишнюю работу и может уйти в сеть.

### CPU / GPU / питание
- Простой: CPU ~11% в среднем (zed.py 34% одного ядра, ina 7%, roboclaw 6%, clickhouse 4%, writer 4%, nav 4%, nats 3.5%, jtop 2.3%), GR3D 0%, EMC 1%, VDD_IN ~7.5 Вт, Tj 49 °C.
- Под нагрузкой (10-01…02): CPU avg 40–52%, p95 64–79%, отдельные ядра упираются в 100%; GPU avg 20–25%, p95 50–83%; мощность avg 10–12 Вт, пик 17.1 Вт; Tj max 60.6 °C, вентилятор до 71%. Температурного запаса много.
- IRQ: xhci → CPU2, UART 3100000 → CPU4, i2c c250000 → CPU5, остальное на 0-5. `rabbit-performance` отработал успешно.

**Находка: OC3 и троттлинг.**
- `soctherm_oc`: `oc3_event_cnt` = 379 через 8 мин после загрузки, 709 → 1131 за ~15 с в простое (~28 событий/с). `oc1/oc2 = 0`, троттлинг включён для всех трёх.
- INA3221: VDD_IN 4.99 В, 2.23 А, crit/max = 4984 мА. По току до порога далеко, поэтому OC3 здесь, скорее всего, срабатывает по просадке/порогу входного питания, а не по реальному перегрузу.
- 2026-10-02 00:06:06 UTC: пик 17.1 Вт / 3.46 А, после него ~85 минут (4279 односекундных отсчётов за 2 дня) CPU кластер 0 работал на 730–1574 МГц, а GPU на 306–714 МГц, тогда как ядра 4–5 оставались на 1728. Батарея при этом 15.7–16.7 В, Tj 56 °C. Ещё один короткий эпизод был в 08:15 (CPU 981). Похоже, что клоки после OC не вернулись в состояние `jetson_clocks` до перезагрузки. Журнал той загрузки не сохранился (§2, журнал), поэтому точно подтвердить нельзя.
- Вывод: для железа OC3 действительно безвреден, но производительность он может срезать надолго. Нужна проверка на стенде (см. рекомендации).

### Сервисы systemd (default target: multi-user)
Работают 39 сервисов. Ненужное для headless-робота (замеры cgroup `memory.current`, у snapd/cups это в основном file cache):

| Сервис | RAM | Что даёт отключение |
|---|---|---|
| snapd (+ snap-ы chromium, cups, gnome-42/46, gtk-themes, mesa-2404, core22/24, bare) | anon 27 МБ, file cache 549 МБ | исчезают автообновления snap на живом роботе, освобождается 2.3 ГБ диска и ~25 loop-маунтов. snapd уже стоит в `apt-mark hold` |
| snap.cups.cupsd + cups-browsed | ~3 МБ anon + ~100 МБ cache, порт **631 открыт на 0.0.0.0** | безопасность, немного RAM |
| lpd (lpr) | <1 МБ | |
| ModemManager | 8 МБ | модема нет |
| networkd-dispatcher | 20 МБ | сеть ведёт NetworkManager, а не systemd-networkd |
| nvargus-daemon | 15 МБ | CSI-камер нет. ZED SDK в контейнере пытается к нему подключиться и пишет ошибки Argus, но сокет туда не проброшен, так что демон всё равно не используется |
| bluetooth | 2 МБ | спарена только мышь MX Master 3. Если BT-геймпада нет, можно выключить |
| avahi-daemon | 2 МБ | mDNS. Если не заходите как `rabbit.local`, можно выключить |
| kerneloops, rpcbind (порт 111 открыт), openvpn (enabled), apport-autoreport, motd-news/update-notifier/fwupd-refresh/ua-timer timers | ≤1–5 МБ | шум и мелкие фоновые пробуждения |
| jtop | 31 МБ, 2.3% CPU | **нужен**: `rabbit-telemetry` читает `/run/jtop.sock` |
| haveged | 5 МБ | можно оставить |

Итого по RAM: **~300–350 МБ анонимной памяти** (uv-обёртки ~240 + сервисы ~60–80) плюс ~650 МБ page cache от snap/cups. CPU выигрыш небольшой (<1%), главное — убрать фоновые всплески от snap refresh, apt timers и apport.

Прочее:
- `logrotate.service` **падает при каждом запуске**: `/etc/logrotate.d/jetson-logging` (пакет `nvidia-jetson-services`) ссылается на `/data/logging-volume` с пользователем `logging`. Из-за этой ошибки logrotate пропускает остальные секции файла. Docker-логи ограничены через compose (`json-file 20m × 3`), так что место не кончается, но юнит в состоянии failed.
- Журнал: `/var/log/journal` нет, поэтому журнал хранится в RAM и теряется при перезагрузке. `--list-boots` показывает одну загрузку с началом «2026-03-25», то есть RTC не держит время: `hwclock` получает timeout на `/dev/rtc0`, а `rabbit-performance` записан как запущенный в «23:17», хотя загрузка была в 07:43. Скорее всего, нет батарейки RTC на несущей плате.
- Открытые порты на 0.0.0.0: 22, 111 (rpcbind), 443, 631 (cups), 4222/9222/8222 (NATS), 8000 (nats-dashboard), 18123 (ClickHouse; у forge_writer/forge_reader пароли совпадают с именами). ufw неактивен. Пока робот только в домашнем LAN, это допустимо, наружу смотрит только cloudflared → nginx.

### Docker
- `docker system df`: Images 232 (активны 9), **78.6 ГБ, из них 77.4 ГБ можно освободить**; build cache 595 записей / 1.9 ГБ; volumes 5 (3 анонимных старых).
- 11 безымянных образов `rabbit` по ~11 ГБ только за последние 36 часов: каждый `deploy.sh` пересобирает образ и оставляет предыдущий висеть. Плюс старые `workspaces-rabbit-{camera,camera-host,nvblox,webrtc,perception}`, `test`, `workspaces-test`, `nvblox_deps`, `stereolabs/zed:4.2*/5.0*` (по 13–16 ГБ). Слои у них частично общие, поэтому реально освободится меньше, чем сумма размеров, но порядок — десятки ГБ.
- Остановленные контейнеры: `xenodochial_cray`, `funny_williamson` (zed 4.2, 14 месяцев).
- `daemon.json` содержит только nvidia runtime, без `default-runtime` и `log-opts`. Для контейнеров вне compose (dev-запуски) ротации логов нет.

---

## 3. Обновление JetPack / L4T

### Что есть сейчас (октябрь 2026)
| Ветка | Версия | L4T | Ключевое |
|---|---|---|---|
| JetPack 6 (наша) | **6.2.3** (2026-08-12) | **36.5.2** | Ubuntu 22.04, ядро 5.15, CUDA 12.6, TRT 10.3, cuDNN 9.3, тот же набор библиотек, что в 6.2.1/6.2.2. Исправления багов и уязвимостей. Ставится через apt |
| | 6.2.2 | 36.5.0 | исправляет регрессию CUDA-аллокаций, появившуюся в 36.4.7. Были жалобы: snap-приложения (chromium) после 36.5 работают плохо (SELinux/AppArmor), удалён 7 W режим, UART ttyTHS1, UAS-загрузка |
| | 6.2.1 (сейчас) | 36.4.4 | |
| | 36.4.7 (в r36.4-репо) | 36.4.7 | **известный баг: `unable to allocate CUDA0 buffer`**. NVIDIA советует оставаться на 36.4.4 или идти на 36.5 |
| JetPack 7 | **7.2.1** (авг. 2026) | **39.2.1** | первая 7.x с поддержкой всего Orin. Ubuntu 24.04, ядро 6.8, CUDA 13.2, cuDNN 9.20, TRT 10.16, Python 3.12. **Только перепрошивка** (USB ISO или SDK Manager), apt-пути нет. По умолчанию прошивается с Super-конфигурацией |

### Совместимость нашего стека
- **ZED SDK 5.5.0** поддерживает JetPack 6.1/6.2 (L4T 36.4), отдельную сборку под **6.2.2 (L4T 36.5)** и **JetPack 7.2 (L4T 39.2, CUDA 13.2)**. Блокера со стороны ZED нет.
- **nvblox**: Isaac ROS 4.6 (2026-08-18) поддерживает Orin на JetPack 7.2, значит, upstream nvblox собирается с CUDA 13. Наш коммит 23d35fc (CUDA 12) придётся заменить на свежий: изменится API, потребуется перенос `native/rabbit_nvblox`.
- **TensorRT-движок YOLOE**: на JP7 его нужно пересобрать из ONNX (TRT 10.3 → 10.16). На 36.5.x пересборка не нужна.
- **numba/llvmlite**: при переходе с Python 3.10 на 3.12 numba 0.68 работает, но весь venv пересоздаётся. Попутно отпадает проблема EOL: **Python 3.10 заканчивает поддержку именно в октябре 2026**.
- **Wi-Fi rtl8822ce**: модуль приходит из `nvidia-l4t-kernel-oot-modules`. На 36.5.x это та же ветка драйвера, и параметр `rtw_tx_pwr_lmt_enable` почти наверняка сохранится. На JP7 (ядро 6.8) драйвер другой сборки, поэтому имя параметра и поведение надо проверять: `modinfo rtl8822ce | grep tx_pwr`. Сам `.conf` в `/etc/modprobe.d` при apt-обновлении не трогается, а при перепрошивке пропадёт.
- **rabbit-performance**, IRQ-пиннинг по именам `xhci-hcd`, `c250000.i2c` и по device-tree пути `serial@3100000`: на 36.5 должно работать без изменений, на JP7/ядре 6.8 имена надо перепроверить.
- **Snap**: на 36.5 snap-приложения ломаются. Это аргумент удалить snap до обновления (они нам не нужны).

### Риски и трудозатраты
| Путь | Риск | Работа | Ожидаемая польза |
|---|---|---|---|
| Ничего не делать (36.4.4) | низкий, при условии что случайный `apt upgrade` не затащит 36.4.7 | 0 | — |
| apt → **36.5.2 / JP 6.2.3** | средний: обновятся bootloader (QSPI capsule, применяется при перезагрузке), ядро, OOT-модули, Wi-Fi-драйвер. Возможны мелкие регрессии | 1–2 часа + перезагрузка + проверка ZED/nvblox/Wi-Fi. Образ `rabbit` пересобирать не обязательно: CUDA 12.6 та же, драйвер в контейнер пробрасывается с хоста | исправления безопасности, поддерживаемая ветка JP6, новее nvidia-container-toolkit (вероятно) |
| Перепрошивка → **JP 7.2.1** | высокий: полная переустановка, новый Ubuntu, новый CUDA, новые ZED SDK, nvblox, TRT, Python. Нужна резервная копия ClickHouse-тома, `zed/settings`, area-файлов, `/etc/modprobe.d`, `rabbit-performance`, ключей и `.env` | 1–3 дня | производительность почти та же (Super уже включён), ядро 6.8, поддержка Ubuntu до 2029, Python 3.12, новые версии Isaac/nvblox |

### Рекомендация
- **Сейчас**: обновлять не надо. Сразу защититься от случайного 36.4.7: `apt-mark hold 'nvidia-l4t-*'` (риск нулевой, снимается `apt-mark unhold`).
- **В ближайшее окно для работ (не во время экспериментов)**: перейти на JP 6.2.3 / L4T 36.5.2 через apt, предварительно удалив snap:
  ```
  # предварительно: штатно остановить стек, сохранить /etc/modprobe.d/rabbit-wifi.conf, zed/settings, area-файлы, том forge-clickhouse
  sed -i 's/r36\.4/r36.5/g' /etc/apt/sources.list.d/nvidia-l4t-apt-source.list
  apt-mark unhold 'nvidia-l4t-*'
  apt update && apt dist-upgrade
  apt install --fix-broken -o Dpkg::Options::="--force-overwrite"
  reboot
  # проверка: cat /etc/nv_tegra_release; nvbootctrl dump-slots-info; nvpmodel -q; modinfo rtl8822ce | grep tx_pwr; ZED + nvblox + YOLOE
  ```
  **Важно (найдено позже, см. §6.3):** с r36.5 UEFI включает DMA на `serial@3100000` (`/dev/ttyTHS1`, это RoboClaw), и драйвер обнуляет первые 96 байт приёма. До перезагрузки на 36.5.x нужно поставить DT-overlay, убирающий `dmas`/`dma-names`, и проверить `dmesg | grep 3100000` → `PIO mode`.
  Риск: средний. Откат через вторую A/B-копию загрузчика возможен, но rootfs не A/B, поэтому полный откат означает перепрошивку. Сделайте образ NVMe или хотя бы резервные копии перечисленного.
- **JetPack 7.2.x**: отложить на 2027 или до момента, когда понадобится что-то из нового стека (свежий nvblox, CUDA 13, Python 3.12). Делать как отдельный проект, заодно сменив Python 3.10.0 на 3.12 и пересобрав nvblox и TRT.

### ZED SDK
- Последняя версия — **5.5.0 (2026-09-17)**, она у нас уже стоит. Патчей 5.5.x не выходило.
- В 5.5.0 из релевантного: ускорен GEN_3 (дешевле `grab()`); исправлены «rare crashes of GEN_3 on long sessions, caused by concurrent access to the internal map»; новый `PositionalTrackingParameters::compute_preference` (`PREFER_GPU`); `depth_precision = INT8` для neural depth (до 14% быстрее, меньше памяти); исправлено зависание GMSL-камер (к USB ZED 2i не относится).
- **Про миллиметры после релокализации и зависание grab() после релокализации ни в 5.5.0, ни в 5.3.x release notes ничего нет.** На форуме Stereolabs есть похожие жалобы (порча area-файла на длинных сессиях, долгая загрузка area-файла, сохранение дольше таймаута), но без исправления. Стоит завести issue в `stereolabs/zed-sdk` с минимальным воспроизведением (SVO + area-файл), а в коде продолжать защищаться от скачка масштаба (×1000) после `relocalized`.
- Прошивка ZED 2i 1523 — актуальная для ZED 2i. Обновлять её через ZED Explorer имеет смысл, только если SDK сам об этом попросит.
- В логах текущей сессии: `Slow grab: 4654 ms` (21:47:38) и `4103 ms` (21:56:34), рядом `uvcvideo ... Non-zero status (-71)` (EPROTO на USB) в 204/222/224 и 784/786 с аптайма, `Area export: FILE ERROR` в 21:56:15. -71 совпадает по времени с переоткрытием камеры. Если такие ошибки появятся без переоткрытия, проверить кабель или порт USB 3.
- `INT8 depth_precision` и `compute_preference` — дешёвые эксперименты для разгрузки GPU и памяти, обновлять SDK для этого не нужно.

---

## 4. Прочие обновления

### Хост, apt (по существующему кешу, `apt update` не запускался)
- Всего обновляемых пакетов **528**: 412 jammy-updates+security, 8 только security, 54 только updates, 6 jammy, **48 «stable»** (NVIDIA L4T 36.4.7 и Docker).
- Среди них libc6 (3.9 → 3.15), systemd 249.11-0ubuntu3.22, binutils, linux-firmware, openssl-зависимые и т.д.
- Docker: **docker-ce 29.8.2, containerd.io 2.3.6 (мажорный скачок 1.7 → 2.x), compose 5.5.1, buildx 0.37.1**.
- Рекомендация: security-обновления Ubuntu ставить можно, но **только при `apt-mark hold 'nvidia-l4t-*'`** и, на первый раз, тоже с hold на `docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin`. Переход на containerd 2.x и Docker 29 лучше делать отдельно и проверить после него `runtime: nvidia` и CDI. Команда: `apt-mark hold 'nvidia-l4t-*' docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin && apt upgrade`. Риск: низкий–средний (libc и systemd обновляются, нужна перезагрузка).
- **nvidia-container-toolkit 1.16.2**: уязвимые версии ≤1.17.7 (CVE-2025-23266 «NVIDIAScape», выход из контейнера; исправлено в 1.17.8). На роботе запускаются только свои образы, так что практический риск низкий. Обновится вместе с JP 6.2.3, если в r36.5-репо есть новее, иначе можно поставить из репо `nvidia.github.io/libnvidia-container`.

### Контейнеры
| Что | Сейчас | Рекомендация |
|---|---|---|
| ClickHouse | 26.1 (обычный релиз, уже без поддержки) | закрепить на **26.3 LTS** (минимальный шаг) или 26.8 LTS (2026-08-27, 57 несовместимых изменений от 26.3, читать changelog). Делать после бэкапа тома `forge-clickhouse` |
| NATS | 2.11.6 через `nats:latest` | закрепить тег. Текущая линия 2.14.x / **2.15** (2026-09-17). Минимум — `nats:2.11-alpine` (закрепить без смены версии), затем отдельно 2.12+ (менялось поведение JetStream, читать release notes) |
| bitnami/natscli | `latest`, больше не обновляется | `natsio/nats-box:<версия>` (уже есть на роботе) |
| mdawar/nats-dashboard | `latest`, 2 года | удалить, если не пользуетесь (освободит 11–44 МБ и порт 8000) |
| Node | 26.10.0 | ок. Node 26 становится LTS в октябре 2026, тег `node:26-alpine` годится |
| nginx | 1.29.8 mainline | ок |
| cloudflared | 2026.9.0, закреплён | ок |
| uv в Dockerfile | `ghcr.io/astral-sh/uv:latest` | закрепить версию (`uv:0.12.22`), чтобы сборки были воспроизводимыми |
| Python в venv | **3.10.0** (первый релиз ветки, 2021 г.) | минимум сменить на последний 3.10.x (`requires-python = "~=3.10.0"` и `uv python pin 3.10`): бесплатно получите 19 патч-релизов исправлений. Ветка 3.10 достигла EOL в октябре 2026, поэтому настоящее решение — Python 3.12 вместе с JP7. pyzed в образе собран под системный 3.10, так что внутри 3.10.x ABI совместим |

---

## 5. Рекомендации по порядку (ценность / риск)

1. **Заблокировать L4T от случайного апгрейда до 36.4.7.** Ценность высокая, риск нулевой.
   `apt-mark hold 'nvidia-l4t-*'`
2. **Убрать `uv run` из рантайма.** −240 МБ RAM, нет синхронизации venv при старте. Риск низкий.
   В `compose.yaml` заменить `command: uv run src/node/X.py` на `command: .venv/bin/python src/node/X.py` (или `uv run --no-sync` + `exec`), venv уже собран в образе. Проверить, что `PYTHONPATH` для pyzed/nvblox сохраняется: он задан через `ENV`, так что сохранится.
3. **Убрать snap и мусорные сервисы.** Нет автообновлений на живом роботе, −60–80 МБ anon и ~650 МБ cache, 2.3 ГБ диска, закрыт порт 631. Риск низкий: snap-ы не используются; `jtop` не трогать.
   ```
   snap remove --purge chromium cups gnome-42-2204 gnome-46-2404 gtk-common-themes mesa-2404 core22 core24 bare && apt purge snapd
   systemctl disable --now ModemManager networkd-dispatcher nvargus-daemon kerneloops lpd rpcbind.socket rpcbind avahi-daemon.socket avahi-daemon apport-autoreport.path apport-autoreport.timer motd-news.timer update-notifier-download.timer update-notifier-motd.timer fwupd-refresh.timer ua-timer.timer openvpn
   # bluetooth: только если не нужен BT-геймпад
   systemctl disable --now bluetooth
   ```
   До удаления snapd можно для начала просто остановить автообновления: `snap refresh --hold`.
4. **Разобраться с OC3-троттлингом.** Высокая ценность для производительности под нагрузкой, риск нулевой (только диагностика).
   - Добавить в телеметрию `oc3_event_cnt` (`/sys/class/hwmon/hwmon3/oc3_event_cnt`) и признак «клоки ниже `jetson_clocks`», чтобы следующий эпизод был виден в Forge.
   - После эпизода: `jetson_clocks --show`, `nvpmodel -q`, `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq`. Временное решение — повторно выполнить `jetson_clocks`. Риск низкий, но это изменение состояния, поэтому только с вашего согласия.
   - Проверить питание модуля: VDD_IN 4.97–4.99 В при 2–3.5 А. Если плата питается от своего DC-DC с 4S-батареи (а не от штатного 19 В блока), стоит проверить, что преобразователь и провод на вход barrel jack держат 25 Вт без просадки. Отключать `oc3_throt_en` не рекомендую: это защита.
5. **Persistent journal.** Позволит разбирать инциденты после перезагрузки. Риск низкий.
   ```
   mkdir -p /etc/systemd/journald.conf.d && printf '[Journal]\nStorage=persistent\nSystemMaxUse=500M\n' > /etc/systemd/journald.conf.d/rabbit.conf
   mkdir -p /var/log/journal && systemd-tmpfiles --create --prefix /var/log/journal && systemctl restart systemd-journald
   ```
   Плюс поставить батарейку RTC на несущую плату. Иначе первые секунды после загрузки пишутся в ClickHouse со старым временем.
6. **Docker cleanup и автоматическая чистка после деплоя.** Освобождает десятки ГБ. Риск низкий: удаляются только неиспользуемые образы; запущенные контейнеры и именованные тома не трогаются.
   ```
   docker container prune -f && docker image prune -a -f --filter "until=48h" && docker builder prune -f --keep-storage 10GB
   ```
   В `scripts/deploy.sh` после сборки добавить `docker image prune -f`. По желанию удалить `/root/nvblox`, `/root/nvblox_deps` (8 ГБ), если они не нужны.
   Dev-эксперименты (nvblox-build, zedlab и т.п.) запускать с `--memory 2g --cpus 2`: именно они давали swap до 3 ГБ и CPU 200%+ рядом со штатным стеком.
7. **Исправить failed logrotate.** Косметика, но сейчас из-за ошибки пропускается ротация. Риск низкий.
   `apt purge nvidia-jetson-services`, если сервисы Jetson Platform Services не используются (проверить `dpkg -L nvidia-jetson-services`), либо `rm /etc/logrotate.d/jetson-logging`.
8. **Закрепить версии образов** (nats, nats-box вместо bitnami, uv) и перейти на ClickHouse 26.3 LTS. Средняя ценность, низкий риск при бэкапе тома.
9. **Python 3.10.0 → 3.10.x последний.** Низкий риск, сразу исправляет давно известные баги CPython; полноценный уход с 3.10 — вместе с JP7.
10. **apt security-обновления хоста** при hold на nvidia-l4t и docker. Средняя ценность, низкий–средний риск, нужна перезагрузка.
11. **JP 6.2.3 / L4T 36.5.2** в окно для работ, после пункта 3 (snap), с бэкапом и **DT-overlay для UART RoboClaw** (§6.3). Средняя ценность, средний риск.
12. **JetPack 7.2.x**: позже, отдельным проектом.
13. **Безопасность LAN**: закрыть ufw всё, кроме 22/443/4222/9222 из домашней сети, и сменить пароли ClickHouse, совпадающие с логинами. Низкая ценность, пока робот только дома.

---

## Источники
- [JetPack Archive](https://developer.nvidia.com/embedded/jetpack-archive)
- [JetPack 6.2.3 / Jetson Linux 36.5.2 is now live (Orin Nano)](https://forums.developer.nvidia.com/t/jetpack-6-2-3-jetson-linux-36-5-2-is-now-live/379873)
- [Jetson Linux 36.5.2](https://developer.nvidia.com/embedded/jetson-linux-r3652)
- [JetPack 6.2.2 / Jetson Linux 36.5 is now live (Orin Nano)](https://forums.developer.nvidia.com/t/jetpack-6-2-2-jetson-linux-36-5-is-now-live/359624)
- [JetsonHacks: JetPack 6.2.2 for Jetson Orin](https://jetsonhacks.com/2026/02/06/jetpack-6-2-2-for-jetson-orin/)
- [Orin Nano 8GB: L4T upgrade to 36.4.7 (CUDA0 buffer)](https://forums.developer.nvidia.com/t/jetson-orin-nano-8gb-developer-kit-l4t-upgrade-to-36-4-7/356006/5)
- [JetPack 6.2.2 (r36.5) causing outages … Orin Nano Super](https://forums.developer.nvidia.com/t/jetpack-6-2-2-and-r36-5-causing-outages-with-multiple-applications-on-jetson-orin-nano-super/362451)
- [JetsonHacks: JetPack 7.2.1 Released](https://jetsonhacks.com/2026/08/12/jetpack-7-2-1-released/)
- [JetPack 7.2 on Orin Nano: feedback thread](https://forums.developer.nvidia.com/t/jetpack-7-2-jetson-linux-r39-2-on-jetson-orin-nano-developer-kit-getting-started-and-feedback-thread/372151?page=3)
- [JetPack 7.2.1 vs 6.2.2 on Orin: What Breaks](https://iotdigitaltwinplm.com/jetpack-7-2-1-vs-6-2-2-jetson-orin-migration-2026/)
- [Isaac ROS release notes](https://nvidia-isaac-ros.github.io/releases/index.html)
- [ZED SDK download / support matrix](https://www.stereolabs.com/developers/release)
- [ZED SDK 5.5 release notes](https://docs.stereolabs.com/docs/development/zed-sdk/release-notes/5-x/5-5)
- [stereolabs/zed-sdk releases](https://github.com/stereolabs/zed-sdk/releases)
- [Stereolabs forum: area file corruption on long runtimes](https://community.stereolabs.com/t/zed-area-file-corruption-on-long-runtimes/9764)
- [NATS Server releases](https://github.com/nats-io/nats-server/releases)
- [ClickHouse 26.8 LTS breaking changes since 26.3](https://dev.to/mohhddhassan/clickhouse-268-lts-57-breaking-changes-since-263-3ba9)

---

## 6. Что даст обновление

Вопрос: что конкретно получит этот робот от перехода на JetPack 6.2.3 (L4T 36.5.2) или JetPack 7.2.1 (L4T 39.2.1), и не косметика ли это. Ответ опирается на release notes Jetson Linux 36.5, 36.5.2 и 39.2 (прочитаны целиком), ZED SDK 5.5, nvblox, форумы NVIDIA и Stereolabs и на наши данные из Forge.

### 6.1. Где у нас реальное узкое место
По `forge.jetson` (1–2 октября): **CPU** avg 40–57%, p95 64–79%, ядра упираются в 100%; **RAM** до 7.7 ГБ из 7.6, swap до 3 ГБ; **GPU** avg 20–25%, p95 50–83%. GPU пока не узкое место. Ускорение CUDA/TensorRT почти ничего не даст. Значимы только выигрыш по RAM и CPU и устранение сбоев.

### 6.2. По каждому направлению

| Что ждём | JP 6.2.3 / L4T 36.5.2 | JP 7.2.1 / L4T 39.2.1 | Можно ли получить без смены JP |
|---|---|---|---|
| **Скорость инференса (YOLOE, NEURAL_LIGHT)** | без изменений: тот же CUDA 12.6, TRT 10.3, cuDNN 9.3 («packages the same libraries») | CUDA 13.2, TRT 10.16, cuDNN 9.20. **Публичных сравнений YOLO или ZED depth на Orin Nano JP7 vs JP6 нет.** Цифра «+28–42% токенов, −40% памяти» из обзоров Seeed — это llama.cpp на **AGX Orin 32GB**, где JP7.2 впервые включил Super-режим (GPU 930 → 1360 МГц). На Orin Nano Super уже в JP6.2 стоит GPU 1020 МГц, CPU 1728, EMC 3199 — этого прироста у нас не будет. Ожидание: 0–10%, требует собственного замера | ZED SDK 5.4/5.5 уже дали «до 20% быстрее depth inference» — это у нас уже есть. `depth_precision = INT8` (до 14% быстрее на Orin NX, меньше памяти) работает на JP6 |
| **Память (8 ГБ)** | без изменений | Заявленные «~450 МБ после загрузки» на Orin Nano Super — это вычищенная система без Docker. У нас хостовая часть после чистки из §5 и так ~0.6–0.8 ГБ. Реалистичный выигрыш **≤0.2–0.3 ГБ (оценка, не измерено)**. Новый известный баг 5699079: «If excessively large CUDA memory allocation is attempted, the device might reboot» — при нашем дефиците RAM это **минус** | −240 МБ от `uv run`, −60–80 МБ от сервисов, INT8 depth, лимиты на dev-контейнеры: всё доступно на JP6 и даёт больше |
| **Стабильность** | **Фикс 5412830**: «UEFI assertion error during boot, causing the device to stop at the bootloader… occurred randomly and required a full firmware reflash to recover». Для робота с 93 жёсткими выключениями из 104 это самый весомый аргумент. Фикс 5602402 (NvMap, CUDA0 buffer) нужен только тем, кто уже на 36.4.7 | новый стек с новыми ранними багами (см. риски) | — |
| **USB -71 / `grab()` stalls** | в fixed issues по USB/UVC/xHCI ничего нет | в release notes 39.2 по USB-хосту на Orin Nano ничего нет. Ядро 6.8 новее, но -71 (EPROTO) — обычно проблема канала (кабель, хаб, помехи), обновление ОС его не лечит. Зависание после релокализации — проблема ZED SDK, от JP не зависит | проверить кабель или порт; issue в Stereolabs |
| **Wi-Fi rtl8822ce** | тот же вендорный модуль из `nvidia-l4t-kernel-oot-modules`, `rabbit-wifi.conf` переживёт apt | по-прежнему вендорный `rtl8822ce.ko` (rtw88 намеренно выключен), сборка под 6.8. Улучшений в notes нет; из известных — только 6 ГГц/MBSSID и размер буфера сканирования. `.conf` после перепрошивки нужно вернуть | — |
| **Питание / Super / OC3** | ничего нового | для Orin Nano ничего нового (новинка — Super для AGX 32GB). Известная проблема 6279443: при установке через ISO Orin Nano **не переходит в Super** — надо прошивать с хоста (`jetson-orin-nano-devkit-super`) | — |
| **nvblox** | nvblox **v0.0.9 / v0.0.10** (апрель 2026) поддерживают CUDA 12.6 / JetPack 6. У нас коммит 23d35fc от 2025-08-08, между v0.0.8 и v0.0.9 | то же плюс CUDA 13 | **Да.** Обновление nvblox не требует JP7 |
| **Isaac ROS** | — | Isaac ROS 4.6 поддерживает Orin только на JP7.2 | мы не используем ROS, значит, для нас не аргумент |
| **ZED SDK** | 5.5.0 есть под L4T 36.4 и 36.5 | 5.5.0 под L4T 39.2. Различия — только Holoscan/CoE и GMSL; для USB ZED 2i функции одинаковые | — |
| **Python 3.12** | пакеты хоста на 3.10, но venv в контейнере может быть любым | системный Python 3.12 | **Да.** Wheel `pyzed-5.5-cp312-linux_aarch64` существует (проверено по HTTP 200). numba 0.68 поддерживает 3.12. Детектор работает внутри ZED SDK (`CUSTOM_YOLOLIKE_BOX_OBJECTS` + ONNX), Python-биндинги TensorRT не нужны. Надо пересобрать только `rabbit_nvblox` (nanobind) под 3.12. CPython 3.11+ в среднем ~1.25× быстрее 3.10 на чистом Python (pyperformance). Для nav/ina/roboclaw/telemetry это заметно, для numba-кода и C++ в ZED SDK — нет |
| **Поддержка и безопасность** | ветка JP6 в sustaining; EOL по roadmap NVIDIA — **Q3 2028** (оценка 2023 г.). 36.5.x включает security fixes из бюллетеней NVIDIA | Ubuntu 24.04 до 2029 (ESM — дальше), JP7 — основная ветка | Ubuntu 22.04: стандартная поддержка до **апреля 2027**, с бесплатным для личного использования Ubuntu Pro (ESM) — до 2032 (касается пакетов Ubuntu, не L4T). **Python 3.10 — EOL 31.10.2026**: это решается сменой Python в контейнере, не JP |

### 6.3. Новые риски, которых не было в аудите выше
- **RoboClaw сидит на `/dev/ttyTHS1` (`serial@3100000`).** Сейчас, на 36.4.4, порт работает в PIO-режиме (`RX in PIO mode`, в DT нет `dmas`). **Начиная с 36.5 UEFI добавляет в этот узел `dmas`/`dma-names`, и `serial-tegra` в DMA-режиме обнуляет первые 96 байт каждого приёма** (форум NVIDIA, jetsonhacks/jetson-orin-uart). В fixed issues 36.5.2 исправления нет. Значит, **обновление на 6.2.3 без DT-overlay, убирающего `dmas`, сломает управление моторами.** Нужен overlay (jetsonhacks) и проверка `dmesg | grep 3100000` → `PIO mode` до выезда.
- **JP7 / R39.2 на Orin Nano Super: TX пин `ttyTHS1` не работает** (пины 40-pin не замаксированы на UART; NVIDIA советует перепрошить с хоста конфигом super и/или править pinmux). Подтверждения исправления в 39.2.1 нет. Для нас это блокер, пока не проверено на стенде.
- JP7: при перепрошивке через ISO Super-режим не включается (только прошивка с хоста); Jetson-IO не работает на Super при ISO-прошивке; слишком большая CUDA-аллокация может перезагрузить плату; откат на JP6 — только полной перепрошивкой, а совместимость JP6 с QSPI от r39 не гарантирована.
- JP 6.2.2/6.2.3: после r36.5 ломаются snap-приложения (нам не важно, если удалить snap); удалён режим 7 W (не используем).

### 6.4. Вердикт по путям

| Путь | Что получим | Чем рискуем | Работа | Стоит ли и когда |
|---|---|---|---|---|
| **A. Ничего, но с `apt-mark hold 'nvidia-l4t-*'`** | защита от 36.4.7 | остаётся случайный bootloader-hang (5412830) и неисправленные уязвимости | 5 мин | сразу, при любом выборе |
| **B. Python 3.12 + nvblox v0.0.10 на текущем JP6** (только образ `rabbit`) | уход с EOL Python 3.10; ~10–25% меньше CPU у Python-узлов (оценка по pyperformance, на наших узлах не замерено); свежий nvblox (оптимизация трекера блоков, `unobserved_esdf_policy`, фиксы); воспроизводимые сборки | перенос `native/rabbit_nvblox` на новый API nvblox; регрессии в numba-коде маловероятны | **1–3 дня** (Python — ~0.5–1, nvblox — 1–2), откат = старый образ | **да, в ближайшие недели.** Это главная практическая польза «большого обновления», и для неё не нужна перепрошивка |
| **C. JP 6.2.3 / L4T 36.5.2 через apt** | фикс случайной остановки в UEFI (актуально при наших жёстких выключениях); security fixes; поддерживаемая точка ветки JP6 до 2028; вероятно, более новый nvidia-container-toolkit. Производительность не меняется | **UART DMA (RoboClaw)** — нужен overlay; обновление QSPI через capsule; rootfs без A/B | **0.5–1 день** с подготовкой overlay и тестом моторов на подставке | **да, но после B и в окно для работ**, с готовым overlay и бэкапом. Не срочно |
| **D. JP 7.2.1 (перепрошивка)** | Ubuntu 24.04 (поддержка до 2029), ядро 6.8, CUDA 13, TRT 10.16, Isaac ROS 4.6 (нам не нужен). Измеримого выигрыша по скорости или памяти для нашей нагрузки не ожидается (≤0–10%, ≤0.3 ГБ, не подтверждено) | перепрошивка; `ttyTHS1` TX на R39.2 Orin Nano Super; Super-режим; новый ранний стек; пересборка всего (ZED-образ под JP7, nvblox под CUDA 13, venv, TRT-кэш детектора); перенастройка Wi-Fi, `rabbit-performance`, IRQ, Docker/CDI; откат только перепрошивкой | **3–5 дней** + неделя наблюдения | **не сейчас.** Пересмотреть в **H1 2027**: к концу стандартной поддержки Ubuntu 22.04 (апрель 2027), когда выйдет 7.2.2+ и подтвердится исправление UART на Orin Nano Super. Раньше — только если понадобится что-то, что есть лишь на JP7 |

**Итог.** Большое обновление до JP7 для этого робота — в основном задел на будущее и гигиена поддержки, а не производительность. Реальная польза сосредоточена в двух дешёвых шагах на текущем JP6: Python 3.12 + свежий nvblox в образе (B) и точечный апгрейд до 36.5.2 ради фикса UEFI-зависания и security (C) — обязательно с DT-overlay для UART RoboClaw. Наши фактические проблемы (дефицит RAM, OC3-троттлинг, USB -71, `grab()` после релокализации) ни один из путей сам не решает: их закрывают пункты 2–6 из §5 и работа с ZED SDK.

### Источники к разделу
- [Jetson Linux 36.5 Release Notes (PDF)](https://docs.nvidia.com/jetson/archives/r36.5/ReleaseNotes/Jetson_Linux_Release_Notes_r36.5.pdf), [36.5.2](https://docs.nvidia.com/jetson/archives/r36.5.2/ReleaseNotes/Jetson_Linux_Release_Notes_r36.5.2.pdf), [39.2](https://docs.nvidia.com/jetson/archives/r39.2/ReleaseNotes/Jetson_Linux_Release_Notes_r39.2.pdf)
- [JetPack 7.2 downloads and notes](https://developer.nvidia.com/embedded/jetpack/downloads/archive-7.2)
- [Migrating from JetPack 6.x to 7.2.1](https://wiki.juxitech.com/tutorials/jetson-orin-nano/jetpack-6-to-7)
- [Seeed: JetPack 7.2 deep dive (AGX Orin, llama.cpp)](https://wiki.seeedstudio.com/jetpack72_deep_dive/)
- [Free up memory for Orin Nano Super JetPack 7.2](https://forums.developer.nvidia.com/t/free-up-memory-for-jetson-orin-nano-super-jetpack-7-2/372526)
- [RidgeRun: AGX Orin RAM, JetPack 7.2 vs Yocto](https://www.ridgerun.com/post/jetson-agx-orin-ram-consumption-jetpack-7-2-vs-a-minimal-yocto-image)
- [UART/Serial not working after JetPack 6.2.2 (Solved)](https://forums.developer.nvidia.com/t/solved-uart-serial-port-not-working-after-upgradint-to-jetpack-6-2-2-orin-nano-nx/363837), [jetsonhacks/jetson-orin-uart](https://github.com/jetsonhacks/jetson-orin-uart)
- [ttyTHS1 TX does not drive on JetPack 7 / R39.2, Orin Nano Super](https://forums.developer.nvidia.com/t/ttyths1-uart1-40-pin-header-pins-8-10-tx-pad-does-not-drive-on-jetpack-7-l4t-r39-2-orin-nano-super-devkit/373290)
- [nvblox release notes](https://github.com/nvidia-isaac/nvblox/blob/public/release-notes.md)
- [Isaac ROS release notes](https://nvidia-isaac-ros.github.io/releases/index.html)
- [ZED SDK 5.5 release notes](https://docs.stereolabs.com/docs/development/zed-sdk/release-notes/5-x/5-5), [ZED SDK downloads](https://www.stereolabs.com/developers/release)
- [Ultralytics: YOLO on Jetson benchmarks](https://docs.ultralytics.com/guides/nvidia-jetson)
- [JetPack 6 versions and support (RidgeRun)](https://developer.ridgerun.com/wiki/index.php/JetPack_6_Migration_and_Developer_Guide/Introduction/Versions_and_Support)
- [Ubuntu 22.04 end of life dates](https://thelastpatch.io/ubuntu-22-04-end-of-life/), [Python 3.10 EOL](https://endoflife.ai/python)
