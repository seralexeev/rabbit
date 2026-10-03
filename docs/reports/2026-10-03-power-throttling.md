# Троттлинг Jetson Orin Nano Super на Rabbit: что происходит, почему и что делать

Дата: 2026-10-02/03. Робот: Orin Nano 8GB Super dev kit, L4T R36.4.4, `MAXN_SUPER` (nvpmodel id 2), `rabbit-performance` → `jetson_clocks` при загрузке.
Всё исследование только на чтение: настройки не менялись, сервисы не перезапускались, в NATS ничего не публиковалось. Единственное вмешательство: три короткие синтетические нагрузки по 20–30 с (`nice -n 19 stress -c 6`, `nice -n 19 stress --vm 6 --vm-bytes 64M`) и несколько лёгких запросов к ClickHouse.

## TL;DR

Это две **разные** проблемы, которые раньше считались одной.

1. **OC3: аппаратный троттлинг по мгновенному превышению мощности VDD_IN.** Срабатывает постоянно, 1–2 события/с в покое и под нагрузкой, иногда 10–30/с. Каждое событие режет частоты CPU и GPU ровно вдвое примерно на ~1 мс (длительность выведена из счётчиков BPMP, см. §1.4). Сейчас это ~0.1–1 % времени, то есть влияние на производительность пренебрежимо. Батарея, DC-DC и моторы тут ни при чём: under-voltage (OC1) = 0, average OC (OC2) = 0, VDD_IN не проседает ниже 4.94 В, корреляции с током моторов нет. NVIDIA считает OC в MAXN «ожидаемым» и отключать его не разрешает.
2. **«Троттлинг 85 минут» 2 октября 00:06–01:30 UTC был не OC, а программный сброс `jetson_clocks`.** В 00:06:06 UTC система переключилась из runlevel 5 в runlevel 3: это `systemctl isolate multi-user.target` при переводе Jetson в headless, коммит `docs: note that the Jetson runs headless` в 00:06:23. `nvpmodel.service` устроен как `Type=oneshot` без `RemainAfterExit`, поэтому после загрузки висит в `inactive (dead)`. `isolate` запустил его заново, и nvpmodel применил дефолты MAXN_SUPER (CPU min 729.6 МГц, GPU min 306 МГц). Наш `rabbit-performance` (`RemainAfterExit=yes`) остался «active» и повторно не выполнился. Клоки ушли в обычный DVFS и оставались там до перезагрузки. Совпадение до секунды: wtmp 00:06:06, телеметрия 00:06:06.

Что делать, по порядку ценности:
- **(а)** drop-in для `nvpmodel.service`, чтобы он больше не перезапускался молча и не сбрасывал клоки;
- **(б)** телеметрия и алерт «пол частот потерян» и «темп OC-событий»;
- **(в)** проверить DC-DC, это гигиена, а не причина.

Custom nvpmodel ради OC сейчас не нужен.

---

## 1. Текущее состояние (2026-10-02 ~22:25–22:45 UTC, uptime 40–60 мин)

### 1.1 Политика частот: `jetson_clocks` после последней загрузки применён

```
cpu0..5  scaling_min=scaling_max=cpuinfo_cur=1728000, governor schedutil
GPU 17000000.gpu  min=max=cur=1020 МГц (nvhost_podgov)
EMC  MinFreq=204 MaxFreq=3199 Current=3199 FreqOverride=1   (bpmp clk/emc/rate = 3199000000)
NV Power Mode: MAXN_SUPER;  default target: multi-user.target
rabbit-performance.service: active (exited), Result=success
nvpmodel.service: Type=oneshot, RemainAfterExit=no, WantedBy=multi-user.target → сейчас inactive (dead)   ← мина, см. §2
```

### 1.2 Счётчики OC и INA3221 модуля

| Источник | Значение |
|---|---|
| `hwmon3` (soctherm_oc) | `oc1_event_cnt=0`, `oc2_event_cnt=0`, `oc3_event_cnt=27 390` за 3 605 с uptime (в среднем 7.6/с); `oc*_throt_en=1` |
| BPMP `soctherm/oc0,oc1` | `event_cnt=0` |
| BPMP `soctherm/oc2` | `event_cnt` = hwmon oc3 (то же событие), `cpu_depth=gpu_depth=1`, `thresh_cnt=1`, `throt_period=1`, `polarity=1` |
| BPMP `cpu_throt_status / gpu_throt_status` | почти всегда 0, один раз 1 за ~700 опросов |
| Термозащита BPMP `hwt` | lo/hi = 101/103 °C, depth 4; Tj сейчас 50–52 °C (максимум за всю историю 60.6 °C) |
| INA3221 ch1 VDD_IN | 5.016–5.024 В, 1.5–2.4 А (7.6–11.5 Вт); `curr1_crit = curr1_max = 4984 мА` (≈25 Вт) |
| INA3221 ch2 VDD_CPU_GPU_CV / ch3 VDD_SOC | 0.4–0.5 А / 0.47–0.5 А |
| INA3221 `samples=512` | `curr1_input` усреднён; critical alert сравнивает **каждую** отдельную конверсию (TI datasheet), поэтому короткий пик через усреднение не виден |

По NVIDIA (Jetson Linux r36.4 PPG): OC1 = under-voltage VDD_IN (~4.5 В), OC2 = average power, OC3 = instantaneous power. Для Orin Nano 8GB в 25 W / Super лимиты OC2 = 25 Вт и OC3 = 25 Вт, глубина троттлинга 50 %. У нас срабатывает **только OC3**.

### 1.3 Темп OC3 в зависимости от нагрузки (опрос 0.05–0.2 с)

| Окно | Нагрузка | VDD_IN ср./макс., мА | OC3 событий/с | Отсчётов CPU < 1700 МГц |
|---|---|---|---|---|
| 60 с | покой, ZED перезапускался, GPU 0 % | 1 550 / 1 816 | 1.07 | 0 / 300 |
| 20 с | покой | 1 615 / 1 768 | 1.1 | 0 / 191 |
| 30 с | `stress -c 6` (все 6 ядер 100 %) | 2 085 / 2 192 | 1.7 | 0 / 285 |
| 30 с | после | 1 655 / 1 824 | 1.1 | 0 / 286 |
| 22 с | покой | 1 840 / 2 008 | 1.0 | 1 / 401 |
| 22 с | `stress --vm 6` (память / EMC) | 2 250 / 2 376 | 1.45 | 2 / 385 |
| 22 с | после | 1 847 / 2 040 | 1.5 | 1 / 400 |
| 60 с | ZED работает, GPU 0–52 % всплесками | ≈1 900 | 2.3 | — |
| 180 с | то же, окна по 2 с | 9.2 Вт ср. | 1.37 | corr(OC, GPU %) = −0.10; corr(OC, P) = +0.09 |

Выводы:
- Средняя мощность 8–12 Вт, то есть 35–45 % от порога 25 Вт. Темп OC3 от нагрузки почти не зависит: CPU-стресс прибавил +0.6/с, корреляция с GPU и мощностью ≈0. Это не «реальная перегрузка» в обычном смысле. Это короткие пики, которые INA3221 ловит на единичной конверсии, или шум на линии alert. Ровно такое же поведение описано на форуме NVIDIA у Orin Nano Super / JP 6.2: OC3 при 10–13 Вт и `curr1_input` < 4 А. NVIDIA отвечает: «Instant high power may occur in very small time slot so that it cannot be captured by INA3221», «Hitting OC in this mode is totally expected».
- Темп не постоянный. В среднем за эту загрузку 7.6/с (первые 42 минуты 9.5/с), прошлый аудит видел 28/с, а в моих окнах было 1–2/с. Значит, бывают периоды, когда событий в 10–20 раз больше. Скорее всего, это фазы работы ZED (neural depth / mapping / старт камеры), но проверить нельзя: OC-счётчики не пишутся в Forge (§4).
- BPMP публикует счётчики пачками раз в ~2.0 с, поэтому точную синхронизацию с отдельными событиями (кадр ZED, ток мотора) из userspace не получить.

### 1.4 Насколько сильно и надолго режет

- `dmesg` за 60 мин содержит 73 строки вида `cpufreq: cpu0,cur:862000,set:1728000,...set ndiv:135`: измеренная частота ровно 1728/2. Это подтверждает глубину 50 % (BPMP `cpu_depth=1` = «Light 50 %» из таблицы PPG). Эти строки пишет драйвер `tegra194-cpufreq`, когда jtop читает `cpuinfo_cur_freq` и попадает в момент троттлинга. Для железа это безвредный шум.
- BPMP `oc2/event_time` растёт **ровно на 33 569 единиц за каждое событие** (проверено на десятках пачек). Это накопленное время троттлинга с фиксированной длительностью на событие. Если единица равна тику TSC 31.25 МГц (вывод, NVIDIA это не документирует), то событие длится ≈1.07 мс. Независимая оценка: при ~1.4 события/с в 0.19 % отсчётов `cpuinfo_cur_freq` частота была пониженной (5 из 2 672), то есть ≈1.4 мс на событие. Это сходится.
- Итог: накоплено 1 002 156 212 тиков ≈ 32 с троттлинга за 3 585 с ≈ **0.9 % времени при 50 % частоты**, то есть ~0.45 % потерянной производительности. В пике (28/с) это ~3 % времени, ~1.5 % производительности. GPU devfreq `cur_freq` эти просадки **не показывает** (ни одного отсчёта < 1020), CPU `scaling_cur_freq` тоже. Видно их только в `cpuinfo_cur_freq` и BPMP-счётчиках.

### 1.5 Питание: просадки нет

| Сигнал | Наблюдение |
|---|---|
| OC1 (under-voltage VDD_IN ~4.5 В) | 0 событий |
| VDD_IN (Forge, 1 Гц, 1–2 октября) | минимум 4 936 мВ (при пике 17.1 Вт), обычно 4 960–5 000 мВ |
| Батарея 4S (rabbit-ina, 50 Гц) | 13.8–16.7 В. Значения 7.37 В в 07:18–07:33 являются ошибками I2C (`errors` растёт 81→334), а не просадкой |
| Ток батареи | среднее 1.2–1.9 А, максимум 6.7 А |
| Моторы (RoboClaw, сумма \|L\|+\|R\|) | p50 0.07 А, p99 0.42 А, p99.9 0.98 А; выбросы 37–70 А являются глюками чтения |
| corr(ток моторов, VDD_IN мВ) по секундам | −0.03 |
| RoboClaw `supply_voltage` | всё время 11.9–12.0 В, пока батарея 13.8–16.7 В. RoboClaw (а вероятно, и barrel jack) сидит на стабилизированной шине ~12 В от DC-DC |
| Сейчас | батарея 14.3–14.6 В, `battery_charge_pct` ≈19 % (заряжать скоро) |

Barrel jack dev kit по спецификации NVIDIA принимает 9–20 В и до 4.2 А. Модуль Orin Nano получает фиксированные 5 В VDD_IN от buck-преобразователя на carrier. Поэтому просадка батареи до OC3 вообще не доходит, а если бы dc-dc не справлялся, мы бы увидели OC1 и падение VDD_IN ниже ~4.9 В. Этого нет.

---

## 2. История: все длительные эпизоды пониженных частот

ClickHouse `forge.jetson` (1 Гц, с 2026-10-01 22:44 UTC). Эпизод определялся как `arrayMin(cpu_freq_mhz) < 1700` или `gpu_freq_mhz < 1000`.

| Период (UTC) | Отсчётов CPU low / GPU low | Что это |
|---|---|---|
| 2026-10-01 22:44 – 10-02 00:06:05 | 0 / 0 | норма (`jetson_clocks`) |
| **2026-10-02 00:06:06 – 01:30:03** (последний отсчёт перед перезагрузкой) | 4 279 / 5 029 из ~5 030 | **сброс `jetson_clocks` повторным запуском nvpmodel** |
| 05:30 – 13:16 | 1 / 0 (08:21:08, один отсчёт 981 МГц на одном ядре) | норма; одиночный OC3, пойманный jtop (см. ниже) |
| 21:46 – 22:31 (текущая загрузка) | 0 / 0 | норма |

Других длительных эпизодов нет. Если судить только по Forge, OC3 невидим: телеметрия пишет `scaling_cur_freq` (запрошенную частоту), а не фактическую. Одиночный 981 МГц появился потому, что чтение `cpuinfo_cur_freq` через `cpufreq_verify_current_freq` на мгновение переписывает `policy->cur` на измеренное значение.

### 2.1 Хронология 00:06 по секундам

```
ts (UTC)   cpu_freq_mhz (ядра 0..5)           gpu  gpu%  VDD_IN мВт
00:06:03   1728 ×6                            1020  46   12161
00:06:04   1728 ×6                            1020   7   12776   ← GPU-нагрузка исчезла (останавливается X/GDM)
00:06:05   1728 ×6                            1020   0   12419
00:06:06   1728 1728 1728 1728 1421 1421      1020  13   17098   ← wtmp: "runlevel (to lvl 3) 2026-10-02T00:06:06"
00:06:07   1267 1267 1267 1114 1728 1728       408  88   11764   ← nvpmodel применил MAXN_SUPER дефолты
00:06:08    960  960  883  883 1728 1728       408   4   11605
00:06:12    730  730  883  883 1728 1728       408   4   10947
00:06:13   1037  960 1037 1037 1728 1728       306   5   10748
```

`last -x` (wtmp):
```
runlevel (to lvl 5)  2026-10-01T14:04:39 - 2026-10-02T00:06:06
runlevel (to lvl 3)  2026-10-02T00:06:06 - 2026-10-02T01:09:51   ← isolate multi-user.target
rabbit :0  2026-10-01T14:04:37 - crash                            ← X-сессия убита
```
(Время 14:04 / 01:09 / 01:46 / 13:17 у записей reboot неверное: RTC не держит время, см. jetson-audit.md. Запись в 00:06 сделана при синхронизированных часах и совпадает с телеметрией.)

### 2.2 Почему это не OC и не термо

- Все значения частот во время эпизода **точно совпадают с таблицей OPP** (730, 806, 883, 960, 1037 … 1651, 1728 МГц; GPU 306/408/510/714/816). Так ведёт себя governor (schedutil / podgov), а не аппаратный делитель. OC даёт «кривые» значения вроде 862/1391.
- Пол частот равен **дефолтам nvpmodel** для MAXN_SUPER из `/etc/nvpmodel/nvpmodel_p3767_0003_super.conf`: `CPU_A78_x MIN_FREQ 729600`, `GPU MIN_FREQ 0` (→306 МГц). Тот же набор лежит в `/usr/local/jtop/l4t_dfs.conf`.
- Распределение за эпизод: CPU 730 МГц в 3 475 отсчётах, 1728 в 15 013 (у занятых ядер). GPU 408 МГц в 4 093, 306 в 675, 1020 ни разу.
- Tj 55–58 °C, порог hwt 101 °C. Батарея 15.6–16.7 В. Мощность во время эпизода ниже, чем до него: 11.0 Вт против 12.2 Вт. Нагрузка GPU выросла с 25 % до 54 %, потому что частота упала, а не наоборот.
- Пик 17.1 Вт в 00:06:06 стал **следствием** переключения (остановка X, повторная инициализация GPU и TPC power gating в nvpmodel), а не причиной.
- Эпизод закончился только с перезагрузкой. Последний отсчёт этой загрузки в 01:30:03 всё ещё «low». Следующая загрузка прошла с `rabbit-performance`, и клоки снова 1728/1020.

Последствия эпизода: ZED capture упал с 29.6–30.0 до 26.5–28.5 fps, EMC, вероятно, тоже вернулся в DVFS (не логируется).

### 2.3 Механизм

```
nvpmodel.service:  Type=oneshot, RemainAfterExit=no, WantedBy=multi-user.target, ExecStart=/etc/systemd/nvpmodel.sh
rabbit-performance.service:  Type=oneshot, RemainAfterExit=yes, After=nvpmodel.service, WantedBy=multi-user.target
```
`systemctl isolate multi-user.target` (то же самое делают `systemctl default` и `systemctl start multi-user.target`) запускает все Wants этого таргета, которые сейчас не active. nvpmodel после загрузки всегда `inactive (dead)`, поэтому он выполняется снова и откатывает `jetson_clocks`. `rabbit-performance` уже `active (exited)` и не перезапускается. Тот же эффект дадут `nvpmodel -m <любой>`, `systemctl restart nvpmodel` и переключение режима через jtop.

---

## 3. Корневая причина

| Гипотеза | Вердикт | Доказательства |
|---|---|---|
| Просадка батареи / DC-DC / проводов | **нет** | OC1 = 0; VDD_IN ≥ 4.936 В; corr(моторы, VDD_IN) ≈ 0; барrel jack 9–20 В, модуль питается от стабилизированных 5 В carrier |
| Тепловой троттлинг | **нет** | Tj ≤ 60.6 °C за всю историю, порог hwt 101/103 °C |
| Средняя перегрузка VDD_IN (OC2) | **нет** | OC2 = 0, средняя мощность 8–17 Вт < 25 Вт |
| Мгновенные пики VDD_IN > 25 Вт (OC3) | **да, постоянно, но влияние мало** | 1–30 событий/с, по ~1 мс на 50 %. Не зависит от средней нагрузки. Известное поведение Orin Nano Super / JP 6.2 в MAXN_SUPER |
| Программная политика частот | **да, это и был «85-минутный троттлинг»** | повторный запуск nvpmodel при `isolate multi-user.target` в 00:06:06 |

Для OC3 остаётся открытым вопрос, что именно даёт пики на 2 А среднего тока: реальные μs-пики (GPU/EMC/CPU di/dt при ~3.2 ГГц EMC и 1.02 ГГц GPU) или шум на critical alert. Публичных данных NVIDIA об этом нет. В форумном треде 279417 подъём `curr1_crit` до 7–10 А не изменил частоту OC3, что указывает на источник «до» sysfs-порога. На производительность это всё равно почти не влияет.

---

## 4. Рекомендации (по ценности и риску). Ничего не применено

### 1. Не дать nvpmodel молча сбрасывать клоки. Ценность высокая, риск низкий
Drop-in, после которого `isolate`/`default` не перезапускает nvpmodel, а если nvpmodel всё же запускается, сразу после него снова выполняется `jetson_clocks`:
```sh
mkdir -p /etc/systemd/system/nvpmodel.service.d
cat > /etc/systemd/system/nvpmodel.service.d/rabbit.conf <<'EOF'
[Service]
RemainAfterExit=yes
ExecStartPost=/usr/bin/jetson_clocks
EOF
systemctl daemon-reload
```
Положить в репозиторий рядом с `workspaces/jetson/rabbit-performance.service` и ставить тем же способом. Перезагрузка не нужна: drop-in начнёт действовать при следующем запуске nvpmodel. Правило для людей и агентов: не запускать `nvpmodel -m`, `systemctl isolate/default`, `jetson_clocks --restore` на живом роботе. Если запустили, после этого выполнить `systemctl restart rabbit-performance` (или `jetson_clocks`). Это стоит дописать в `.claude/skills/rabbit-robot/SKILL.md`, рядом с запретом `nvpmodel -m 0`.

Временное восстановление, если эпизод повторится: `jetson_clocks` (или `systemctl restart rabbit-performance`). Проверка: `jetson_clocks --show`, `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq` (должно быть 1728000), `cat /sys/class/devfreq/17000000.gpu/min_freq` (1020000000).

### 2. Телеметрия и алерты в Forge. Ценность высокая, риск низкий
Сейчас Forge не видит ни OC, ни потерю пола частот: `cpu_freq_mhz` берётся из `scaling_cur_freq` через jtop. Добавить в `telemetry.py` (1 Гц, чтение sysfs от root, jtop уже root):
- `oc1/oc2/oc3_event_cnt` из `/sys/class/hwmon/hwmon*/` с `name == soctherm_oc`, плюс дельта в событиях/с;
- `throttle_ms`: дельта `/sys/kernel/debug/bpmp/debug/soctherm/oc2/event_time` (единицы не задокументированы, но пропорциональны времени троттлинга);
- фактические частоты: `cpuinfo_cur_freq` для cpu0 и cpu4 (по одному на кластер), а также `scaling_min_freq`, GPU `min_freq`/`max_freq`, EMC rate (`/sys/kernel/debug/bpmp/debug/clk/emc/rate`), `/var/lib/nvpmodel/status`;
- флаг `clocks_pinned = (scaling_min_freq == 1728000 && gpu min_freq == 1020000000 && emc == 3199000000)`.

Алерты в HUD / chat-агенте:
- `clocks_pinned == false` дольше 10 с → «jetson_clocks сброшен»;
- OC3 > 20/с дольше 60 с или OC1/OC2 > 0 → предупреждение о питании.

Колонки в `forge.jetson` добавить по процедуре из скилла `forge-dev`.

### 3. Проверить DC-DC и проводку. Ценность средняя, риск низкий, это гигиена, а не причина
Модель DC-DC неизвестна, а `supply_voltage` RoboClaw всё время 11.9–12.0 В: похоже, что RoboClaw и, вероятно, Jetson сидят на одной шине 12 В.
- Узнать модель и ток DC-DC. Для dev kit нужно ≥ 12 В × 4 А (≈50 Вт; NVIDIA: DCJ 9–20 В, до 4.2 А). Лучше иметь отдельный преобразователь для Jetson, не общий с моторами.
- Провод на barrel jack сечением ≥ 0.5 мм² (AWG20) и коротким. Рядом с джеком поставить электролит 470–1000 мкФ, если DC-DC далеко.
- Проверка на стенде: `stress -c 6` плюс движение моторов, смотреть `oc1_event_cnt` и `in1_input`. Если OC1 > 0 или VDD_IN < 4.85 В, менять DC-DC.
- Отдельно: батарея сейчас ≈19 %, при 4S ниже ~13.2 В начнутся реальные проблемы.

### 4. Custom nvpmodel с ограничением max-частот. Ценность низкая сейчас, риск средний
NVIDIA рекомендует именно это («MAXN is an unconstrained power mode… create a custom power mode w/o hitting OC event»). Но у нас темп OC3 от нагрузки не зависит, и потери ~0.5–1.5 %, так что выигрыш сомнителен, а производительность ZED упадёт. Применять только если телеметрия из п. 2 покажет длительные периоды > 30/с во время работы ZED. Пример режима (новый `POWER_MODEL ID=4 NAME=RABBIT` в копии `/etc/nvpmodel/nvpmodel_p3767_0003_super.conf`): `GPU MAX_FREQ 918000000`, `CPU_A78_* MAX_FREQ 1574400`, `EMC MAX_FREQ 3199000000`. `rabbit-performance` (`jetson_clocks`) будет прибивать частоты к этим max. Сначала проверить на стенде.

### 5. Чего не делать
- Не отключать `oc*_throt_en` и не менять `curr*_crit`/`curr*_max`. NVIDIA: «it is not possible to disable. This is mechanism to protect your board», «Do not modify any INA3221 sysfs node value».
- Не трогать BPMP DTB.

### 6. Persistent journal (из jetson-audit.md)
Позволит в следующий раз увидеть, кто и что запускал (systemd isolate, nvpmodel). Риск низкий.

---

## 5. Источники

- NVIDIA Jetson Linux r36.4 Developer Guide, Platform Power and Performance (Orin Nano/NX/AGX): типы OC (UV / average / instantaneous), лимиты 25 Вт для Super, глубины 50/75/87.5 %, «Do not modify any INA3221 sysfs node value». https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html
- OC3 ниже порога, «Instant high power may occur in very small time slot»: https://forums.developer.nvidia.com/t/oc3-raised-at-current-lower-than-critical/321989
- OC1/OC2/OC3 = 4.5 В / avg / instant; подъём crit не помогает: https://forums.developer.nvidia.com/t/very-frequent-oc3-and-oc1-alarms-being-thrown-when-current-limit-isnt-reached/279417
- «Hitting OC in this mode is totally expected»; питание 19 В / 4–4.2 А: https://forums.developer.nvidia.com/t/jetson-orin-nano-super-system-throttled-due-to-over-current-lowcurrent-problem/368504
- DC jack 9–20 В, до 4.2 А: https://forums.developer.nvidia.com/t/power-supply-for-jetson-orin-nano/362326
- VDD_IN модуля всегда 5 В, в том числе в MAXN_SUPER: https://forums.developer.nvidia.com/t/what-is-the-vdd-in-input-logic-for-the-jetson-orin-nano-and-orin-nx-maxn-super-mode/380399
- Custom nvpmodel вместо MAXN: https://forums.developer.nvidia.com/t/jetson-orin-nano-hitting-system-throttled-due-to-over-current/340708, https://forums.developer.nvidia.com/t/system-throttled-due-to-over-current-on-orin-nx/247300
- Отключить нельзя: https://forums.developer.nvidia.com/t/disabling-instantaneous-overcurrent-throttling/375987
- TI INA3221 datasheet (critical alert на каждой конверсии, warning по среднему): https://www.ti.com/lit/ds/symlink/ina3221.pdf

## 6. Как воспроизвести замеры

```sh
# счётчики и INA
ssh rabbit 'grep . /sys/class/hwmon/hwmon3/oc* /sys/class/hwmon/hwmon1/{in1_input,curr1_input,curr1_crit}'
# BPMP (read-only)
ssh rabbit 'grep . /sys/kernel/debug/bpmp/debug/soctherm/oc2/* /sys/kernel/debug/bpmp/debug/soctherm/*_throt_status'
# фактическая частота против запрошенной
ssh rabbit 'grep . /sys/devices/system/cpu/cpu[04]/cpufreq/{cpuinfo_cur_freq,scaling_cur_freq,scaling_min_freq}'
# переключения runlevel
ssh rabbit 'TZ=UTC last -x --time-format iso | head'
```
Скрипт опроса, использованный для таблиц §1.3: `oc3_event_cnt`, `curr1/in1`, `cpuinfo_cur_freq` cpu0/cpu4, GPU `cur_freq`, `*_throt_status`, `oc2/event_time` с периодом 0.05–0.2 с (`python3 - <dur> <period>` через ssh).
