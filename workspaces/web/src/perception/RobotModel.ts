import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

export type RobotModel = {
    group: THREE.Group;
    wheels: { fl: THREE.Object3D; fr: THREE.Object3D; rl: THREE.Object3D; rr: THREE.Object3D };
    update: (state: { steering: number; travelled: number; time: number }) => void;
    dispose: () => void;
};

const CENTER_X = 0.06;
const FLOOR_Y = -0.137;

const WHEEL_RADIUS = 0.0375;
const WHEEL_WIDTH = 0.029;
const RIM_RADIUS = 0.026;
const TREAD_DEPTH = 0.0015;
const HALF_TRACK = 0.084;
const FRONT_AXLE = 0.013;
const REAR_AXLE = 0.1845;
const WHEEL_Y = FLOOR_Y + WHEEL_RADIUS;

const PLATE_THICKNESS = 0.002;
const BOTTOM_PLATE_TOP = FLOOR_Y + 0.0247;
const DECK_THICKNESS = 0.003;
const DECK_BOTTOM = FLOOR_Y + 0.0725;
const DECK_TOP = DECK_BOTTOM + DECK_THICKNESS;
const TOP_PLATE_TOP = FLOOR_Y + 0.1183;
const TOP_PLATE_BOTTOM = TOP_PLATE_TOP - PLATE_THICKNESS;

const PLATE_OUTLINE: [halfWidth: number, z: number][] = [
    [0.0266, -0.037],
    [0.0517, 0.0026],
    [0.0587, 0.0093],
    [0.0427, 0.0218],
    [0.0427, 0.0512],
    [0.0574, 0.0758],
    [0.0594, 0.2145],
    [0.048, 0.2329],
];

const SHELL_WIDTH = 0.1;
const SHELL_HEIGHT = 0.021;
const SHELL_LENGTH = 0.234;
const SHELL_BOTTOM = BOTTOM_PLATE_TOP;
const SHELL_Z = 0.105;
const SHELL_BACK = SHELL_Z + SHELL_LENGTH / 2;

const STANDOFFS: [x: number, z: number][] = [
    [-0.038, -0.0097],
    [0.038, -0.0097],
    [-0.038, 0.2198],
    [0.038, 0.2198],
];

const ZED_WIDTH = 0.175;
const ZED_HEIGHT = 0.03;
const ZED_DEPTH = 0.043;
const ZED_Y = 0.0002;
const ZED_Z = -0.0036;
const ZED_BOTTOM = ZED_Y - ZED_HEIGHT / 2;
const EYE_X = 0.06;

const JETSON_Y = FLOOR_Y + 0.031;
const JETSON_Z = 0.106;
const ROBOCLAW_Z = 0.186;
const BATTERY_Z = 0.153;
const V_MOUNT_HEIGHT = 0.018;
const BATTERY_HEIGHT = 0.062;

const plateShape = () =>
    new THREE.Shape([
        ...PLATE_OUTLINE.map(([w, z]) => new THREE.Vector2(w, z)),
        ...PLATE_OUTLINE.map(([w, z]) => new THREE.Vector2(-w, z)).reverse(),
    ]);

const roundedRectShape = (width: number, length: number, radius: number) => {
    const w = width / 2;
    const l = length / 2;
    const shape = new THREE.Shape();
    shape.moveTo(-w + radius, -l);
    shape.lineTo(w - radius, -l);
    shape.quadraticCurveTo(w, -l, w, -l + radius);
    shape.lineTo(w, l - radius);
    shape.quadraticCurveTo(w, l, w - radius, l);
    shape.lineTo(-w + radius, l);
    shape.quadraticCurveTo(-w, l, -w, l - radius);
    shape.lineTo(-w, -l + radius);
    shape.quadraticCurveTo(-w, -l, -w + radius, -l);
    return shape;
};

const heartShape = (size: number) => {
    const s = size / 2;
    const shape = new THREE.Shape();
    shape.moveTo(0, -s);
    shape.bezierCurveTo(-s * 0.3, -s * 0.55, -s, -s * 0.15, -s, s * 0.3);
    shape.bezierCurveTo(-s, s * 0.85, -s * 0.25, s * 0.95, 0, s * 0.45);
    shape.bezierCurveTo(s * 0.25, s * 0.95, s, s * 0.85, s, s * 0.3);
    shape.bezierCurveTo(s, -s * 0.15, s * 0.3, -s * 0.55, 0, -s);
    return shape;
};

const tireProfile = () => {
    const r = WHEEL_RADIUS - TREAD_DEPTH;
    const h = WHEEL_WIDTH / 2;
    const corner = 0.006;
    const points = [new THREE.Vector2(RIM_RADIUS, -h), new THREE.Vector2(r - corner, -h)];
    for (let i = 1; i <= 4; i++) {
        const a = -Math.PI / 2 + (i / 4) * (Math.PI / 2);
        points.push(new THREE.Vector2(r - corner + Math.cos(a) * corner, -h + corner + Math.sin(a) * corner));
    }
    for (let i = 0; i <= 4; i++) {
        const a = (i / 4) * (Math.PI / 2);
        points.push(new THREE.Vector2(r - corner + Math.cos(a) * corner, h - corner + Math.sin(a) * corner));
    }
    points.push(new THREE.Vector2(RIM_RADIUS, h), new THREE.Vector2(RIM_RADIUS, -h));
    return points;
};

const blinkAmount = (time: number) => {
    const period = 4.6;
    const duration = 0.16;
    const phase = time % period;
    const double = (time / period) % 3 < 1 ? phase - duration * 1.4 : -1;
    const pulse = (p: number) => (p >= 0 && p < duration ? Math.sin((p / duration) * Math.PI) : 0);
    return Math.max(pulse(phase), pulse(double));
};

const twitchAmount = (time: number, period: number) => {
    const phase = time % period;
    const duration = 0.4;
    return phase < duration ? Math.sin((phase / duration) * Math.PI * 3) * (1 - phase / duration) : 0;
};

export const createRobotModel = (): RobotModel => {
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];
    const geo = <T extends THREE.BufferGeometry>(g: T): T => {
        geometries.push(g);
        return g;
    };
    const merge = (parts: THREE.BufferGeometry[]) => {
        const merged = mergeGeometries(parts);
        for (const part of parts) {
            part.dispose();
        }
        if (merged == null) {
            throw new Error('Failed to merge robot geometries');
        }
        return geo(merged);
    };
    const mat = <T extends THREE.Material>(m: T): T => {
        materials.push(m);
        return m;
    };

    const shellMat = mat(
        new THREE.MeshPhysicalMaterial({ color: 0xfff4fa, roughness: 0.45, clearcoat: 0.6, clearcoatRoughness: 0.35 }),
    );
    const pinkMat = mat(new THREE.MeshPhysicalMaterial({ color: 0xffa8cc, roughness: 0.5, clearcoat: 0.4 }));
    const lavenderMat = mat(new THREE.MeshPhysicalMaterial({ color: 0xc6b5ff, roughness: 0.45, clearcoat: 0.5 }));
    const mintMat = mat(new THREE.MeshStandardMaterial({ color: 0x8ee8c4, roughness: 0.6 }));
    const plateMat = mat(new THREE.MeshStandardMaterial({ color: 0x2b2d36, roughness: 0.55, metalness: 0.2 }));
    const deckMat = mat(
        new THREE.MeshPhysicalMaterial({
            color: 0xe9e2ff,
            roughness: 0.15,
            clearcoat: 1,
            transparent: true,
            opacity: 0.35,
            depthWrite: false,
        }),
    );
    const brassMat = mat(new THREE.MeshStandardMaterial({ color: 0xe8c77a, roughness: 0.35, metalness: 0.6 }));
    const zedMat = mat(new THREE.MeshStandardMaterial({ color: 0x40444f, roughness: 0.42, metalness: 0.35 }));
    const heatsinkMat = mat(new THREE.MeshStandardMaterial({ color: 0x5a6070, roughness: 0.35, metalness: 0.7 }));
    const tireMat = mat(new THREE.MeshStandardMaterial({ color: 0x26272e, roughness: 0.92 }));
    const whiteMat = mat(new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.4 }));
    const lensMat = mat(new THREE.MeshPhysicalMaterial({ color: 0x07080c, roughness: 0.12, metalness: 0.2, clearcoat: 1 }));
    const sparkleMat = mat(new THREE.MeshBasicMaterial({ color: 0xffffff }));
    const blushMat = mat(
        new THREE.MeshStandardMaterial({ color: 0xff8fb8, emissive: 0xff6fa3, emissiveIntensity: 0.35, roughness: 0.8 }),
    );
    const mouthMat = mat(new THREE.MeshStandardMaterial({ color: 0x5a3a4a, roughness: 0.6 }));
    const ledMat = mat(new THREE.MeshBasicMaterial({ color: 0x00ff41 }));
    const tailLightMat = mat(new THREE.MeshBasicMaterial({ color: 0xff7aa8 }));
    const furMat = mat(
        new THREE.MeshPhysicalMaterial({
            color: 0xffffff,
            roughness: 0.95,
            sheen: 1,
            sheenColor: new THREE.Color(0xffd3e6),
            sheenRoughness: 0.4,
        }),
    );

    const sphereGeo = geo(new THREE.SphereGeometry(1, 16, 10));
    const beadGeo = geo(new THREE.SphereGeometry(1, 10, 6));
    const discGeo = geo(new THREE.CylinderGeometry(1, 1, 1, 24).rotateX(Math.PI / 2));

    const group = new THREE.Group();
    group.name = 'rabbit';

    const add = (parent: THREE.Object3D, geometry: THREE.BufferGeometry, material: THREE.Material) => {
        const mesh = new THREE.Mesh(geometry, material);
        parent.add(mesh);
        return mesh;
    };

    const plateGeo = geo(
        new THREE.ExtrudeGeometry(plateShape(), { depth: PLATE_THICKNESS, bevelEnabled: false }).rotateX(Math.PI / 2),
    );
    const bottomPlate = add(group, plateGeo, plateMat);
    bottomPlate.position.set(CENTER_X, BOTTOM_PLATE_TOP, 0);
    const topPlate = add(group, plateGeo, plateMat);
    topPlate.position.set(CENTER_X, TOP_PLATE_TOP, 0);

    const deck = add(
        group,
        geo(new THREE.ExtrudeGeometry(plateShape(), { depth: DECK_THICKNESS, bevelEnabled: false }).rotateX(Math.PI / 2)),
        deckMat,
    );
    deck.position.set(CENTER_X, DECK_TOP, 0);

    const standoffGeo = geo(
        new THREE.CylinderGeometry(0.0033, 0.0033, TOP_PLATE_BOTTOM - BOTTOM_PLATE_TOP, 6).translate(
            0,
            (TOP_PLATE_BOTTOM - BOTTOM_PLATE_TOP) / 2,
            0,
        ),
    );
    for (const [x, z] of STANDOFFS) {
        const standoff = add(group, standoffGeo, brassMat);
        standoff.position.set(CENTER_X + x, BOTTOM_PLATE_TOP, z);
    }

    const shell = add(group, geo(new RoundedBoxGeometry(SHELL_WIDTH, SHELL_HEIGHT, SHELL_LENGTH, 4, 0.009)), shellMat);
    shell.position.set(CENTER_X, SHELL_BOTTOM + SHELL_HEIGHT / 2, SHELL_Z);

    const beltGeo = geo(
        new THREE.ExtrudeGeometry(roundedRectShape(SHELL_WIDTH + 0.004, SHELL_LENGTH + 0.004, 0.011), {
            depth: 0.004,
            bevelEnabled: false,
            curveSegments: 6,
        }).rotateX(Math.PI / 2),
    );
    const belt = add(group, beltGeo, pinkMat);
    belt.position.set(CENTER_X, SHELL_BOTTOM + SHELL_HEIGHT / 2 + 0.002, SHELL_Z);

    for (const side of [-1, 1]) {
        const tailLight = add(group, discGeo, tailLightMat);
        tailLight.scale.set(0.006, 0.006, 0.002);
        tailLight.position.set(CENTER_X + side * 0.03, SHELL_BOTTOM + SHELL_HEIGHT / 2, SHELL_BACK + 0.0005);
    }

    const zed = new THREE.Group();
    zed.name = 'zed';
    zed.position.set(CENTER_X, ZED_Y, ZED_Z);
    group.add(zed);

    const zedFront = -ZED_DEPTH / 2;
    const zedMountGeo = geo(new THREE.BoxGeometry(0.014, ZED_BOTTOM - TOP_PLATE_TOP, 0.014));
    for (const side of [-1, 1]) {
        const zedMount = add(zed, zedMountGeo, plateMat);
        zedMount.position.set(side * 0.03, (TOP_PLATE_TOP + ZED_BOTTOM) / 2 - ZED_Y, 0);
    }

    add(zed, geo(new RoundedBoxGeometry(ZED_WIDTH, ZED_HEIGHT, ZED_DEPTH, 4, 0.012)), zedMat);

    const zedLed = add(zed, beadGeo, ledMat);
    zedLed.scale.setScalar(0.0018);
    zedLed.position.set(0, ZED_HEIGHT / 2 - 0.006, zedFront - 0.0002);

    for (const side of [-1, 1]) {
        const cheek = add(zed, beadGeo, blushMat);
        cheek.scale.set(0.0065, 0.0035, 0.002);
        cheek.position.set(side * 0.08, -0.0095, zedFront - 0.0005);

        const mouthHalf = add(zed, geo(new THREE.TorusGeometry(0.0045, 0.0011, 6, 12, Math.PI)), mouthMat);
        mouthHalf.rotation.z = Math.PI;
        mouthHalf.position.set(side * 0.0045, -0.005, zedFront - 0.0005);
    }

    const eyeRingGeo = geo(new THREE.TorusGeometry(0.0118, 0.0018, 8, 28));
    const eyes: THREE.Group[] = [];
    for (const side of [-1, 1]) {
        const eye = new THREE.Group();
        eye.position.set(side * EYE_X, -ZED_Y, zedFront);
        zed.add(eye);
        eyes.push(eye);

        add(eye, eyeRingGeo, mintMat);
        const lens = add(eye, discGeo, lensMat);
        lens.scale.set(0.0105, 0.0105, 0.004);

        const sparkle = add(eye, beadGeo, sparkleMat);
        sparkle.scale.setScalar(0.0032);
        sparkle.position.set(-0.0038, 0.0038, -0.0022);
        const sparkleSmall = add(eye, beadGeo, sparkleMat);
        sparkleSmall.scale.setScalar(0.0015);
        sparkleSmall.position.set(0.0042, -0.004, -0.0022);
    }

    const earOuterScale = new THREE.Vector3(0.017, 0.026, 0.008);
    const earInnerScale = new THREE.Vector3(0.0098, 0.019, 0.0037);
    const buildEarSegment = (parent: THREE.Object3D, length: number) => {
        const outer = add(parent, sphereGeo, shellMat);
        outer.scale.copy(earOuterScale).setY(length / 2 + 0.004);
        outer.position.y = length / 2;
        const inner = add(parent, sphereGeo, pinkMat);
        inner.scale.copy(earInnerScale).setY(length / 2 - 0.003);
        inner.position.set(0, length / 2 + 0.0015, -0.0052);
    };

    const ears = [-1, 1].map((side) => {
        const base = new THREE.Group();
        base.position.set(side * 0.035, ZED_HEIGHT / 2 - 0.002, 0.004);
        zed.add(base);
        const root = add(base, beadGeo, shellMat);
        root.scale.set(0.015, 0.009, 0.011);

        const lower = new THREE.Group();
        base.add(lower);
        buildEarSegment(lower, 0.075);

        const tip = new THREE.Group();
        tip.position.y = 0.068;
        lower.add(tip);
        buildEarSegment(tip, 0.068);

        const floppy = side < 0;
        return { side, base, tip, floppy, tilt: -side * 0.24, fold: floppy ? -1.05 : 0.12, phase: side * 1.7 };
    });

    const jetson = new THREE.Group();
    jetson.name = 'jetson';
    jetson.position.set(CENTER_X - 0.005, JETSON_Y, JETSON_Z);
    group.add(jetson);
    const board = add(jetson, geo(new THREE.BoxGeometry(0.079, 0.0016, 0.1)), mintMat);
    board.position.y = 0.0008;
    const heatsinkGeo = merge([
        new THREE.BoxGeometry(0.06, 0.004, 0.05).translate(0, 0.002, 0),
        ...Array.from({ length: 9 }, (_, i) =>
            new THREE.BoxGeometry(0.0024, 0.02, 0.05).translate(-0.027 + i * 0.00675, 0.014, 0),
        ),
    ]);
    const heatsink = add(jetson, heatsinkGeo, heatsinkMat);
    heatsink.position.y = 0.004;
    const fanY = 0.03;
    const fanHousing = add(jetson, geo(new THREE.TorusGeometry(0.018, 0.0024, 8, 28).rotateX(Math.PI / 2)), lavenderMat);
    fanHousing.position.y = fanY;
    const fanBladesGeo = merge(
        Array.from({ length: 5 }, (_, i) =>
            new THREE.BoxGeometry(0.006, 0.0012, 0.015)
                .rotateZ(0.35)
                .translate(0, 0, 0.0085)
                .rotateY((i / 5) * Math.PI * 2),
        ),
    );
    const fan = new THREE.Group();
    fan.position.y = fanY;
    jetson.add(fan);
    add(fan, fanBladesGeo, whiteMat);
    const fanHub = add(fan, discGeo, pinkMat);
    fanHub.scale.set(0.005, 0.005, 0.004);
    fanHub.rotation.x = Math.PI / 2;

    const roboclaw = new THREE.Group();
    roboclaw.name = 'roboclaw';
    roboclaw.position.set(CENTER_X, DECK_TOP + 0.009, ROBOCLAW_Z);
    group.add(roboclaw);
    const roboclawStandoffGeo = geo(new THREE.CylinderGeometry(0.0025, 0.0025, 0.009, 6).translate(0, -0.0045, 0));
    for (const x of [-0.03, 0.03]) {
        for (const z of [-0.034, 0.034]) {
            const post = add(roboclaw, roboclawStandoffGeo, brassMat);
            post.position.set(x, 0, z);
        }
    }
    const roboclawBoard = add(roboclaw, geo(new RoundedBoxGeometry(0.0667, 0.0016, 0.0737, 2, 0.0008)), lavenderMat);
    roboclawBoard.position.y = 0.0008;
    const roboclawHeatsink = add(
        roboclaw,
        merge([
            new THREE.BoxGeometry(0.046, 0.003, 0.03).translate(0, 0.0015, 0),
            ...Array.from({ length: 7 }, (_, i) =>
                new THREE.BoxGeometry(0.003, 0.012, 0.03).translate(-0.0205 + i * 0.0068, 0.009, 0),
            ),
        ]),
        heatsinkMat,
    );
    roboclawHeatsink.position.set(0, 0.0016, -0.012);
    const terminalGeo = geo(new THREE.BoxGeometry(0.03, 0.008, 0.008));
    for (const side of [-1, 1]) {
        const terminal = add(roboclaw, terminalGeo, mintMat);
        terminal.position.set(side * 0.017, 0.0056, 0.028);
    }

    const battery = new THREE.Group();
    battery.name = 'battery';
    battery.position.set(CENTER_X, TOP_PLATE_TOP, BATTERY_Z);
    group.add(battery);
    const vMount = add(battery, geo(new RoundedBoxGeometry(0.09, V_MOUNT_HEIGHT, 0.13, 2, 0.004)), plateMat);
    vMount.position.y = V_MOUNT_HEIGHT / 2;
    const batteryBody = add(battery, geo(new RoundedBoxGeometry(0.086, BATTERY_HEIGHT, 0.115, 4, 0.01)), lavenderMat);
    batteryBody.position.y = V_MOUNT_HEIGHT + BATTERY_HEIGHT / 2;
    const heart = add(
        battery,
        geo(
            new THREE.ExtrudeGeometry(heartShape(0.03), { depth: 0.002, bevelEnabled: false, curveSegments: 8 }).rotateX(
                -Math.PI / 2,
            ),
        ),
        pinkMat,
    );
    heart.position.set(0, V_MOUNT_HEIGHT + BATTERY_HEIGHT, -0.01);
    const ledGeo = geo(new THREE.BoxGeometry(0.008, 0.002, 0.004));
    for (let i = 0; i < 4; i++) {
        const led = add(battery, ledGeo, ledMat);
        led.position.set(-0.018 + i * 0.012, V_MOUNT_HEIGHT + BATTERY_HEIGHT, 0.035);
    }

    const tail = new THREE.Group();
    tail.position.set(CENTER_X, SHELL_BOTTOM + SHELL_HEIGHT / 2 + 0.004, SHELL_BACK + 0.01);
    group.add(tail);
    const tailCore = add(tail, sphereGeo, furMat);
    tailCore.scale.setScalar(0.017);
    for (let i = 0; i < 7; i++) {
        const a = (i / 7) * Math.PI * 2;
        const puff = add(tail, beadGeo, furMat);
        puff.scale.setScalar(0.0085 + (i % 3) * 0.0012);
        puff.position.set(Math.cos(a) * 0.012, Math.sin(a) * 0.012, 0.004 + (i % 2) * 0.003);
    }

    const tireGeo = geo(new THREE.LatheGeometry(tireProfile(), 28).rotateZ(Math.PI / 2));
    const treadGeo = merge(
        Array.from({ length: 22 }, (_, i) =>
            new THREE.BoxGeometry(0.012, TREAD_DEPTH * 2, 0.007)
                .translate((i % 2 ? 1 : -1) * 0.006, WHEEL_RADIUS - TREAD_DEPTH, 0)
                .rotateX((i / 22) * Math.PI * 2),
        ),
    );
    const hubGeo = geo(new THREE.CylinderGeometry(RIM_RADIUS, RIM_RADIUS, WHEEL_WIDTH - 0.004, 28).rotateZ(Math.PI / 2));
    const spokesGeo = merge(
        [-1, 1].flatMap((side) =>
            Array.from({ length: 5 }, (_, i) =>
                new THREE.BoxGeometry(0.002, 0.0052, 0.023)
                    .translate(side * (WHEEL_WIDTH / 2 - 0.0015), 0, 0.0125)
                    .rotateX((i / 5) * Math.PI * 2),
            ),
        ),
    );
    const capGeo = geo(new THREE.CylinderGeometry(0.0075, 0.0075, WHEEL_WIDTH + 0.002, 16).rotateZ(Math.PI / 2));

    const spinners: THREE.Group[] = [];
    const createWheel = (side: number, z: number) => {
        const pivot = new THREE.Group();
        pivot.position.set(CENTER_X + side * HALF_TRACK, WHEEL_Y, z);
        group.add(pivot);
        const spin = new THREE.Group();
        pivot.add(spin);
        add(spin, tireGeo, tireMat);
        add(spin, treadGeo, tireMat);
        add(spin, hubGeo, pinkMat);
        add(spin, spokesGeo, whiteMat);
        add(spin, capGeo, lavenderMat);
        spinners.push(spin);
        return pivot;
    };

    const wheels = {
        fl: createWheel(-1, FRONT_AXLE),
        fr: createWheel(1, FRONT_AXLE),
        rl: createWheel(-1, REAR_AXLE),
        rr: createWheel(1, REAR_AXLE),
    };

    const update: RobotModel['update'] = ({ steering, travelled, time }) => {
        wheels.fl.rotation.y = steering;
        wheels.fr.rotation.y = steering;
        for (const spin of spinners) {
            spin.rotation.x = -travelled / WHEEL_RADIUS;
        }

        const lean = THREE.MathUtils.clamp(-steering * 0.5, -0.35, 0.35);
        for (const ear of ears) {
            const twitch = ear.floppy ? 0 : twitchAmount(time + ear.phase, 5.3) * 0.2;
            ear.base.rotation.set(
                0.28 + Math.sin(time * 1.9 + ear.phase) * 0.04,
                0,
                ear.tilt + lean + Math.sin(time * 2.3 + ear.phase) * 0.05 + twitch,
            );
            ear.tip.rotation.x = ear.fold + Math.sin(time * 3.1 + ear.phase) * (ear.floppy ? 0.14 : 0.05);
            ear.tip.rotation.z = lean * 0.6;
        }

        const blink = 1 - blinkAmount(time) * 0.88;
        for (const eye of eyes) {
            eye.scale.y = blink;
        }

        fan.rotation.y = time * 14;
        tail.rotation.set(Math.sin(time * 2.6) * 0.08, Math.sin(time * 5.2) * 0.18, 0);
        tail.scale.setScalar(1 + Math.sin(time * 2.6) * 0.04);
    };

    update({ steering: 0, travelled: 0, time: 0 });

    const dispose = () => {
        for (const g of geometries) {
            g.dispose();
        }
        for (const m of materials) {
            m.dispose();
        }
    };

    return { group, wheels, update, dispose };
};
