# SLAM, локализация и навигация для Rabbit: что уже существует и что нам подходит

Обзор на 2 октября 2026. Робот и репозиторий не трогались, код читался только для контекста (`workspaces/rabbit/src`, скиллы, `zed-report.md`, `planner-report.md`, `jetson-audit.md`). Оценки, помеченные «(оценка)», не измерены, это мои прикидки.

## Коротко

- **Да, локализацию мы изобретаем заново, а навигацию почти нет.** Вся обвязка вокруг ZED GEN_3 (`relocalization.py`, `JumpGate`, миллиметровый фильтр, таймауты релокализации, архивация `.area`, «сбросить карту, если не привязались», запрет планировщика во время релокализации) нужна только потому, что у нас одна поза, которая и одометрия, и глобальная привязка, и SLAM сидит в чёрном ящике. В ROS это решено давно: непрерывный `odom`, отдельная поправка `map→odom` от локализатора (REP-105) и multi-session карта, которая сама сшивает сессии. Именно этот кусок стоит заменить.
- **Планировщик, nav и explore лучше оставить.** Наш Hybrid A* (асимметричные кривизны, проверка по камере, 30–80 мс на Jetson), выбор точки обзора объекта, слепая зона и память скана — это то, чего в Nav2 нет. Nav2 (Smac Hybrid/Lattice + MPPI + Collision Monitor) — канонический аналог, но переход на него означает ROS 2 на Orin Nano 8 ГБ, где уже сейчас занято 4–5 ГБ. Мы получили бы универсальность, которая нам не нужна, и потеряли бы свои функции.
- **nvblox мы уже используем как библиотеку, и это правильно.**
- **Рекомендация.** Вариант 1: ZED остаётся камерой и источником глубины. Одометрия берётся из **cuVSLAM** (PyCuVSLAM 17, wheel есть прямо под JP6/py3.10, ROS не нужен) или из ZED VIO без area memory. Глобальная локализация и multi-session карта переходят к **RTAB-Map**: он решает kidnapped robot через BoW, сшивает сессии, а его авторы проверяли устойчивость к освещению именно в квартире. Сначала два-три вечера офлайн-экспериментов на записанных SVO, потом shadow-режим на роботе.
- **Чего не делать сейчас:** полный переход на ROS 2 + Isaac ROS + Nav2. На JP6 последняя Isaac ROS 3.2 заморожена, на JP7.2 нужна перепрошивка. На форуме NVIDIA прямо пишут, что ZED wrapper + VSLAM + nvblox + Nav2 не помещаются в Orin Nano 8 ГБ, а cuVGL (глобальная локализация NVIDIA) с ZED не документирован.

---

## 1. Наш случай и что именно болит

| | |
|---|---|
| Робот | Ackermann, ~0.3 м, R_min ≈ 0.3–0.4 м, вправо шире, чем влево. Только передний обзор, слепая зона < 0.3 м |
| Вычислитель | Orin Nano 8GB Super, JP 6.2.1 / L4T 36.4.4, CUDA 12.6, TRT 10.3. Штатный стек занимает ~4–5 ГБ RAM, `zed.py` ~1.9 ГБ RSS (jetson-audit) |
| Сенсоры | ZED 2i по USB (rolling shutter, IMU), энкодеров нет, лидара нет |
| Среда | квартира, освещение меняется, ходят люди, робота переносят и включают где угодно, headless |
| Стек | ZED SDK 5.5 GEN_3 + `.area`, NEURAL_LIGHT depth, свой nvblox (nanobind), Hybrid A* (numba), frontier explore, pure pursuit + scan guard, YOLOE |

Боли, все про **локализацию**: GEN_3 застревает в INITIALIZING после переноса; `.area`, сохранённый в LOST, ломает релокализацию; несколько секунд поза идёт в мм; `grab()` встаёт на 2–4 с после релокализации; GEN_3 копит keyframes даже стоя и ест 0.5–1 ядро; GEN_1 в 5.5 не релокализуется по `.area`; при неудаче карту приходится сбрасывать. Из ответа Stereolabs на форуме (авг. 2026) видно, что релокализация GEN_3 устроена через loop closure. Если робот стоит в начале карты, «loop closure искать негде» и статус остаётся INITIALIZING. Значит, GEN_3 должен проехать по уже знакомому месту, чтобы привязаться, а это плохо сочетается с «включили где угодно и сразу хотим ехать».

---

## 2. Visual / visual-inertial SLAM: сравнительная таблица

| Система | Версия / активность | Лицензия | ROS нужен? | Kidnapped / wake-up anywhere | Map save/load, multi-session | Orin Nano 8GB | Вердикт для нас |
|---|---|---|---|---|---|---|---|
| **ZED SDK GEN_3** (сейчас) | 5.5.0, 17.09.2026 | проприетарная, бесплатна с камерой | нет | через loop closure: нужно движение по знакомому месту; у нас нестабильно | `.area`, одна сессия; порча файла на долгих сессиях (форум) | работает, но 0.5–1 ядро CPU на оптимизатор и копит keyframes | оставить как камеру и глубину, **локализацию забрать** |
| **cuVSLAM / PyCuVSLAM** (NVIDIA) | v17.0.0, 21.07.2026; open source с v15 (03.2026); репо активно (push 02.10.2026) | NVIDIA Community License: коммерческое использование разрешено, **только на NVIDIA-железе** | **нет**: C++ и Python API, wheel `cu12-cp310-aarch64` под JP6 | `LocalizeInMap` **требует prior pose** и ищет по сетке вокруг него. Документация: «no tracking-lost recovery support». Распознавание мест (BoW/DBoW2/AnyLoc) только в **draft PR #168** | `SaveMap`/`LocalizeInMap` (LMDB); при успехе загруженная карта заменяет текущую, слияния сессий нет | очень лёгкий: Orin AGX stereo 1.8 мс/кадр, 5.5% CPU; на Orin Nano Super 1–2 стереопары с запасом (статья cuVSLAM) | **лучший кандидат на одометрию** (stereo + IMU, GPU, низкий CPU). Для wake-up anywhere одного его не хватает |
| **Isaac ROS Visual SLAM** (cuVSLAM в ROS) | 3.2 (последняя под JP6, Humble); 4.6 (18.08.2026, Orin на JP7.2, Jazzy); 5.0 (21.09.2026, Lyrical) | Apache-2.0 (обёртка) | да | то же: `LoadMapAndLocalize` с prior pose | то же | работает; вместе с остальным Isaac-стеком упирается в RAM (форум) | смысла нет: PyCuVSLAM даёт то же без ROS |
| **RTAB-Map** | 0.23.8 (07.2026), теги 0.23.13 для ROS-дистрибутивов, push 02.10.2026, 4k★ | BSD-3 (основная часть) | **нет**: C++ библиотека, CLI, standalone-приложение (brew на Mac, Docker). Есть и `rtabmap_ros` | **да, это его сильная сторона**: в localization mode BoW по всей карте (WM подгружается из LTM), выдаёт поправку `map→odom` и не трогает одометрию | **multi-session**: новая сессия сама сшивается со старой при первом совпадении; memory management (STM/WM/LTM); localization mode | CPU-шный, ~1 Гц обновления графа (этого достаточно, одометрия идёт отдельно). Своя VO хрупкая (индустриальный бенчмарк: теряла одометрию), поэтому одометрию нужно давать внешнюю | **лучший кандидат на глобальную локализацию и карту** поверх внешней одометрии |
| ORB-SLAM3 | v1.0 (2021), последний push 07.2024 | GPL-3 | нет | да (DBoW2, Atlas) | Atlas, save/load | CPU-тяжёлый; есть GPU-форк Jetson-ORB-SLAM3 (статья 2026) | не поддерживается, GPL. Брать незачем |
| OpenVINS | push 11.2025 | GPL-3 | ROS-ориентирован | нет (только VIO) | нет | ок | только одометрия; cuVSLAM лучше |
| VINS-Fusion | push 05.2024 | GPL-3 | да | частично (loop closure, pose graph reuse) | save/load pose graph | ок | заброшен |
| Kimera-VIO / Hydra / Khronos | Kimera-VIO 08.2026, Hydra/Khronos активны | BSD | да | loop closure (Kimera-RPGO) | scene graphs | тяжело вместе с сегментацией | исследовательский уровень, нам рано |
| Basalt | push 03.2026 | BSD-3 | нет | нет | офлайн-маппинг | лёгкий | только VIO |
| DROID-SLAM / DPVO / MASt3R-SLAM / VGGT-SLAM | активны (DPVO 09.2026) | MIT/BSD/NC | нет | — | — | **нет**: DROID ~24 ГБ GPU; DPVO ~3 ГБ при ~18 FPS на десктопе; MASt3R-SLAM 15 FPS на RTX 4090; VGGT-SLAM 2.0 3.5 FPS на Thor | не для Orin Nano рядом с остальным стеком |
| Spectacular AI SDK | 1.53 | бесплатно только non-commercial; **ARM-бинарники только по коммерческой лицензии** | нет | VISLAM + Mapping API | да | Jetson через коммерческую лицензию | ZED не поддерживается, ARM платный. Не наш вариант |

Вывод по разделу: в 2026 году нет одной open-source системы, которая на Orin Nano без ROS сразу даёт и быструю стабильную VIO, и надёжный wake-up anywhere. Лучшая комбинация из двух частей: **cuVSLAM (одометрия) + RTAB-Map (глобальная локализация и карта)**. RTAB-Map умеет брать cuVSLAM как одометрию: в upstream есть `OdometryCuVSLAM`, но под старый C API v14. В форке CoMPASLab прямо сейчас (октябрь 2026) чинят обработку потери трекинга cuVSLAM внутри RTAB-Map. Сами мы можем подать одометрию в RTAB-Map как внешнюю, это проще.

---

## 3. Глобальная локализация с нуля (kidnapped robot), только зрение

| Подход | Как работает | Без ROS | Освещение | Orin Nano |
|---|---|---|---|---|
| **RTAB-Map localization mode** | BoW (по умолчанию GFTT/ORB, опционально SuperPoint) по всем узлам карты → геометрическая проверка (PnP) → `map→odom` | да | слабое место любых локальных фич. Решение авторов: **multi-session карта** из сессий при разном свете. Статья Labbé & Michaud 2022 тестировала это **в реальной квартире** на закате каждые 30 мин; SuperPoint дал лучшую релокализацию | CPU, ~1 Гц. SuperPoint через libtorch тяжёл для Nano; ORB/GFTT нормально |
| **cuVSLAM `LocalizeInMap`** | поиск по сетке (радиус, шаг, угол) вокруг prior pose | да | — | быстро, но **нужен prior**. В draft PR #168 добавляют VPR: AnyLoc дал 92.9% межсессионно против 49.3% у следующего бэкенда, BoW/DBoW2 хуже. Не смержено |
| **Isaac ROS cuVGL** (Visual Global Localization) | BoW-retrieval + стерео relative pose; карта строится офлайн из rosbag | **нет** (ROS-пакет, бинарная библиотека) | — | Humble/Jetson заявлены. **ZED не документирован**: NVIDIA на форуме отвечает «документации для ZED нет, проверьте rqt_graph». Пайплайн создания карт заточен под Nova/Hawk |
| **ZED GEN_3 `.area`** | loop closure по area map | да | рекомендовано картировать при тех же условиях | у нас нестабильно (см. §1) |
| **Свой VPR + PnP** (hloc-стиль: MegaLoc / AnyLoc / SALAD / BoQ на DINOv2 + SuperPoint/LightGlue + PnP) | ищем похожий keyframe в базе, потом PnP по 3D-точкам keyframe (глубина ZED) | да | DINOv2-дескрипторы заметно устойчивее к свету, чем ORB. MegaLoc (2025) обучен в том числе на ScanNet (indoor) | LightGlue TRT fp16 на Orin Nano Super: 7.9 мс при 512 точках, 21.6 мс при 1024. DINOv2 ViT-S/B через TRT: десятки мс (оценка). Запускается раз в секунду при поиске, так что укладывается |

Мнение: для квартиры 50–100 м² с картой из нескольких сессий RTAB-Map — самое дешёвое и проверенное решение. Свой VPR + PnP — это ровно то же колесо, только мы бы писали его сами. Он оправдан только как prior для cuVSLAM (вариант 2) или если multi-session RTAB-Map не справится с вечерним светом. Тогда DINOv2-дескриптор (MegaLoc) подключается в RTAB-Map как глобальный дескриптор: там есть `PyDescriptor`/NetVLAD-хук с 0.22.

---

## 4. Карта и навигация: Nav2 против нашего стека

| Функция | У нас | Nav2 / Isaac | Вердикт |
|---|---|---|---|
| Кадры `map`/`odom`/`base` | одна поза ZED, которая прыгает; `JumpGate`, `plausible_position`, re-anchoring в nav | tf2, REP-105: `odom` непрерывен, `map→odom` от локализатора | **это колесо мы изобрели плохо.** Нужно перенять идею (без ROS), см. §7 |
| 3D-карта → 2D | nvblox (TSDF → ESDF slice → clearance grid), пересборка по поправкам keyframes | isaac_ros_nvblox + костмап-плагин Nav2 | мы уже на библиотеке, всё правильно. В nvblox есть dynamic mode и people segmentation, но **для ZED dynamic mode официально не поддержан** (issue #175, сент. 2026, без ответа) |
| Глобальный планировщик | Hybrid A* (numba): асимметричные кривизны влево и вправо, камера как точка цели, analytic shots, cost-aware, 30–80 мс | Smac Hybrid-A* (Dubins/Reeds-Shepp, **один** `minimum_turning_radius`), Smac State Lattice (примитивы из файла) | Smac не знает асимметрии: пришлось бы брать худший радиус или генерировать свой lattice. Выигрыша нет, **оставить своё** |
| Контроллер | pure pursuit по задней оси + scan guard (слепая зона, память точек < 0.4 м) | RPP, MPPI (Ackermann `min_turning_r`), Collision Monitor | MPPI для Ackermann требует тонкой настройки: открытый issue #5714 (11.2025), где MPPI плохо держит путь в поворотах и задним ходом. Collision Monitor ≈ наш guard, но памяти слепой зоны в нём нет. **Оставить**, позаимствовать идеи (полигоны slowdown/stop/approach) |
| Логика поездки | `Navigator`: выбор цели, replanning, backup по своему следу, ожидание перед объездом | BT Navigator + recoveries (BackUp, Wait), Route Server | у Nav2 это общее и расширяемое, но точки обзора объекта, «не ехать задом в неизвестное» и правила прибытия для Ackermann всё равно пришлось бы писать как BT-плагины |
| Exploration | frontier + планировщик | в Nav2 нет; сторонний m-explore-ros2 (простой) | оставить |
| Open-RMF | — | управление флотами, лифты, двери | к нам не относится |

**Что можно взять без ROS 2:** cuVSLAM (PyCuVSLAM/C++), nvblox core (уже взяли), RTAB-Map (C++ lib, CLI), LightGlue/SuperPoint/DINOv2 через TRT. **Что требует ROS 2:** Nav2 целиком (плагины завязаны на `nav2_costmap_2d`, lifecycle, tf2), cuVGL, Isaac Perceptor, nvblox-костмап для Nav2.

**ROS 2 на нашем железе.** На JP6 (Ubuntu 22.04) нативно ставится Humble, но Humble заканчивается в **мае 2027**. Isaac ROS для Orin на JP6 есть только в 3.2 (2024–2025, заморожена). Новые Isaac ROS 4.6 (Jazzy) и 5.0 (Lyrical) требуют **JP 7.2**, то есть перепрошивки (1–3 дня, jetson-audit §3). Документация 4.6 для Orin Nano прямо говорит, что board-prep под Nano отдельный, а основная инструкция написана для AGX.

---

## 5. Семантика: «поезжай к холодильнику»

| Система | Что делает | Где работает | Для Orin Nano |
|---|---|---|---|
| ConceptGraphs (2023, MIT, push 10.2025) | 3D scene graph объектов с CLIP + LLM | десктопный GPU, в основном офлайн | нет |
| HOV-SG (2024) | иерархия этажи → комнаты → объекты | тяжёлый | нет |
| VLMaps (2023) | плотные LSeg-фичи в карте | тяжёлый | нет |
| OK-Robot (2024), DynaMem / stretch_ai (2024–2026) | объектная память (voxel + SigLIP/OWLv2) + LLM; DynaMem умеет «забывать» исчезнувшее | Stretch + внешний GPU-сервер | идеи да, код нет |
| OneMap (2024–25) | real-time open-vocab карта для object-nav | Orin **AGX**, ~2 Гц | Nano примерно в 4 раза слабее, впритык |
| Isaac ROS + foundation models | детекторы и сегментация на TRT, FoundationStereo | ROS | частично |

Мнение: наш подход (YOLOE на TRT через ZED custom detector → треки → объектная память в ClickHouse → LLM в Forge → выбор точки обзора) и есть «OK-Robot-lite», то есть тот же паттерн, что в state of the art, но в масштабе Nano. Готового стека под Orin Nano нет, **здесь мы не изобретаем колесо**. Дешёвое улучшение: хранить на каждый объект CLIP/SigLIP-эмбеддинг кропа (маленькая TRT-модель раз в N кадров) для open-vocab запросов вида «синяя кружка», а тяжёлые VLM-запросы отправлять в облако через Forge.

---

## 6. Коммерческие и готовые решения

| Продукт | Что даёт | Цена | Для нас |
|---|---|---|---|
| Stereolabs ZED SDK | бесплатен с камерой | — | уже есть |
| ZED X Mini (GMSL, **global shutter**) + ZED Link Mono | лучше для VSLAM на ходу, чем rolling-shutter ZED 2i | $599 + €139 | хороший апгрейд камеры, если упрёмся в смаз и rolling shutter. Совместимо с любым из вариантов |
| ZED Box Mini (Orin Nano) | готовый компьютер | от $879 | нам не нужен |
| NVIDIA Isaac Perceptor | cuVSLAM + cuVGL + nvblox + офлайн-создание карт | бесплатно, но референс-железо Nova Orin (AGX) с Hawk-камерами; ROS | не под Nano + ZED |
| Slamcore | коммерческий SDK (Jetson Orin), ориентирован на RealSense и склады | по запросу (B2B) | дорого и закрыто, для домашнего робота не стоит |
| Spectacular AI | VISLAM, mapping API | ARM только коммерчески; ZED не поддерживается | нет |
| Kudan (KdVisual) | коммерческий VSLAM, интеграция с Isaac Perceptor | по запросу | нет |
| Orin NX 16GB вместо Nano 8GB | вдвое больше RAM | модуль заметно дороже Nano; цены Jetson выросли в 2026 (Orin Nano Super $249 → $399) | единственное, что делает вариант 3 (полный ROS) реалистичным |

---

## 7. Что мы изобретаем заново, а что действительно наше

**Изобретаем заново, и это стоит заменить:**
1. **Управление глобальной привязкой**: `lib/relocalization.py`, таймауты, «3 м без привязки», рестарты процесса с архивацией `.area`, запрет поездок во время `relocalizing`. Всё это обвязка вокруг чёрного ящика, который не умеет multi-session. RTAB-Map делает это штатно: не привязался — продолжает жить в `odom`, при первом совпадении выдаёт поправку `map→odom`, а новую сессию сшивает со старой картой без сброса.
2. **Скачки позы**: `JumpGate`, `plausible_position`, re-anchoring в nav. Это следствие того, что nav ездит в глобальном кадре. По REP-105 nav, guard, pure pursuit и память скана работают в непрерывном `odom`, а глобальные цели переводятся через последнюю поправку `map→odom`. Скачок тогда меняет только поправку, путь перепланируется, а одометрия под колёсами не прыгает. **Эту идею можно внедрить уже сейчас, без смены SLAM**: `odom` получается накоплением покадровых дельт ZED (`get_position(..., REFERENCE_FRAME.CAMERA)`), причём дельты больше физически возможных отбрасываются. World-поза ZED тогда служит только источником поправки `map→odom`. Проверить, не протекают ли скачки релокализации в дельты GEN_3.
3. **Сброс карт при неудачной релокализации.** Multi-session RTAB-Map решает это по построению.

**Колесо есть, но наше не хуже. Оставить:**
- Hybrid A*, pure pursuit, frontier exploration, логика поездки. Аналоги Nav2 есть, но наши проще, оттюнингованы под асимметричную кинематику и слепую зону, покрыты симулятором и replay. Переход сам по себе ничего не исправит.
- nvblox через nanobind: это уже использование библиотеки, а не изобретение.

**Действительно своё (готового нет):**
- асимметричные таблицы кривизны и геометрия «камера ≠ задняя ось»;
- слепая зона передней камеры и память точек;
- выбор точки обзора объекта и правила прибытия для Ackermann;
- NATS, Forge, HUD и LLM-чат вокруг всего этого;
- объектная память с запросами на естественном языке под Orin Nano.

---

## 8. Варианты миграции (по убыванию рекомендации)

### Вариант 1 (рекомендую): ZED как камера + cuVSLAM (или ZED VIO) как odom + RTAB-Map как глобальная карта и локализация. Без ROS

**Схема.**
- `zed.py` берёт `grab()`, NEURAL_LIGHT depth, rectified left/right и IMU. Позиционный трекинг ZED выключается совсем (лучше всего) или работает в VIO-режиме без area memory.
- Одометрия: **PyCuVSLAM** в режиме Inertial (stereo + IMU) на GPU. В репозитории cuVSLAM есть готовые примеры `examples/zed/live` и `examples/zed/recording/track_svo`. Запасной путь — ZED GEN_1 или GEN_3 VIO без `.area`.
- **RTAB-Map** (libRTABMap через nanobind, как `rabbit_nvblox`, или процесс `rtabmap` в отдельном контейнере) получает keyframe (RGB + depth или стерео) с odom-позой ~1 раз в секунду. Отдаёт `map→odom`, оптимизированные позы узлов (для пересборки nvblox, механизм `_correct_stored_frames` у нас уже есть), статус «локализован или нет».
- nav, guard и pure pursuit работают в `odom`. Планировщик и explore работают в `map` и при скачке `map→odom` перепланируют.

**Работа.** Офлайн-эксперимент 2–3 вечера. Интеграция 2–3 недели (оценка): обёртка RTAB-Map ~300–600 строк C++/nanobind, трекер cuVSLAM ~200 строк Python, перевод nav в odom-кадр, миграция места хранения карты.

**Что удаляем.** `lib/relocalization.py`, `lib/pose_gate.py` (JumpGate), работу с `.area` в `zed.py` (save/load/archive, `_check_relocalization`, рестарты по таймауту релокализации, миллиметровый фильтр как механизм защиты; проверку правдоподобия можно оставить как assert), re-anchoring в nav, отказы планировщика «пока relocalizing» (останется «нет `map→odom` — нет глобальных целей», а локальная езда разрешена). По грубой оценке 400–700 строк кода и тестов, а главное — целый класс инцидентов.

**Риски на Orin Nano 8 ГБ.**
- RAM: cuVSLAM ~0.2–0.5 ГБ GPU/unified (оценка), RTAB-Map на квартиру ~0.3–0.6 ГБ (оценка). При этом уходят память и CPU GEN_3 (keyframes, оптимизатор 0.5–1 ядро), так что баланс, скорее всего, нулевой или положительный. Проверить замером.
- CPU: экстракция фич RTAB-Map на CPU при 1 Гц — доли ядра (оценка).
- Свет: ORB/GFTT вечером хуже. Митигируем multi-session (картировать при 2–3 режимах освещения), а если этого не хватит — глобальным DINOv2-дескриптором.
- Калибровка: cuVSLAM критичен к калибровке и синхронизации стерео и IMU. ZED отдаёт заводскую калибровку и синхронные кадры, это плюс.
- Лицензия cuVSLAM разрешает использование только на NVIDIA-железе. Для нас это не ограничение.
- RTAB-Map без официальных Python-биндингов: нужен свой C++-слой (опыт с nanobind есть) или отдельный процесс.

### Вариант 2: всё на cuVSLAM (SLAM + save/load) + свой VPR для prior. Без ROS

**Схема.** PyCuVSLAM в режиме OdometryWithSlam. Карта сохраняется через `SaveMap`. При старте берётся prior из своего VPR (MegaLoc/AnyLoc на DINOv2 через TRT по базе keyframes с позами), затем `localize_in_map(guess, LocalizationSettings)`. Пока нет привязки, работаем в odom.

**Плюсы.** Одна быстрая GPU-библиотека, минимум CPU, активная разработка NVIDIA. Если **PR #168** (VPR внутри `LocalizeInMap`, бэкенд AnyLoc) смержат, свой VPR не понадобится, и этот вариант может стать лучшим.

**Минусы.** Сегодня wake-up anywhere — это своя разработка (VPR, база, пороги, проверка ложных срабатываний). Сшивания сессий нет: загрузка заменяет карту, а «неправильная карта — автоматического ремонта нет» (документация cuVSLAM). Recovery после потери трекинга тоже на нас.

**Работа.** 3–5 недель (оценка). **Что удаляем:** то же, что в варианте 1. **RAM:** меньше всех (оценка).

### Вариант 3: ROS 2 + Isaac ROS (cuVSLAM, nvblox, cuVGL) + Nav2 (Smac + MPPI + Collision Monitor)

**Схема.** zed-ros2-wrapper → isaac_ros_visual_slam → isaac_ros_nvblox → Nav2. Мост ROS ↔ NATS для HUD и Forge. Либо JP 6.2 + Humble + Isaac ROS 3.2 (тупик к маю 2027), либо перепрошивка на JP 7.2 + Isaac ROS 4.6 (Jazzy) / 5.0 (Lyrical).

**Работа.** 6–10 недель (оценка) плюс перепрошивка.

**Что удаляем.** Почти весь `zed.py`, `planner.py`, `trip.py`, `navmap.py`, `nav.py`, `explore.py`, часть `safety.py` (~5000 строк). Взамен пишем launch-файлы, YAML, BT-плагины для объектных поездок, lattice-примитивы под асимметричный руль и мост.

**Риски.**
- **RAM**: прямой отчёт на форуме NVIDIA — «RAM Orin Nano не хватает на ZED Wrapper + VSLAM + NVBLOX + NAV2».
- cuVGL с ZED не документирован.
- MPPI для Ackermann капризен (#5714).
- Isaac Perceptor рассчитан на Nova/AGX.
- Теряем симулятор и replay-тесты.

Имеет смысл только вместе с Orin NX 16GB или AGX и если цель — «стандартный ROS-робот», а не этот робот.

### Вариант 0 (базовая линия): остаться на ZED GEN_3

Завести issue в `stereolabs/zed-sdk` с минимальным SVO + `.area` для миллиметров и зависаний `grab()`. Ждать исправлений. Обвязка остаётся и будет расти.

---

## 9. План экспериментов (снять риски до любых изменений в репо)

**Принцип.** Одни и те же записи гоняются через всех кандидатов. Решение принимается по цифрам, а не по README.

**Этап 0. Датасет (1 вечер, на роботе нужна только запись; ведёте вы джойстиком или переносите руками).**
1. Наклеить 6–8 меток из малярного скотча на полу в разных комнатах (центр комнаты, лицом к стене, коридор, у холодильника, тёмный угол). Это наш дешёвый ground truth.
2. **S1, mapping**: медленный проход по всей квартире по часовой стрелке и против, днём, 6–10 мин. Встать на каждую метку на 3 с.
3. **S2–S8, wake-up**: робот выключен, его переносят на метку (каждый раз на другую), включают и записывают 1–2 мин, сначала стоя 10 с, потом небольшой проезд. Освещение: день, вечер с лампами, полумрак. В 2–3 сессиях в кадре ходит человек.
4. Записывать SVO2 (с IMU, в `zed.py` есть запись) и параллельно текущие позы ZED в Forge.

**Этап 1. Офлайн-прогон.** Jetson в простое или любой x86 с NVIDIA GPU. RTAB-Map и на Mac.

| Кандидат | Как | Где |
|---|---|---|
| A. ZED GEN_3 (база) | `.area` из S1, релокализация S2–S8 из SVO (с учётом совета Stereolabs: не стартовать с кадра 0 той же записи) | Jetson |
| B. cuVSLAM VO | `examples/zed/recording/track_svo`, Inertial-режим: дрейф на петле S1 (старт = финиш), потери трекинга, CPU/GPU/RAM | Jetson |
| C. cuVSLAM SLAM + `localize_in_map` | карта из S1. Для S2–S8: (а) prior = метка ±0.5 м / ±30°; (б) «слепой» поиск по сетке на всю квартиру (время, успех) | Jetson |
| D. RTAB-Map | экспорт SVO → rectified стерео (или RGB + NEURAL depth) + калибровка + odom-позы из B. `rtabmap-reprocess` / `rtabmap-console`: карта из S1, localization mode на S2–S8; затем multi-session (S1 + вечерняя сессия) и повторный тест ночной | Mac (`brew install rtabmap`) или Jetson в Docker |
| E. (если D проседает вечером) | глобальный дескриптор MegaLoc в RTAB-Map или как prior для C | Jetson |

**Метрики на каждую wake-up сессию:** привязался или нет; время и пройденный путь до привязки; ошибка в метке (поза на метке минус поза метки в карте S1); ложные привязки (> 0.5 м); стабильность позы после привязки (нет миллиметров, нет скачков, нет зависаний). Для победителя на Jetson: CPU (ядра), RAM/GPU-память, задержка позы.

**Критерии перехода к варианту 1:** ≥ 90% wake-up сессий привязываются за ≤ 10 с и ≤ 1 м пути, ошибка ≤ 0.15 м на метках, **ноль** ложных привязок > 0.5 м, суммарный CPU не выше нынешнего GEN_3. Если cuVSLAM VO на ZED 2i нестабилен (rolling shutter, смаз), одометрией становится ZED VIO без `.area`, а вопрос ZED X Mini откладываем на потом.

**Этап 2. Shadow-режим на роботе (несколько дней).** Победитель работает рядом с текущим стеком и публикует `rabbit.loc.*` (`map→odom`, статус), а nav его пока не потребляет. Forge пишет обе позы, сравниваем в ClickHouse на реальных включениях. Только после этого переключаем nav и планировщик.

**Независимо от выбора, сделать уже сейчас:**
- Разделить в nav `odom` и `map` (§7, п. 2). Это убирает класс багов при любом SLAM.
- Завести issue в Stereolabs с SVO-репро.
- Следить за cuVSLAM PR #168 (VPR в `LocalizeInMap`): если его смержат, пересмотреть вариант 2.

---

## Источники

**cuVSLAM / Isaac ROS**
- [nvidia-isaac/cuVSLAM (open source, v17.0.0, CHANGELOG, doc/load_map.md)](https://github.com/nvidia-isaac/cuVSLAM) · [releases](https://github.com/nvidia-isaac/cuVSLAM/releases) · [PyCuVSLAM](https://github.com/nvidia-isaac/PyCuVSLAM)
- [cuVSLAM: CUDA accelerated visual odometry and mapping (arXiv 2506.04359)](https://arxiv.org/html/2506.04359v2)
- [cuVSLAM PR #168: visual place recognition for LocalizeInMap (draft)](https://github.com/nvidia-isaac/cuVSLAM/pull/168)
- [Isaac ROS cuVSLAM concepts (LocalizeInMap требует prior pose)](https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/index.html)
- [Isaac ROS release notes (3.2 … 5.0)](https://nvidia-isaac-ros.github.io/releases/index.html)
- [Isaac ROS 4.6 на Orin / JetPack 7.2](https://openelab.io/blogs/learn/isaac-ros-4-6-jetson-orin-jetpack-7-2)
- [isaac_ros_visual_global_localization (cuVGL)](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_mapping_and_localization/isaac_ros_visual_global_localization/index.html) · [Visual Global Localization concepts](https://nvidia-isaac-ros.github.io/concepts/visual_global_localization/index.html)
- [Форум: cuVGL с ZED — документации нет](https://forums.developer.nvidia.com/t/how-to-create-cuvgl-maps-for-a-custom-robot-using-zed-camera/323622)
- [Isaac Perceptor: mapping and localization tutorial](https://nvidia-isaac-ros.github.io/v/release-3.2/reference_workflows/isaac_perceptor/tutorial_mapping_and_localization.html)
- [Форум: Orin Nano не хватает RAM на ZED wrapper + VSLAM + nvblox + Nav2](https://forums.developer.nvidia.com/t/enquiry-for-suitable-jetson-for-visual-slam-and-nvbox-application/309934) · [Orin Nano 8GB + nvblox (2026)](https://forums.developer.nvidia.com/t/jetson-orin-nano-8gb-com-problemas-para-executar-pilha-isaac-ros-nvblox/361504)
- [Isaac ROS Nvblox](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_nvblox/index.html) · [nvblox technical details (dynamics, people)](https://nvidia-isaac-ros.github.io/concepts/scene_reconstruction/nvblox/technical_details.html) · [issue #175: dynamic mode и ZED](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nvblox/issues/175) · [nvblox releases](https://github.com/nvidia-isaac/nvblox)

**RTAB-Map**
- [introlab/rtabmap releases (0.23.8)](https://github.com/introlab/rtabmap/releases) · [RTAB-Map (IntRoLab)](https://introlab.3it.usherbrooke.ca/index.php/RTAB-Map)
- [Labbé & Michaud, Multi-Session Visual SLAM for Illumination-Invariant Re-Localization in Indoor Environments (2022)](https://arxiv.org/abs/2103.03827)
- [Appearance-Based Loop Closure Detection for Online Large-Scale and Long-Term Operation (memory management)](https://arxiv.org/pdf/2407.15304)
- [CoMPASLab/rtabmap: cuVSLAM odometry fixes (2026)](https://github.com/CoMPASLab/rtabmap/pull/5)
- [Industrial cuVSLAM Benchmark & Integration (arXiv 2603.16240)](https://arxiv.org/html/2603.16240)

**ZED SDK**
- [ZED SDK 5.5 release notes](https://docs.stereolabs.com/docs/development/zed-sdk/release-notes/5-x/5-5) · [Positional tracking modes (GEN_1 / GEN_3)](https://docs.stereolabs.com/docs/development/zed-sdk/modules/positional-tracking/modes) · [Area memory & VSLAM mapping](https://docs.stereolabs.com/docs/development/zed-sdk/modules/positional-tracking/vslam-mapping-tutorial)
- [Форум: SPATIAL_MEMORY_STATUS stuck at INITIALIZING (ответ Stereolabs, 08.2026)](https://community.stereolabs.com/t/using-positionaltracking-sample-has-spatial-memory-status-stuck-at-initializing/11595)
- [Форум: area file corruption on long runtimes](https://community.stereolabs.com/t/zed-area-file-corruption-on-long-runtimes/9764) · [Stagnant poses with GEN_3](https://community.stereolabs.com/t/stagnant-poses-with-gen-3-tracking/9566) · [GEN_3 + enable_imu_fusion](https://community.stereolabs.com/t/gen-3-positional-tracking-does-not-work-if-tracking-parameters-enable-imu-fusion-is-set-to-true/11361)
- [ZED X](https://www.stereolabs.com/products/zed-x) · [ZED Link Mono](https://www.stereolabs.com/en-lu/store/products/zed-link-capture-card-mono) · [ZED Box Mini](https://www.stereolabs.com/blog/zed-box-mini)

**Nav2**
- [MPPI controller](https://navigation.ros.org/configuration/packages/configuring-mppic.html) · [MPPI Ackermann issue #5714](https://github.com/ros-navigation/navigation2/issues/5714)
- [Smac Hybrid-A*](https://navigation.ros.org/configuration/packages/smac/configuring-smac-hybrid.html) · [nav2_smac_planner (Jazzy)](https://docs.ros.org/en/ros2_packages/jazzy/api/nav2_smac_planner/__README.html)
- [ROS 2 distributions 2026 (Humble EOL 05.2027, Lyrical)](https://www.robocloudhub.tech/learn/blog/ros2-distributions-2026)

**Другие VSLAM и learned**
- [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) · [Jetson-ORB-SLAM3 (2026)](https://arxiv.org/pdf/2608.17874) · [OpenVINS](https://github.com/rpng/open_vins) · [VINS-Fusion](https://github.com/HKUST-Aerial-Robotics/VINS-Fusion) · [Kimera-VIO](https://github.com/MIT-SPARK/Kimera-VIO) · [Hydra](https://github.com/MIT-SPARK/Hydra) · [Basalt](https://github.com/VladyslavUsenko/basalt-mirror)
- [Deep Patch Visual SLAM (DPVO/DPV-SLAM)](https://arxiv.org/html/2408.01654v1) · [UAV VSLAM multi-paradigm evaluation (DPVO 3.1 GB)](https://arxiv.org/html/2605.03678) · [MASt3R-SLAM](https://opencv.org/mast3r-slam/) · [VGGT-SLAM 2.0](https://www.emergentmind.com/papers/2601.19887)
- [Spectacular AI SDK docs](https://spectacularai.github.io/docs/sdk/) · [Slamcore (Tracxn)](https://tracxn.com/d/companies/slamcore/__SOl4qynBBOI7eVdR65mFkq2ddmnNA_H7xmcezu3p68Y) · [Kudan + Isaac Perceptor](https://www.kudan.io/a-technical-deep-dive-into-visual-data-driven-amrs-powered-by-kdvisual-and-nvidia-isaac-perceptor/)

**Place recognition / matching**
- [MegaLoc (2025)](https://arxiv.org/pdf/2502.17237) · [AnyLoc](https://github.com/AnyLoc/AnyLoc) · [VPR methods for pair retrieval (2026)](https://arxiv.org/html/2603.13917) · [hloc](https://github.com/cvg/Hierarchical-Localization)
- [LightGlue на Orin Nano Super (TRT 10.3, fp16)](https://huggingface.co/kornia/lightglue) · [LightGlue-ONNX/TensorRT](https://github.com/fabio-sim/LightGlue-ONNX)

**Семантика**
- [ConceptGraphs](https://github.com/concept-graphs/concept-graphs) · [OK-Robot](https://github.com/ok-robot/ok-robot) · [DynaMem](https://arxiv.org/abs/2411.04999) · [stretch_ai](https://github.com/hello-robot/stretch_ai) · [OneMap](https://arxiv.org/html/2409.11764) · [go2-semantic-nav (Orin NX)](https://github.com/yusufdxb/go2-semantic-nav)

**Железо**
- [Цены Jetson 2026](https://hwbusters.com/news/nvidia-jetson-prices-jump-up-to-101-the-249-orin-nano-super-is-now-399/) · свой `jetson-audit.md` (RAM, JetPack, ZED 5.5)
