"""Hand routing of the power paths, ground planes, keepouts and stitching (rev B).

Current paths are copper pours (F.Cu and B.Cu where both are free) and wide tracks; the autorouter only adds the
low-current taps (net-class widths in build_board.py). Widths follow IPC-2152 for 1 oz outer copper (gen/calc.py):
14 A needs 7.5 mm on each of two layers, 10 A 4.7 mm, 6 A 2.3 mm, 4.5 A 1.6 mm.

Grounds: In1 is solid GND except the GND_MOT island under the motor block (In1 + B.Cu). GND_MOT carries the DRV8316
power ground, the bulk caps and the brake chopper, and joins GND only through NT1 next to the battery connector
(J1 pin 2 is the star point). Motor phase currents stay inside the island.
"""
import math

import pcbnew

F, B, IN1, IN2 = pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu

BOARD_POLY = [(-61, -136), (61, -136), (61, 136), (-61, 136)]

# GND_MOT island on In1 and B.Cu: motor drivers, bulk caps, brake chopper; J10 (ToF RL) and the power input stay
# on GND (notches)
GND_MOT_ISLAND = [(-56.0, -92.0), (39.0, -92.0), (39.0, -100.5), (44.6, -100.5), (44.6, -117.2), (-44.0, -117.2),
                  (-44.0, -109.6), (-56.0, -109.6)]
# B.Cu island copper the autorouter sees: only under the DRV8316s (exposed-pad heat); over the rest of the island
# B.Cu is a GND_MOT fill made after routing, so the vias that bring the drive signals under the MOT_BUS bar fit
GND_MOT_B = [[(x0 - 3.2, -101.8), (x0 + 3.2, -101.8), (x0 + 3.2, -110.2), (x0 - 3.2, -110.2)] for x0 in (-26.0, 26.0)]

# pours: (net, layers, polygon, priority)
def rel(x0, y0, pts):
    return [(x0 + x, y0 + y) for x, y in pts]


# LM61495 VIN copper beside the VIN2 / VIN1 pins and their 470 nF and 10 uF caps (SNVSBZ4A fig. 11-2), open
# outward; the rest of each outline is added per buck
VIN_L = [(-2.0, 1.45), (-2.0, 0.8), (-0.85, 0.8), (-0.85, 0.35), (-3.3, 0.35), (-3.3, -1.5)]
VIN_R = [(x, y) for x, y in reversed([(-x, y) for x, y in VIN_L])]

POURS = [
    # battery input chain: XT60 -> F1 -> Q1 (ideal diode) -> Q2 (switch) -> 2 mOhm shunt -> VBUS
    ("BAT_IN", (F, B), [(45.4, -102.4), (54.8, -102.4), (54.8, -90.3), (45.4, -90.3)], 20),
    ("BAT_F", (F, B), [(40.9, -94.8), (44.0, -94.8), (44.0, -89.6), (54.8, -89.6), (54.8, -84.0), (51.3, -84.0),
                       (51.3, -82.3), (44.6, -82.3), (44.6, -88.2), (40.9, -88.2)], 20),
    ("SW_MID", (F, B), [(45.6, -81.6), (54.8, -81.6), (54.8, -64.9), (45.6, -64.9)], 20),
    ("VBUS_RAW", (F, B), [(48.8, -64.3), (55.2, -64.3), (55.2, -59.6), (51.0, -59.6), (51.0, -56.9), (46.6, -56.9),
                          (46.6, -62.6), (48.8, -62.6)], 20),
    ("VBUS", (F, B), [(46.4, -53.2), (50.95, -53.2), (50.95, -50.7), (54.0, -50.7), (54.0, -52.2), (58.3, -52.2),
                      (58.3, -34.0), (36.2, -34.0), (36.2, -46.6), (37.4, -46.6), (37.4, -50.2), (46.4, -50.2)], 20),
    # VBUS spine under the Pi to the front, the front strip on B.Cu and the feeds of F3, F4, C33 and the Jetson eFuse
    ("VBUS", (F, B), [(38.5, -34.5), (46.0, -34.5), (46.0, 34.3), (38.5, 34.3)], 20),
    ("VBUS", (B,), [(-44.6, 33.4), (46.0, 33.4), (46.0, 40.2), (-8.8, 40.2), (-8.8, 51.0), (-14.6, 51.0),
                    (-14.6, 40.2), (-44.6, 40.2)], 20),
    ("VBUS", (F, B), [(-45.2, 35.0), (-41.6, 35.0), (-41.6, 39.0), (-45.2, 39.0)], 20),
    ("VBUS", (F,), [(29.0, 34.3), (46.6, 34.3), (46.6, 48.3), (32.4, 48.3), (32.4, 40.6), (29.0, 40.6)], 20),
    ("VBUS", (F, B), [(-14.6, 48.2), (-9.45, 48.2), (-9.45, 50.6), (-14.6, 50.6)], 20),
    # motor branch: F2 -> 5 mOhm -> MOT_BUS corridor, the bar over the brake resistors, lobes at the DRV8316 VM pins
    ("MOT_F", (F, B), [(28.9, -50.6), (35.0, -50.6), (35.0, -46.4), (31.3, -46.4), (31.3, -47.5), (28.9, -47.5)], 20),
    ("MOT_BUS", (F, B), [(22.9, -47.5), (25.6, -47.5), (25.6, -87.6), (31.4, -87.6), (31.4, -91.0), (25.6, -91.0),
                         (25.6, -91.6), (22.9, -91.6)], 20),
    ("MOT_BUS", (F,), [(-55.0, -96.6), (25.6, -96.6), (25.6, -91.6), (-55.0, -91.6)], 20),
    ("MOT_BUS", (F,), [(-55.0, -105.0), (-45.6, -105.0), (-45.6, -96.6), (-55.0, -96.6)], 20),
    ("MOT_BUS", (F,), [(-38.6, -96.6), (-35.4, -96.6), (-35.4, -106.9), (-29.1, -106.9), (-29.1, -110.4),
                       (-33.1, -111.4), (-38.6, -111.4)], 20),
    ("MOT_BUS", (F,), [(12.0, -96.6), (16.6, -96.6), (16.6, -106.9), (22.9, -106.9), (22.9, -110.4), (18.9, -111.4),
                       (12.0, -111.4)], 20),
    ("BRK_D", (F,), [(-11.3, -99.5), (11.3, -99.5), (11.3, -102.3), (2.7, -102.3), (2.7, -107.4), (-2.7, -107.4),
                     (-2.7, -102.3), (-11.3, -102.3)], 20),
    # 5.1 V buck (U4 at -30, 45) and 6 V buck (U6 at 14, 45): VIN band beside the VIN pins, SW to the inductor
    ("BODY_IN", (F,), rel(-30.0, 45.0, VIN_L + [(-6.0, -1.5), (-6.0, -9.6), (-9.8, -9.6), (-9.8, 1.45)]), 20),
    ("BODY_IN", (F,), rel(-30.0, 45.0, VIN_R + [(6.5, 1.45), (6.5, -1.5)]), 20),
    ("BODY_IN", (B,), [(-39.0, 43.4), (-23.5, 43.4), (-23.5, 46.3), (-39.0, 46.3)], 20),
    ("SW4", (F,), [(-30.9, 44.5), (-29.1, 44.5), (-29.1, 48.0), (-27.9, 48.0), (-27.9, 52.4), (-32.1, 52.4),
                   (-32.1, 48.0), (-30.9, 48.0)], 21),
    ("+5V", (F,), [(-37.6, 57.5), (-22.4, 57.5), (-22.4, 63.7), (-37.6, 63.7)], 20),
    ("STEER_IN", (F,), rel(14.0, 45.0, VIN_L + [(-6.5, -1.5), (-6.5, 1.45)]), 20),
    ("STEER_IN", (F,), rel(14.0, 45.0, VIN_R + [(13.0, 1.45), (13.0, -8.1), (10.0, -8.1), (10.0, -1.5)]), 20),
    ("STEER_IN", (B,), [(5.0, 43.4), (23.2, 43.4), (23.2, 46.3), (5.0, 46.3)], 20),
    ("SW6", (F,), [(13.1, 44.5), (14.9, 44.5), (14.9, 48.0), (16.1, 48.0), (16.1, 52.4), (11.9, 52.4),
                   (11.9, 48.0), (13.1, 48.0)], 21),
    ("6V_RAW", (F,), [(8.6, 57.5), (21.6, 57.5), (21.6, 63.7), (6.4, 63.7), (6.4, 60.2), (8.6, 60.2)], 20),
    # servo 6 V from R2 (B.Cu) up the right side and along the nose to the servo headers
    ("SERVO_6V", (B,), [(31.6, 47.6), (39.8, 47.6), (39.8, 81.5), (20.5, 103.0), (20.5, 111.2), (-8.4, 111.2),
                        (-8.4, 108.2), (14.8, 108.2), (14.8, 101.0), (33.9, 79.0), (33.9, 52.4), (31.6, 52.4)], 20),
    # Jetson eFuse output -> 10 mOhm -> XT30
    ("JET_OUT", (F,), [(-3.95, 48.2), (-1.3, 48.2), (-1.3, 53.4), (-6.4, 58.9), (-9.3, 58.9), (-9.3, 56.0),
                       (-7.0, 56.0), (-5.1, 53.6), (-5.1, 51.6), (-3.95, 51.6)], 20),
    ("JET_PWR", (F, B), [(-2.95, 56.1), (0.4, 56.1), (0.4, 59.8), (-17.6, 68.2), (-25.0, 74.2), (-29.6, 74.2),
                         (-29.6, 69.9), (-25.8, 69.9), (-20.3, 65.4), (-2.95, 59.0)], 20),
]

# hand tracks: (net, layer, width mm, points)
TRACKS = [
    # star: NT1 GND side to the battery minus (J1 pin 2)
    ("GND", F, 3.0, [(42.5, -104.5), (47.5, -104.5), (50.0, -106.5)]),
    # 5 V to the Pi header pins 2 and 4 (Pi up to ~3 A incl. USB)
    ("+5V", F, 2.0, [(-22.8, 59.0), (-19.9, 59.0), (-19.9, 34.0)]),
    ("+5V", F, 1.2, [(-19.9, 34.0), (-21.13, 32.6), (-21.13, 31.27)]),
    ("+5V", F, 1.2, [(-19.9, 34.0), (-18.59, 32.6), (-18.59, 31.27)]),
    # 6 V to the servo shunt (peaks of 6 A last seconds; 3 mm is ~3.6 A continuous at +20 C)
    ("6V_RAW", F, 3.0, [(21.4, 60.4), (36.0, 60.4), (36.0, 57.1), (34.45, 55.55)]),
    ("SERVO_6V", F, 2.0, [(34.45, 49.45), (36.6, 49.45), (37.6, 50.6)]),
    # Jetson eFuse P_IN (pin 6) into the VBUS piece
    ("VBUS", F, 0.3, [(-8.86, 46.67), (-10.0, 46.67), (-10.0, 48.4)]),
    # LM74800 C pins into SW_MID; CP cap VM pads into the lobes
    ("SW_MID", F, 0.2, [(43.39, -72.25), (45.9, -72.25)]),
    ("SW_MID", F, 0.2, [(43.39, -73.25), (45.9, -73.25)]),
]


def drv_tracks(x0):
    """Phase outputs (pairs 13/14, 16/17, 19/20) to the VH connector and DRV8316 pin stubs; x0 = DRV centre X."""
    t = []
    y0 = -106.0
    ja = {-26.0: (-29.96, -26.0, -22.04), 26.0: (22.04, 26.0, 29.96)}[x0]
    for (ph, px), jx in zip((("A", x0 - 1.5), ("B", x0), ("C", x0 + 1.5)), ja):
        net = f"M{'L' if x0 < 0 else 'R'}{ph}"
        t.append((net, F, 0.6, [(px, y0 - 3.6), (px, y0 - 4.6), (jx, y0 - 7.0)]))
        t.append((net, F, 1.5, [(jx, y0 - 7.0), (jx, -129.5)]))
        t.append((net, B, 1.5, [(jx, y0 - 7.5), (jx, -129.5)]))
    for yy in (-107.75, -108.25):                              # VM 10-11 into the lobe, 9 joined to 10
        t.append(("MOT_BUS", F, 0.25, [(x0 - 2.4, yy), (x0 - 3.6, yy)]))
    t.append(("MOT_BUS", F, 0.2, [(x0 - 2.7, -107.25), (x0 - 2.7, -107.75)]))
    y, s = y0, ("L" if x0 < 0 else "R")
    t += [(f"BK_{s}", F, 0.2, [(x0 - 2.6, y + 1.75), (x0 - 3.35, y + 1.73), (x0 - 8.0, y + 1.45)]),
          (f"SWBK_{s}", F, 0.2, [(x0 - 2.6, y + 0.75), (x0 - 3.35, y + 0.77)]),
          (f"CPL_{s}", F, 0.15, [(x0 - 2.6, y + 0.25), (x0 - 4.3, y + 0.23)]),
          (f"CPH_{s}", F, 0.15, [(x0 - 2.6, y - 0.25), (x0 - 3.75, y - 0.25), (x0 - 4.3, y - 0.7)]),
          (f"CP_{s}", F, 0.2, [(x0 - 2.6, y - 0.75), (x0 - 3.35, y - 0.79)])]
    for (px, py), (qx, qy) in (((x0 - 2.4, -103.75), (x0 - 1.6, -103.75)), ((x0 - 2.4, -104.75), (x0 - 1.6, -104.75)),
                               ((x0 - 2.4, -108.75), (x0 - 1.6, -108.75)), ((x0 - 0.75, -109.4), (x0 - 0.75, -108.6)),
                               ((x0 + 0.75, -109.4), (x0 + 0.75, -108.6)), ((x0 + 2.4, -106.25), (x0 + 1.6, -106.25))):
        t.append(("GND_MOT", F, 0.25, [(px, py), (qx, qy)]))   # AGND 2, GND_BK 4, PGND 12/15/18, AGND 26 -> EP
    return t


def buck_vias(x0, y0):
    """AGND via under the LM61495 body between SW and the FB/AGND/RT pins (AGND 8 and SPSP/MODE 11-12 join it), and
    one beside the RT resistor's ground end."""
    return rel(x0, y0, [(0.0, -1.15), (1.25, -5.8)])


def buck_tracks(n, x0, y0, vin, vout):
    """LM61495 pin stubs: SW out between VIN2 and RBOOT to CBOOT, RBOOT-CBOOT short at the pins, CBOOT pin to the
    cap, BIAS to its cap (SNVSBZ4A p.48), SPSP to SYNC/MODE (both GND, one via); VCC, FB, RT and EN fanned out
    to the control parts below, VOUT down the left of them, VIN to the EN divider."""
    return [(f"SW{n}", F, 0.25, rel(x0, y0, [(0.0, -0.03), (-2.45, -0.03)])),
            (f"BOOT{n}", F, 0.2, rel(x0, y0, [(-1.25, -0.525), (-1.25, -1.025)])),
            (f"BOOT{n}", F, 0.25, rel(x0, y0, [(-1.6, -1.025), (-2.45, -1.025)])),
            (vout, F, 0.2, rel(x0, y0, [(-1.6, -1.525), (-2.0, -1.525), (-2.52, -2.05)])),
            ("GND", F, 0.2, rel(x0, y0, [(1.85, -1.525), (1.85, -1.025)])),
            ("GND", F, 0.25, rel(x0, y0, [(0.0, -1.7), (0.0, -1.15), (1.2, -1.025)])),
            ("GND", F, 0.25, rel(x0, y0, [(0.95, -4.975), (1.25, -5.8)])),
            (f"VCC{n}", F, 0.25, rel(x0, y0, [(-1.3, -2.3), (-1.3, -2.8)])),
            (f"FB{n}", F, 0.2, rel(x0, y0, [(-0.5, -2.3), (-0.5, -6.7), (0.525, -6.7)])),
            (f"FB{n}", F, 0.2, rel(x0, y0, [(0.775, -8.3), (0.6, -6.7)])),
            (f"FF{n}", F, 0.2, rel(x0, y0, [(-1.825, -8.3), (-0.775, -8.3)])),
            (vout, F, 0.25, rel(x0, y0, [(-3.375, -8.3), (-2.1, -7.3), (-2.1, -6.7), (-2.3, -6.3), (-2.3, -2.6),
                                         (-2.52, -2.2)])),
            (f"RT{n}", F, 0.2, rel(x0, y0, [(0.5, -2.3), (0.5, -2.7), (0.95, -3.15), (0.95, -3.425)])),
            (f"EN{n}", F, 0.2, rel(x0, y0, [(1.6, -0.525), (2.3, -0.525), (2.3, -3.1), (2.175, -3.5), (2.175, -5.1)])),
            (vin, F, 0.3, rel(x0, y0, [(3.825, -3.5), (3.825, -1.6)]))]


TRACKS += drv_tracks(-26.0) + drv_tracks(26.0) + buck_tracks(4, -30.0, 45.0, "BODY_IN", "+5V") + buck_tracks(6, 14.0, 45.0, "STEER_IN", "6V_RAW")

# connections the autorouter does not make: pads to a pour (it does not route to planes on signal layers) and
# pins boxed in by their neighbours
TRACKS += [
    # LED anode to its resistor
    ("LED5_A", F, 0.25, [(-47.0, 31.33), (-47.0, 33.21)]), ("LED12_A", F, 0.25, [(-40.5, 60.32), (-40.5, 62.21)]),
    ("LED6_A", F, 0.25, [(38.6, 58.82), (38.6, 60.71)]), ("LED33_A", F, 0.25, [(5.0, 75.32), (5.0, 77.21)]),
    ("LEDB_A", F, 0.25, [(56.6, -58.32), (56.6, -60.21)]), ("MCU_LED_A", F, 0.25, [(7.825, -59.4), (9.61, -59.4)]),
    # motor INA226: A1/A0 and VS sit on opposite sides; join them under B.Cu
    ("+3V3_PI", F, 0.25, [(29.55, -39.0), (29.55, -39.5)]),
    ("+3V3_PI", F, 0.25, [(29.4, -39.0), (28.6, -38.3)]),
    ("+3V3_PI", B, 0.3, [(28.6, -38.3), (28.6, -37.3), (33.6, -37.3), (33.6, -43.7)]),
    ("+3V3_PI", F, 0.3, [(33.6, -43.7), (33.625, -42.9)]),
    # spare motor-bus terminal J49: its GND_MOT pin is just outside the island, two vias into it
    ("GND_MOT", B, 1.5, [(-53.0, -89.92), (-53.0, -91.2), (-55.3, -91.2), (-55.3, -94.4)]),
    ("GND_MOT", B, 1.5, [(-53.0, -91.2), (-50.7, -91.2), (-50.7, -94.4)]),
    # LM74800 right column: CAP (11) between the VS/C stubs, OUT (9) and HGATE (8) out through vias, GND (7) down
    ("LM_CAP", F, 0.2, [(43.39, -72.75), (44.6, -72.75)]), ("LM_CAP", IN2, 0.2, [(44.6, -72.75), (44.625, -71.45)]),
    ("LM_CAP", F, 0.2, [(44.625, -71.45), (44.625, -70.6)]),
    ("VBUS_RAW", F, 0.25, [(43.39, -73.75), (44.45, -73.75)]),
    ("VBUS_RAW", B, 0.3, [(44.45, -73.75), (45.2, -73.0), (45.2, -63.9), (49.2, -63.9)]),
    ("HG", F, 0.2, [(43.39, -74.25), (44.3, -74.25), (44.9, -74.45)]),
    ("HG", IN2, 0.2, [(44.9, -74.45), (46.3, -73.05), (46.3, -63.2), (46.0, -62.9)]),
    ("HG", F, 0.2, [(46.0, -62.9), (46.6, -62.3)]),
    ("GND", F, 0.25, [(43.39, -74.75), (43.9, -74.75), (44.1, -75.5)]),
    # buck outputs back to their control parts (BIAS, feedback) under the input caps
    ("+5V", F, 0.25, [(-33.55, 35.7), (-33.375, 36.4)]),
    ("+5V", IN2, 0.3, [(-33.55, 35.7), (-33.55, 55.6), (-35.3, 57.2), (-35.3, 58.2)]),
    ("6V_RAW", F, 0.25, [(10.45, 35.7), (10.625, 36.4)]),
    ("6V_RAW", IN2, 0.3, [(10.45, 35.7), (10.45, 55.6), (9.0, 57.0), (9.0, 58.2)]),
    # 5 V: Pi-header track to C9, the +5V pour to the ToF LDO across the Jetson-power band
    ("+5V", F, 0.5, [(-22.4, 37.45), (-20.6, 37.45)]),
    ("+5V", IN2, 0.4, [(-22.9, 61.8), (-14.0, 71.0), (-11.0, 77.54)]), ("+5V", F, 0.4, [(-11.0, 77.54), (-9.6, 77.54)]),
    ("+5V", F, 0.3, [(-14.0, 71.0), (-13.0, 71.8)]),
    # button connector J15 pin 4 (5 V) across the empty front
    ("+5V", IN2, 0.3, [(-11.0, 77.54), (-11.0, 86.6), (25.0, 86.6), (26.5, 88.3), (44.2, 88.3)]),
    ("+5V", F, 0.3, [(44.2, 88.3), (45.0, 89.4)]),
    # servo LED resistor R37 and test point TP3 down to the SERVO_6V pour on B.Cu
    ("SERVO_6V", F, 0.3, [(38.6, 57.17), (38.6, 56.2), (40.5, 54.0)]),
    # lidar connector J12 5 V from the same In2 trunk; ToF LDO enable from its pull-up R26 down the left of U7
    ("+5V", IN2, 0.3, [(-33.0, 97.0), (-24.6, 88.4), (-11.0, 86.6)]),
    ("TOF_EN", F, 0.2, [(-10.1, 72.46), (-11.6, 72.46), (-11.6, 81.3), (-10.82, 81.6)]),
    # Jetson-power LED resistor to the XT30 pad
    ("JET_PWR", F, 0.3, [(-40.5, 58.68), (-41.6, 58.68), (-41.6, 72.0), (-29.0, 72.0)]),
    # 5 V LED resistor to the Pi header 5 V pin
    ("+5V", F, 0.3, [(-47.0, 29.68), (-45.8, 30.9), (-22.0, 30.9), (-21.4, 31.27)]),
    # eFuse UVLO divider top to the P_IN stub; OVP divider top down into the B.Cu VBUS strip
    ("VBUS", F, 0.25, [(-12.0, 46.225), (-10.45, 46.67), (-10.0, 46.67)]),
    ("VBUS", F, 0.25, [(-12.0, 41.375), (-12.0, 40.35)]),
    # 5 V to the motor block (MCU LDO, Hall / encoder supplies): from the Pi-header track down In2 between the header
    # pins and under the Pi
    ("+5V", IN2, 0.3, [(-19.86, 36.0), (-19.86, 26.0), (-5.0, 11.0), (-5.0, -55.0), (5.0, -61.3)]),
    ("+5V", F, 0.3, [(5.0, -61.3), (5.86, -62.3)]),
    ("+5V", F, 0.3, [(5.4, -62.55), (4.8, -62.85), (4.8, -64.15), (5.4, -64.45)]),   # MCU LDO IN to EN
    # latch hold zener D8 to the VBUS_RAW stub of the LM74800
    ("VBUS_RAW", F, 0.25, [(36.0, -66.65), (34.9, -67.3)]), ("VBUS_RAW", B, 0.3, [(34.9, -67.3), (45.2, -67.3)]),
    # brake comparator pull-up R60 to the MOT_BUS bar, under the BRK_D pour
    ("MOT_BUS", F, 0.25, [(7.4, -107.82), (7.4, -109.0)]), ("MOT_BUS", B, 0.3, [(7.4, -109.0), (5.0, -108.0), (5.0, -97.6)]),
    ("MOT_BUS", F, 0.3, [(5.0, -97.6), (5.0, -96.3)]),
    # brake comparator supply (R55) and threshold divider (R57) up to the bar beside the TVS
    ("MOT_BUS", F, 0.3, [(-16.43, -104.2), (-16.43, -96.4)]),
    # latch side of the battery feed (LM74800 A/VSNS, Q4, test point) into the BAT_F pour
    ("BAT_F", F, 0.4, [(37.0, -92.6), (41.3, -92.6)]),
    ("BAT_F", F, 0.25, [(40.3, -73.25), (40.3, -72.75), (38.9, -72.75), (38.4, -72.0)]),
    ("BAT_F", F, 0.25, [(38.4, -71.9), (39.3, -71.4)]),
    ("BAT_F", B, 0.4, [(39.3, -71.4), (39.1, -71.8), (39.1, -88.2), (41.6, -88.9)]),
] + [t for x0 in (-26.0, 26.0) for t in (
    # DRV8316 VREF (37, front row) to AVDD (25, right column): small vias in the fan-out, In2 around the exposed pad
    (f"AVDD_{'L' if x0 < 0 else 'R'}", F, 0.15, [(x0 - 0.25, -102.6), (x0 - 0.25, -101.3)]),
    (f"AVDD_{'L' if x0 < 0 else 'R'}", IN2, 0.2, [(x0 - 0.25, -101.3), (x0 + 4.6, -101.3), (x0 + 4.6, -107.25),
                                                  (x0 + 3.3, -107.25)]),
    (f"AVDD_{'L' if x0 < 0 else 'R'}", F, 0.15, [(x0 + 3.3, -107.25), (x0 + 3.3, -106.75), (x0 + 2.6, -106.75)]),
    # the three INL pins (28, 30, 32) between the INH pins: small vias right of the pins, joined on In2
    (f"INL_{'L' if x0 < 0 else 'R'}", IN2, 0.2, [(x0 + 3.6, -105.25), (x0 + 3.6, -103.25)]))] + [
    (f"INL_{'L' if x0 < 0 else 'R'}", F, 0.2, [(x0 + 2.4, y), (x0 + 3.6, y)])
    for x0 in (-26.0, 26.0) for y in (-105.25, -104.25, -103.25)]

VIAS = [
    # phase pairs F <-> B
    ("MLA", [(-29.96, -114.6), (-29.96, -116.0)], 0.8, 0.4), ("MLB", [(-26.0, -114.6), (-26.0, -116.0)], 0.8, 0.4),
    ("MLC", [(-22.04, -114.6), (-22.04, -116.0)], 0.8, 0.4), ("MRA", [(22.04, -114.6), (22.04, -116.0)], 0.8, 0.4),
    ("MRB", [(26.0, -114.6), (26.0, -116.0)], 0.8, 0.4), ("MRC", [(29.96, -114.6), (29.96, -116.0)], 0.8, 0.4),
    # GND_MOT: star tie, bulk caps, brake FET sources
    ("GND_MOT", [(41.0, -110.0), (42.5, -110.6), (44.0, -110.0)], 0.8, 0.4),
    ("GND_MOT", [(-40.0, -101.6), (-40.0, -103.0), (-40.0, -104.4), (-43.6, -100.9)], 0.8, 0.4),
    ("GND_MOT", [(27.6, -98.6), (29.5, -99.0), (31.4, -98.6)], 0.8, 0.4),
    ("GND_MOT", [(-1.9, -110.4), (0.0, -110.6), (1.9, -110.4)], 0.6, 0.3),
    # servo 6 V down to the B.Cu pour
    ("SERVO_6V", [(37.0, 51.0), (38.3, 51.0)], 0.8, 0.4),
    # B.Cu halves of the buck inputs and of MOT_F (the F.Cu pours are split by the pads)
    ("BODY_IN", [(-38.6, 44.3)] + rel(-30.0, 45.0, [(-5.5, -1.0), (-4.6, -1.0), (4.6, -1.0), (5.5, -1.0)]), 0.6, 0.3),
    ("STEER_IN", [(22.5, 44.3)] + rel(14.0, 45.0, [(-5.5, -1.0), (-4.6, -1.0), (4.6, -1.0), (5.5, -1.0)]), 0.6, 0.3),
    ("MOT_F", [(31.77, -49.6), (31.77, -48.2)], 0.8, 0.4),
    # buck PGND next to the input caps (the F.Cu GND fill joins the PGND pads and the cap grounds)
    ("GND", [(xc + dx, 49.1) for xc in (-30.0, 14.0) for dx in (-5.5, -4.2, -2.9, 2.9, 4.2, 5.5)], 0.6, 0.3),
    ("GND", buck_vias(-30.0, 45.0) + buck_vias(14.0, 45.0), 0.6, 0.3),
    ("+3V3_PI", [(28.6, -38.3), (33.6, -43.7)], 0.6, 0.3),
    ("GND_MOT", [(-55.3, -93.0), (-50.7, -93.0), (-55.3, -94.4), (-50.7, -94.4)], 0.8, 0.4),
    ("LM_CAP", [(44.6, -72.75), (44.625, -71.45)], 0.46, 0.2),
    ("VBUS_RAW", [(44.45, -73.75)], 0.46, 0.2), ("HG", [(44.9, -74.45), (46.0, -62.9)], 0.46, 0.2),
    ("GND", [(44.1, -75.5)], 0.6, 0.3),
    ("+5V", [(-14.0, 71.0), (44.2, 88.3)], 0.6, 0.3),
    ("VBUS", [(-12.0, 40.35), (-44.65, 35.8), (-44.65, 37.2), (-44.65, 38.6)], 0.6, 0.3),
    ("BAT_F", [(39.3, -71.4)], 0.6, 0.3),
    ("SERVO_6V", [(38.6, 56.2)], 0.6, 0.3), ("MOT_BUS", [(7.4, -109.0), (5.0, -97.6)], 0.6, 0.3),
    ("AVDD_L", [(-26.25, -101.3), (-22.7, -107.25)], 0.46, 0.2), ("AVDD_R", [(25.75, -101.3), (29.3, -107.25)], 0.46, 0.2),
    ("INL_L", [(-22.4, y) for y in (-105.25, -104.25, -103.25)], 0.46, 0.2),
    ("INL_R", [(29.6, y) for y in (-105.25, -104.25, -103.25)], 0.46, 0.2),
    ("+5V", [(-33.55, 35.7), (-35.3, 58.2), (-22.9, 61.8), (-11.0, 77.54), (-19.86, 36.0), (5.0, -61.3)], 0.6, 0.3),
    ("6V_RAW", [(10.45, 35.7), (9.0, 58.2)], 0.6, 0.3),
    ("VBUS_RAW", [(34.9, -67.3)], 0.6, 0.3),
]

# copper keepouts around the deck standoffs (washers / nuts) and the Pi screws
STANDOFF_KEEPOUT = 4.6
def circle(x, y, r, n=20):
    return [(x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def inside(poly, x, y):
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def obstacles(bl):
    """Pads as (x, y, r, net, half_w, half_h): r is the bounding radius (stitching), the box is for fan-out."""
    out = []
    for fp in bl.b.GetFootprints():
        for p in fp.Pads():
            x = pcbnew.ToMM(p.GetPosition().x) - 150
            y = 150 - pcbnew.ToMM(p.GetPosition().y)
            r = max(pcbnew.ToMM(p.GetSize().x), pcbnew.ToMM(p.GetSize().y)) / 2
            bb = p.GetBoundingBox()
            out.append((x, y, r, p.GetNetname(), pcbnew.ToMM(bb.GetWidth()) / 2, pcbnew.ToMM(bb.GetHeight()) / 2))
    return out


def box_dist(px, py, ox, oy, hw, hh):
    return math.hypot(max(abs(px - ox) - hw, 0.0), max(abs(py - oy) - hh, 0.0))


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def clear_of_tracks(x, y, net, margin):
    for tnet, layer, w, pts in TRACKS:
        if tnet == net:
            continue
        for (ax, ay), (cx, cy) in zip(pts, pts[1:]):
            if seg_dist(x, y, ax, ay, cx, cy) < w / 2 + margin:
                return False
    return True


def stitch(bl, net, poly, obs, vias, pitch=3.0, margin=1.6):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    x = min(xs) + 1.2
    n = 0
    while x < max(xs) - 1.0:
        y = min(ys) + 1.2
        while y < max(ys) - 1.0:
            ok = inside(poly, x, y) and all(inside(poly, x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            if ok:
                for ox, oy, r, onet, hw, hh in obs:
                    lim = r + (0.9 if onet == net else margin)
                    if (ox - x) ** 2 + (oy - y) ** 2 < lim * lim:
                        ok = False
                        break
            if ok and not clear_of_tracks(x, y, net, 0.8):
                ok = False
            if ok and any(math.hypot(px - x, py - y) < 1.3 for px, py in vias):
                ok = False
            if ok:
                bl.via(net, (x, y), 0.8, 0.4)
                vias.append((x, y))
                n += 1
            y += pitch
        x += pitch
    return n


def board_outline():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).with_name("outline.json")).read_text())
    pts = []
    for sgm in data["segments"]:
        pts.append(tuple(sgm["start"]))
        if sgm["type"] == "arc":
            pts.append(tuple(sgm["mid"]))
    return pts


OUTLINE = board_outline()


def via_spot(x, y, w, h, cx, cy, net, obs, vias, reach=0.55):
    """First clear via position next to a pad: along the pad's long axis away from the footprint centre first,
    then the other directions; checks other-net pads, hand tracks, placed vias, the board edge, the ZED cut and
    which ground plane (GND or the GND_MOT island) is under the via."""
    import design
    dirs = []
    horiz = w > 1.3 * h or (h <= 1.3 * w and abs(x - cx) * h >= abs(y - cy) * w)
    main = (math.copysign(1, (x - cx) or 1), 0) if horiz else (0, math.copysign(1, (y - cy) or 1))
    dirs = [main, (main[1], main[0]), (-main[1], -main[0]), (-main[0], -main[1])]
    cut = design.CUTOUTS[0]
    for k in range(5):
        for dx, dy in dirs:
            half = (w if dx else h) / 2
            vx, vy = x + dx * (half + reach + 0.35 * k), y + dy * (half + reach + 0.35 * k)
            if not inside(OUTLINE, vx, vy) or not all(inside(OUTLINE, vx + ex, vy + ey) for ex, ey in
                                                     ((1, 0), (-1, 0), (0, 1), (0, -1))):
                continue
            if cut[0][0] - 1.0 < vx < cut[1][0] + 1.0 and cut[0][1] - 1.0 < vy < cut[2][1] + 1.0:
                continue
            isl = inside(GND_MOT_ISLAND, vx, vy)
            near_edge = any(inside(GND_MOT_ISLAND, vx + ex, vy + ey) != isl for ex, ey in
                            ((0.9, 0), (-0.9, 0), (0, 0.9), (0, -0.9)))
            if near_edge or (net == "GND_MOT") != isl:
                continue
            ok = True
            for ox, oy, r, onet, hw, hh in obs:
                if onet == net:
                    continue
                if box_dist(vx, vy, ox, oy, hw, hh) < 0.3 + 0.2:
                    ok = False
                    break
                if any(box_dist(x + (vx - x) * f, y + (vy - y) * f, ox, oy, hw, hh) < 0.15 + 0.15
                       for f in (0.25, 0.5, 0.75, 1.0)):
                    ok = False
                    break
            if ok and any(math.hypot(px - vx, py - vy) < 0.95 for px, py in vias):
                ok = False
            if ok and not clear_of_tracks(vx, vy, net, 0.3 + 0.2):
                ok = False
            if ok:
                return vx, vy
    return None


def gnd_fanout(bl, obs, vias):
    """Via to the plane next to every SMD ground pad: GND to In1, GND_MOT to the island (In1 + B.Cu)."""
    skip = ("NT1", "U11", "U12", "U4", "U6", "R406", "R606", "U10")
    n, miss = 0, []
    for ref, fp in bl.fps.items():
        if ref in skip:
            continue
        cx = pcbnew.ToMM(fp.GetPosition().x) - 150
        cy = 150 - pcbnew.ToMM(fp.GetPosition().y)
        for p in fp.Pads():
            net = p.GetNetname()
            if net not in ("GND", "GND_MOT") or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            x = pcbnew.ToMM(p.GetPosition().x) - 150
            y = 150 - pcbnew.ToMM(p.GetPosition().y)
            bb = p.GetBoundingBox()
            w = pcbnew.ToMM(bb.GetWidth()); h = pcbnew.ToMM(bb.GetHeight())
            if w > 2.6 and h > 2.6:          # exposed pads with their own thermal vias
                continue
            spot = via_spot(x, y, w, h, cx, cy, net, obs, vias)
            if spot is None:
                miss.append(f"{ref}.{p.GetNumber()}")
                continue
            bl.track(net, [(x, y), spot], min(0.3, w, h), F)
            bl.via(net, spot, 0.6, 0.3)
            vias.append(spot)
            n += 1
    if miss:
        print("no room for a ground via at:", " ".join(miss))
    return n


def apply(bl):
    import design
    # ground: solid In1 GND, GND fill on the other layers at the lowest priority, the GND_MOT island above them on
    # In1 and F.Cu (and B.Cu under the drivers); the GND_FILL zones are left out of the autorouter's DSN
    bl.zone("GND", IN1, BOARD_POLY, 0, 0.35, 0.25, thermal=True, name="GND_IN1", holes=[GND_MOT_ISLAND])
    for layer, nm in ((F, "F"), (B, "B"), (IN2, "In2")):
        bl.zone("GND", layer, BOARD_POLY, 0, 0.35, 0.3, thermal=True, name=f"GND_FILL_{nm}")
    bl.zone("GND_MOT", IN1, GND_MOT_ISLAND, 10, 0.35, 0.3, thermal=False, name="GND_MOT_In1")
    bl.zone("GND_MOT", F, GND_MOT_ISLAND, 10, 0.35, 0.3, thermal=False, name="GND_FILL_MOT_F")
    bl.zone("GND_MOT", B, GND_MOT_ISLAND, 9, 0.35, 0.3, thermal=False, name="GND_FILL_MOT_B")
    for i, poly in enumerate(GND_MOT_B):
        bl.zone("GND_MOT", B, poly, 10, 0.35, 0.3, thermal=False, name=f"GND_MOT_B_{i}")
    # one zone per connected piece of each net on each layer: overlapping zones of one net with different priorities
    # are filled apart (the lower one is knocked out with the zone clearance) and would not connect
    merged = {}
    for net, layers, poly, pri in POURS:
        for layer in layers:
            sp = pcbnew.SHAPE_POLY_SET()
            sp.NewOutline()
            for x, y in poly:
                sp.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
            if (net, layer) in merged:
                merged[(net, layer)].BooleanAdd(sp)
            else:
                merged[(net, layer)] = sp
    for i, ((net, layer), sp) in enumerate(merged.items()):
        for k in range(sp.OutlineCount()):
            if sp.HoleCount(k):
                raise SystemExit(f"pour {net} on {bl.b.GetLayerName(layer)} encloses a hole")
            ol = sp.Outline(k)
            pts = [(pcbnew.ToMM(ol.CPoint(j).x), pcbnew.ToMM(ol.CPoint(j).y)) for j in range(ol.PointCount())]
            bl.zone(net, layer, pts, 20 + i, 0.3, 0.3, thermal=False, name=f"{net}_{bl.b.GetLayerName(layer)}_{i}_{k}")
    for net, layer, w, pts in TRACKS:
        bl.track(net, pts, w, layer)
    vias = []
    for net, pts, d, drill in VIAS:
        for at in pts:
            bl.via(net, at, d, drill)
            vias.append(at)
    obs = obstacles(bl)
    print("GND fan-out vias", gnd_fanout(bl, obs, vias))
    total = 0
    for net, layers, poly, pri in POURS:
        if len(layers) > 1:
            total += stitch(bl, net, poly, obs, vias)
    total += stitch(bl, "GND_MOT", GND_MOT_ISLAND, obs, vias, pitch=4.0)
    # the cable cut-out is a hole in the board: keep everything (incl. the autorouter) out with a margin
    for poly in design.CUTOUTS:
        xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
        m = 0.35
        bl.keepout([(min(xs) - m, min(ys) - m), (max(xs) + m, min(ys) - m), (max(xs) + m, max(ys) + m),
                    (min(xs) - m, max(ys) + m)])
    for p in design.PARTS:
        if p["ref"].startswith("H"):
            x, y = p["at"]
            bl.keepout(circle(x, y, STANDOFF_KEEPOUT), ("F.Cu", "B.Cu"))
    for pad in bl.fps["MOD1"].Pads():
        x = pcbnew.ToMM(pad.GetPosition().x) - 150; y = 150 - pcbnew.ToMM(pad.GetPosition().y)
        bl.keepout(circle(x, y, 2.9), ("F.Cu", "B.Cu"))
    print("stitching vias", total)
