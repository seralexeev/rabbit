# Datasheets

Original PDFs of every part, drawing and app note the designs rely on, one folder per maker (the rule is in
`AGENTS.md`). Designs cite them as `datasheet/<Maker>/<file>.pdf` plus the page.

| Folder | What |
|---|---|
| `TI/`, `ST/`, `NXP/`, `Analog Devices/`, `MEMSIC/`, `TDK/`, `Opsco/`, `MagnTek/` | ICs of the body boards (`pcb/rabbit-body-c`, `pcb/rabbit-body`) and the ToF carrier (`pcb/rabbit-tof`) |
| `Diodes/`, `Infineon/`, `AOS/`, `Nexperia/`, `NCE/` | Discretes: diodes, MOSFETs, transistors |
| `AMASS/`, `JST/`, `GCT/`, `HCTL/`, `Keystone/`, `Kinghelm/`, `QJ/`, `Littelfuse/` | Connectors, battery holders, fuses |
| `Slamtec/` | RPLIDAR C1 (connector XH2.54-5P pinout p.11-12) |
| `ZED/`, `ZED 2i Datasheet v1.2.pdf` | Stereolabs ZED 2i: specs and the technical drawing (M3 holes 36 mm apart) |
| `Raspberry Pi/`, `Pololu/` | Mechanical drawings; `Raspberry Pi/bcm2711-peripherals.pdf` (GPIO alternate functions and power-on pulls, table 94 p.77-78) |
| `Pololu 37D/`, `JGB37-520R30-12/`, `BLDC 37D drop-in/`, `Red Ackerman Racing Car/`, `xArm 1S Robot Arm/` | Drive, chassis and arm documentation |

Not yet saved (the maker sites refuse scripted downloads; save from a browser when next used):
onsemi BSS138LT1G, Nexperia BAT54 series, ST USBLC6-2, Coilcraft XAL1010, ST RM0440 (STM32G4 reference manual) and AN2606 (system bootloader).
