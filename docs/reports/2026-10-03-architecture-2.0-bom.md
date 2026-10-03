# Rabbit 2.0: покупки (BOM)

Приложение к [`2026-10-03-architecture-2.0.md`](2026-10-03-architecture-2.0.md). Выводы и проводка — в [`-wiring.md`](2026-10-03-architecture-2.0-wiring.md).

**Как читать цены:**
- цены проверены 2026-10-03 на страницах производителей и магазинов (ссылки ниже);
- AUD — Core Electronics с GST;
- **«оценка»** — цену проверить не удалось: курс ~1,5 AUD за USD или типичная цена категории;
- **Есть** — уже у владельца.

## Что уже есть

| Позиция | Роль в 2.0 |
|---|---|
| Jetson Orin Nano Super 8 GB dev kit, NVMe 915 ГБ | мозг |
| ZED 2i | камера |
| NEEWER PS099E + площадка V-mount | батарея |
| RoboClaw 2x30A | моторы, энкодеры |
| 2× Pololu 37D 70:1 12 В с энкодерами 64 CPR (#4754) | привод |
| AGFRC A50BHL + Adafruit PCA9685 | руль |
| TI INA4235EVM | монитор питания; заменить шунты, см. `-wiring.md` |
| Pololu D36V50F12 ×2 | один — Jetson; второй освобождается, когда RoboClaw переходит на батарею |
| Pololu D36V50F6 | серва |
| Pololu D24V90F5 (5 В 9 А, вход 5–38 В) | **5 В для Pi**: вместо покупки D24V50F5 |
| Pololu D24V22F12 | резерв (был для TRB246) |
| Raspberry Pi 4 (с мая 2025) | тело; **проверить, что 8 ГБ** |
| Adafruit TCA9548A, Teltonika TRB246, Evemodel блок, XY-CD63L | резерв / отложено |

## Купить

| # | Позиция | Почему эта | Цена | Ссылка |
|---|---|---|---|---|
| 1 | **Лидар Slamtec RPLIDAR C1** | дешевле и точнее LD19: ±30 мм против ±45 мм, 0,72° против ~1°, 6 м по чёрному, IP54. LD19 (Waveshare D300) снят с производства. 0,05–12 м, 10 Гц, 5000 точек/с, UART 3,3 В 460800, 5 В (0,8 А старт / 0,26 А работа), 110 г, Ø55,6 мм | **A$129,95** (в наличии), US$69 | [Core](https://core-electronics.com.au/rplidar-c1-dtof-lidar-360-laser-range-scanner-12m-ip54.html), [DFRobot](https://www.dfrobot.com/product-2803.html), [даташит](https://files.waveshare.com/wiki/RPLIDAR-C1/SLAMTEC_rplidar_datasheet_C1_v1.0_en.pdf) |
| 2 | **4× VL53L8CX на Pololu #3419** | при 5 клк видит в 1,4–1,7 раза дальше, чем VL53L5CX (окна), на 30% экономнее; регуляторы и сдвиг уровней на плате. 8×8 при 15 Гц, 45°×45°, 2–400 см | 4 × A$41,05 = **A$164,20**; US$24,95 шт. | [Core](https://core-electronics.com.au/vl53l8cx-time-of-flight-88-zone-distance-sensor-carrier-with-voltage-regulators-400cm-max.html), [Pololu](https://www.pololu.com/product/3419), [даташит](https://www.farnell.com/datasheets/3930859.pdf) |
| 3 | Регулятор 3,3 В ~1 А с EN для ToF (например, Pololu D24V10F3) | ToF питаются от 3,3 В, не от 3V3 Pi | ~A$12 (оценка) | pololu.com |
| 4 | 6× микропереключатель Omron D2F-01L (4 + 2 запасных) | «01» — для слабых логических токов, нормально замкнутый контакт, 0,78 Н | US$1,44 шт., ~A$15 (оценка) | [DigiKey](https://www.digikey.com/en/products/result?keywords=D2F-01L), [даташит](https://omronfs.omron.com/en_US/ecb/products/pdf/en-d2f.pdf) |
| 5 | **Выключатель Pololu Big Pushbutton HP #2813** | единственный у Pololu ~15 А: 4,5–32 В, 6 А длительно / 16 А тепловой предел, вход OFF ≥ 1 В, ток в выключенном < 0,2 мкА | **A$12,20**, US$8,95 | [Core](https://core-electronics.com.au/big-pushbutton-power-switch-with-reverse-voltage-protection-hp.html), [Pololu](https://www.pololu.com/product/2813) |
| 6 | Кнопка двухполюсная (2NO) без фиксации, 16–19 мм, подсветка 5 В | полюс 1 включает, полюс 2 сообщает Pi | ~A$15 (оценка) | — |
| 7 | TVS SMBJ20A | на выход выключателя (рекомендация Pololu) | ~A$1 (оценка) | — |
| 8 | Блок предохранителей Blue Sea 5025 (6 × ATO, отрицательная шина, крышка) | звезда земли и предохранители в одном месте; 30 А на цепь | US$46,95, ~A$70 (оценка); дешёвый аналог 6×ATO ~A$20 (оценка) | [Blue Sea](https://www.bluesea.com/products/5025/ST_Blade_Fuse_Block_-_6_Circuits_with_Negative_Bus_and_Cover) |
| 9 | Держатель предохранителя ATO в разрыв провода (главный 15 А) | | A$4,30 | [Core](https://core-electronics.com.au/standard-duty-30a-blade-fuse-holder.html) |
| 10 | Предохранители ATO 15, 10, 7,5, 5, 5, 2 А + запас | | ~A$10 (оценка) | — |
| 11 | Шунты 2512 ≥ 1 Вт: 2 мОм и 5 мОм, по 2 шт. (Ohmite PCS2512 или аналог) | каналы 1 и 3 INA, см. `-wiring.md` | ~A$10 (оценка) | — |
| 12 | Конденсатор Panasonic EEU-FR1V102, 1000 мкФ 35 В, 18 мОм | на клеммы RoboClaw | ~US$1–1,7 | [DigiKey](https://www.digikey.com/en/products/detail/panasonic-industry/EEU-FR1V102/2433579) |
| 13 | XT60 пара | от площадки V-mount | A$4,40 | [Core](https://core-electronics.com.au/xt60-connectors-male-female-pair.html) |
| 14 | Силиконовый провод AWG14/16/18/20/22/26, наконечники, термоусадка, JST-XH | | ~A$40 (оценка) | — |
| 15 | 3× MOSFET 2N7000/BSS138, резисторы 1k/4,7k/10k/100k/330, 100 нФ | Q1–Q3, подтяжки | ~A$5 (оценка) | — |
| 16 | RTC Adafruit DS3231 #3013 + CR1220 | время Pi и всей системы без интернета | A$29,95 + ~A$3; US$17,50 | [Core](https://core-electronics.com.au/adafruit-ds3231-precision-rtc-breakout.html), [Adafruit](https://www.adafruit.com/product/3013) |
| 17 | **Raspberry Pi Flash Drive 256 ГБ** (USB 3, UAS, SMART, 22 тыс. IOPS случайной записи) | загрузка и данные; у Samsung T7 известна проблема с загрузкой на Pi 4 (firmware#1799) | **A$109,95**, US$55 | [Core](https://core-electronics.com.au/raspberry-pi-256gb-flash-drive.html), [Raspberry Pi](https://www.raspberrypi.com/products/flash-drive/) |
| 18 | USB-хаб Waveshare USB3.2-Gen1-HUB-4U (металл, клеммы 7–36 В, 2 А на порт) | питание прямо от батареи (F5), не грузит 5 В Pi | US$17,99, ~A$27 (оценка) | [Waveshare](https://www.waveshare.com/usb3.2-gen1-hub-4u.htm); альтернатива — [хаб Raspberry Pi](https://core-electronics.com.au/raspberry-pi-usb-3-0-hub.html) A$21,29 (5 В через USB-C) |
| 19 | **Wi-Fi Alfa AWUS036ACM** (MT7612U, драйвер в ядре с 4.19, 2× RP-SMA 5 дБи, ~380 мА) + USB-удлинитель | зрелый драйвер. У AXML (MT7921) открыта ошибка mt76#1141 на Pi 4 с ядром 6.18 | US$37–47, ~A$65 (оценка) | [morrownr](https://github.com/morrownr/USB-WiFi/blob/main/home/USB_WiFi_Adapters_that_are_supported_with_Linux_in-kernel_drivers.md) |
| 20 | Camera Module 3 Wide (IMX708, 120° по диагонали, 102° по горизонтали, автофокус) + шлейф 300 мм Adafruit #1648 | задняя камера; владелец купит | US$38,50 + US$1,95, ~A$62 (оценка; на Core цена не проверена) | [PiShop](https://www.pishop.us/product/raspberry-pi-camera-module-3-wide/), [Adafruit](https://www.adafruit.com/product/1648) |
| 21 | Cat6 0,5 м | Jetson ↔ Pi | A$4,10 | [Core](https://core-electronics.com.au/cat6-05m-patch-cable-rj45.html) |
| 22 | Охлаждение Pi: 52Pi ICE Tower (вентилятор от 5 В) | Pi внутри корпуса робота под нагрузкой Forge и видео | US$12,48–22, ~A$30 (оценка) | [52Pi](https://52pi.com/collections/ice-tower-cooler-1) |

**Итого купить: ~A$825** (~US$550 по курсу 1,5). Из них ~A$460 — проверенные цены, остальное оценки.

**Если Pi 4 не 8 ГБ:**
- Pi 4 8 ГБ сейчас стоит **A$267,63 / US$165** (подорожание 2025–26 из-за памяти) — итого ~A$1 090;
- 4 ГБ, скорее всего, хватит: Forge ~0,3–1 ГБ, NATS, nginx, узлы тела ~0,5 ГБ.

**Где сэкономить:**

| Замена | Экономия |
|---|---|
| VL53L5CX на Pololu #3417 (A$33,75) | −A$29; хуже на свету, есть Python-драйвер Pimoroni |
| дешёвый блок предохранителей | ~−A$50 |
| хаб Raspberry Pi вместо Waveshare | ~−A$6 |

**Необязательное:**
- Батарейка RTC для Jetson: на dev kit разъём J3 и резистор R560 **не распаяны**. Нужны Molex PicoBlade 53398-0271, резистор 0402 и CR1225 с выводом PicoBlade 51021 (~A$10, оценка, плюс пайка SMD). Предлагается не делать: время Jetson берёт с Pi.
- Изолятор USB (ADuM3160) для USB RoboClaw — если USB останется основным каналом (~A$30, оценка).

## Источники характеристик

- Лидары: [LD19](https://www.elecrow.com/download/product/SLD06360F/LD19_Datasheet_V1.0.pdf), [RPLIDAR C1](https://files.waveshare.com/wiki/RPLIDAR-C1/SLAMTEC_rplidar_datasheet_C1_v1.0_en.pdf), [протокол RPLIDAR](https://files.seeedstudio.com/wiki/SLAMRadar/S3/series_protocol_LR001_SLAMTEC_rplidar_series_protocol_v1.0_en.pdf), [STL-19P (D500)](https://www.waveshare.com/wiki/D500_LiDAR_Kit)
- Драйверы без ROS: [`lds2d`](https://pypi.org/project/lds2d/) (LD19/STL19P/C1, на железе не проверен), [`rplidarc1`](https://pypi.org/project/rplidarc1/), [Slamtec SDK](https://github.com/Slamtec/rplidar_sdk). Свой парсер — ~150 строк.
- ToF: [VL53L5CX](https://www.st.com/resource/en/datasheet/vl53l5cx.pdf), [UM2884](https://www.pololu.com/file/0J1885/um2884-a-guide-to-using-the-vl53l5cx-multizone-timeofflight-ranging-sensor-with-wide-field-of-view-ultra-lite-driver-uld-stmicroelectronics.pdf), [UM3109 (L8CX)](https://www.pololu.com/file/0J2030/um3109-a-guide-for-using-the-vl53l8cx-lowpower-highperformance-timeofflight-multizone-ranging-sensor-stmicroelectronics.pdf)
- Драйверы ToF: [sensebox/CircuitPython_VL53LxCX](https://github.com/sensebox/CircuitPython_VL53LxCX) (L5CX и L8CX, через Blinka), [pimoroni/vl53l5cx-python](https://github.com/pimoroni/vl53l5cx-python) (только L5CX), [ST STSW-IMG042](https://www.st.com/en/embedded-software/stsw-img042.html)
- Pololu: [выключатели](https://www.pololu.com/category/121/pololu-power-switches), [D24V90F5](https://www.pololu.com/product/2866), [D36V50F12](https://www.pololu.com/product/4095), [D36V50F6](https://www.pololu.com/product/4092), [37D #4754](https://www.pololu.com/product/4754)
- RoboClaw: [руководство](https://downloads.basicmicro.com/docs/roboclaw_user_manual.pdf), [даташит 2x30A](https://downloads.basicmicro.com/docs/roboclaw_datasheet_2x30A.pdf); копии в `datasheet/`
- Raspberry Pi 4: [питание и GPIO](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply), [UART](https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts), [overlays README](https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README), [даташит](https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-datasheet.pdf), [цены](https://www.raspberrypi.com/news/a-new-3gb-raspberry-pi-4-for-83-75-and-more-memory-driven-price-increases/), [загрузка с USB](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#usb-mass-storage-boot)
- Jetson: [спецификация несущей платы](https://developer.nvidia.com/downloads/assets/embedded/secure/jetson/orin_nano/docs/jetson_orin_nano_devkit_carrier_board_specification_sp.pdf) (копия в `datasheet/`), [форум о J3/R560](https://forums.developer.nvidia.com/t/orin-nano-official-devkit-rtc-battery-connector-resistor-tidbits/366189)
- Провод: [таблица Cooner](https://www.coonerwire.com/amp-chart/)
