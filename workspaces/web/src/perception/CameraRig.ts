import * as THREE from 'three';

export const VIEW_MODES = [
    { id: 'fpv', label: 'FPV' },
    { id: 'third', label: '3RD' },
    { id: 'top', label: 'TOP' },
    { id: 'free', label: 'FREE' },
] as const;

export type ViewMode = (typeof VIEW_MODES)[number]['id'];

export const TOP_ORIENTATIONS = [
    { id: 'heading', label: 'HDG UP' },
    { id: 'north', label: 'N UP' },
] as const;

export type TopOrientation = (typeof TOP_ORIENTATIONS)[number]['id'];

type RobotFrame = { center: THREE.Vector3; eye: THREE.Vector3; forward: THREE.Vector3 };

export type CameraRig = {
    setMode: (mode: ViewMode) => void;
    setTopOrientation: (orientation: TopOrientation) => void;
    update: (dt: number, now: number, robot: RobotFrame) => void;
    dispose: () => void;
};

type Options = {
    camera: THREE.PerspectiveCamera;
    element: HTMLElement;
    pick: (ndc: THREE.Vector2) => THREE.Vector3 | null;
    onModeChange: (mode: ViewMode) => void;
    onClick: (ndc: THREE.Vector2, append: boolean) => void;
};

const WORLD_UP = new THREE.Vector3(0, 1, 0);
const NORTH = new THREE.Vector3(0, 0, -1);

const RETURN_DELAY_MS = 1400;
const RETURN_RATE = 2.2;
const INPUT_RATE = 16;
const FOLLOW_RATE = 9;
const CHASE_YAW_RATE = 2.6;
const HEADING_UP_RATE = 3.5;
const FPV_RATE = 22;
const TRANSITION_MS = 750;
const ROTATE_PER_PX = 0.0065;
const ZOOM_PER_DELTA = 0.0015;
const BASE_FOV = 55;
const CLICK_SLOP_PX = 5;
const CLICK_MS = 400;

const CHASE_ELEVATION = 0.36;
const CHASE_LOOK_HEIGHT = 0.05;
const FPV_YAW_LIMIT = 2.4;
const FPV_PITCH_LIMIT = 1.2;
const MIN_ELEVATION = -0.08;
const MAX_ELEVATION = 1.5;

const clamp = THREE.MathUtils.clamp;
const ease = (rate: number, dt: number) => 1 - Math.exp(-rate * dt);
const wrapAngle = (a: number) => a - Math.round(a / (2 * Math.PI)) * 2 * Math.PI;
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

const setOrbit = (out: THREE.Vector3, azimuth: number, elevation: number, distance: number) =>
    out.set(
        Math.sin(azimuth) * Math.cos(elevation) * distance,
        Math.sin(elevation) * distance,
        Math.cos(azimuth) * Math.cos(elevation) * distance,
    );

export const createCameraRig = ({ camera, element, pick, onModeChange, onClick }: Options): CameraRig => {
    let mode: ViewMode = 'third';
    let topOrientation: TopOrientation = 'heading';

    const follow = new THREE.Vector3();
    const eye = new THREE.Vector3();
    let chaseAzimuth = 0;
    let headingAzimuth = 0;
    let fpvAzimuth = 0;
    let fpvPitch = 0;
    let initialized = false;

    const look = { yaw: 0, pitch: 0, yawTarget: 0, pitchTarget: 0 };
    const pan = new THREE.Vector3();
    const panTarget = new THREE.Vector3();
    const zoom = { third: 0.95, thirdTarget: 0.95, top: 3.2, topTarget: 3.2, fov: BASE_FOV, fovTarget: BASE_FOV };
    const free = { azimuth: 0, elevation: 0.5, distance: 3, azimuthTarget: 0, elevationTarget: 0.5, distanceTarget: 3 };
    const pivot = new THREE.Vector3();
    const pivotTarget = new THREE.Vector3();

    let drag: {
        id: number;
        x: number;
        y: number;
        moved: number;
        button: number;
        startedAt: number;
        action: 'rotate' | 'pan';
    } | null = null;
    let lastInput = -Infinity;

    let transitionStart = -Infinity;
    const fromPosition = new THREE.Vector3();
    const fromQuaternion = new THREE.Quaternion();

    const position = new THREE.Vector3();
    const target = new THREE.Vector3();
    const up = new THREE.Vector3();
    const offset = new THREE.Vector3();
    const right = new THREE.Vector3();
    const screenUp = new THREE.Vector3();
    const quaternion = new THREE.Quaternion();
    const matrix = new THREE.Matrix4();
    const ndc = new THREE.Vector2();

    const startTransition = () => {
        fromPosition.copy(camera.position);
        fromQuaternion.copy(camera.quaternion);
        transitionStart = performance.now();
    };

    const enterFree = () => {
        camera.getWorldDirection(offset);
        const distance = clamp(camera.position.distanceTo(target), 0.4, 30);
        pivot.copy(camera.position).addScaledVector(offset, distance);
        pivotTarget.copy(pivot);
        offset.copy(camera.position).sub(pivot);
        free.azimuth = free.azimuthTarget = Math.atan2(offset.x, offset.z);
        free.elevation = free.elevationTarget = clamp(
            Math.asin(clamp(offset.y / distance, -1, 1)),
            MIN_ELEVATION,
            MAX_ELEVATION,
        );
        free.distance = free.distanceTarget = distance;
    };

    const setMode = (next: ViewMode) => {
        if (next === mode) return;
        if (next === 'free') enterFree();
        mode = next;
        look.yaw = look.yawTarget = look.pitch = look.pitchTarget = 0;
        pan.set(0, 0, 0);
        panTarget.set(0, 0, 0);
        drag = null;
        startTransition();
    };

    const worldPerPixel = (distance: number) =>
        (2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / Math.max(element.clientHeight, 1);

    const panBy = (dx: number, dy: number, distance: number, into: THREE.Vector3) => {
        const scale = worldPerPixel(distance);
        right.setFromMatrixColumn(camera.matrixWorld, 0);
        screenUp.setFromMatrixColumn(camera.matrixWorld, 1);
        if (mode === 'top') {
            right.y = 0;
            screenUp.y = 0;
            right.normalize();
            screenUp.normalize();
        }
        into.addScaledVector(right, -dx * scale).addScaledVector(screenUp, dy * scale);
    };

    const rotateBy = (dx: number, dy: number) => {
        if (mode === 'free') {
            free.azimuthTarget -= dx * ROTATE_PER_PX;
            free.elevationTarget = clamp(free.elevationTarget + dy * ROTATE_PER_PX, MIN_ELEVATION, MAX_ELEVATION);
            return;
        }
        if (mode === 'fpv') {
            look.yawTarget = clamp(look.yawTarget - dx * ROTATE_PER_PX * 0.6, -FPV_YAW_LIMIT, FPV_YAW_LIMIT);
            look.pitchTarget = clamp(look.pitchTarget - dy * ROTATE_PER_PX * 0.6, -FPV_PITCH_LIMIT, FPV_PITCH_LIMIT);
            return;
        }
        look.yawTarget -= dx * ROTATE_PER_PX;
        const wrapped = wrapAngle(look.yawTarget);
        look.yaw += wrapped - look.yawTarget;
        look.yawTarget = wrapped;
        look.pitchTarget = clamp(
            look.pitchTarget + dy * ROTATE_PER_PX,
            MIN_ELEVATION - CHASE_ELEVATION,
            MAX_ELEVATION - CHASE_ELEVATION,
        );
    };

    const onPointerDown = (event: PointerEvent) => {
        if (drag != null) return;
        const secondary = event.button === 1 || event.button === 2 || event.shiftKey;
        const action = mode === 'top' ? (secondary ? 'rotate' : 'pan') : mode === 'free' && secondary ? 'pan' : 'rotate';
        if (mode === 'top' && action === 'rotate') return;
        drag = {
            id: event.pointerId,
            x: event.clientX,
            y: event.clientY,
            moved: 0,
            button: event.button,
            startedAt: performance.now(),
            action,
        };
        try {
            element.setPointerCapture(event.pointerId);
        } catch {}
        element.style.cursor = 'grabbing';
        lastInput = performance.now();
    };

    const onPointerMove = (event: PointerEvent) => {
        if (drag == null || event.pointerId !== drag.id) return;
        const dx = event.clientX - drag.x;
        const dy = event.clientY - drag.y;
        drag.x = event.clientX;
        drag.y = event.clientY;
        drag.moved += Math.abs(dx) + Math.abs(dy);
        lastInput = performance.now();
        if (drag.action === 'rotate') {
            rotateBy(dx, dy);
        } else if (mode === 'top') {
            panBy(dx, dy, zoom.top, panTarget);
        } else {
            panBy(dx, dy, free.distance, pivotTarget);
        }
    };

    const onPointerUp = (event: PointerEvent) => {
        if (drag == null || event.pointerId !== drag.id) return;
        const click =
            event.type === 'pointerup' &&
            drag.button === 0 &&
            drag.moved < CLICK_SLOP_PX &&
            performance.now() - drag.startedAt < CLICK_MS;
        drag = null;
        try {
            element.releasePointerCapture(event.pointerId);
        } catch {}
        if (click) onClick(toNdc(event), event.shiftKey);
        element.style.cursor = '';
        lastInput = performance.now();
    };

    const onWheel = (event: WheelEvent) => {
        event.preventDefault();
        const delta = event.deltaMode === 1 ? event.deltaY * 33 : event.deltaY;
        const factor = Math.exp(clamp(delta, -200, 200) * ZOOM_PER_DELTA);
        if (mode === 'third') zoom.thirdTarget = clamp(zoom.thirdTarget * factor, 0.35, 8);
        if (mode === 'top') zoom.topTarget = clamp(zoom.topTarget * factor, 0.6, 40);
        if (mode === 'free') free.distanceTarget = clamp(free.distanceTarget * factor, 0.15, 60);
        if (mode === 'fpv') zoom.fovTarget = clamp(zoom.fovTarget * factor, 20, 100);
        lastInput = performance.now();
    };

    const toNdc = (event: MouseEvent) => {
        const rect = element.getBoundingClientRect();
        return ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    };

    const onDoubleClick = (event: MouseEvent) => {
        const point = pick(toNdc(event));
        if (point == null) return;
        if (mode !== 'free') {
            setMode('free');
            onModeChange('free');
        }
        pivotTarget.copy(point);
        free.distanceTarget = clamp(free.distanceTarget, 0.4, 4);
    };

    const onContextMenu = (event: Event) => event.preventDefault();

    element.addEventListener('pointerdown', onPointerDown);
    element.addEventListener('pointermove', onPointerMove);
    element.addEventListener('pointerup', onPointerUp);
    element.addEventListener('pointercancel', onPointerUp);
    element.addEventListener('wheel', onWheel, { passive: false });
    element.addEventListener('dblclick', onDoubleClick);
    element.addEventListener('contextmenu', onContextMenu);

    const trackRobot = (dt: number, robot: RobotFrame) => {
        const forward = robot.forward;
        const horizontal = Math.hypot(forward.x, forward.z);
        const azimuth = horizontal > 0.05 ? Math.atan2(-forward.x, -forward.z) : chaseAzimuth;
        const pitch = Math.asin(clamp(forward.y, -1, 1));

        if (!initialized) {
            follow.copy(robot.center);
            eye.copy(robot.eye);
            chaseAzimuth = headingAzimuth = fpvAzimuth = azimuth;
            fpvPitch = pitch;
            initialized = true;
            return;
        }

        if (follow.distanceToSquared(robot.center) > 4) follow.copy(robot.center);
        follow.lerp(robot.center, ease(FOLLOW_RATE, dt));
        eye.lerp(robot.eye, ease(FPV_RATE, dt));
        if (eye.distanceToSquared(robot.eye) > 1) eye.copy(robot.eye);
        chaseAzimuth += wrapAngle(azimuth - chaseAzimuth) * ease(CHASE_YAW_RATE, dt);
        headingAzimuth += wrapAngle(azimuth - headingAzimuth) * ease(HEADING_UP_RATE, dt);
        fpvAzimuth += wrapAngle(azimuth - fpvAzimuth) * ease(FPV_RATE, dt);
        fpvPitch += (pitch - fpvPitch) * ease(FPV_RATE, dt);
    };

    const easeInputs = (dt: number, now: number) => {
        if (drag == null && now - lastInput > RETURN_DELAY_MS && mode !== 'free') {
            const decay = Math.exp(-RETURN_RATE * dt);
            look.yawTarget *= decay;
            look.pitchTarget *= decay;
            panTarget.multiplyScalar(decay);
        }
        const k = ease(INPUT_RATE, dt);
        look.yaw += (look.yawTarget - look.yaw) * k;
        look.pitch += (look.pitchTarget - look.pitch) * k;
        pan.lerp(panTarget, k);
        zoom.third += (zoom.thirdTarget - zoom.third) * k;
        zoom.top += (zoom.topTarget - zoom.top) * k;
        zoom.fov += (zoom.fovTarget - zoom.fov) * k;
        free.azimuth += (free.azimuthTarget - free.azimuth) * k;
        free.elevation += (free.elevationTarget - free.elevation) * k;
        free.distance += (free.distanceTarget - free.distance) * k;
        pivot.lerp(pivotTarget, ease(INPUT_RATE * 0.5, dt));
    };

    const solve = () => {
        up.copy(WORLD_UP);
        if (mode === 'third') {
            target.copy(follow).y += CHASE_LOOK_HEIGHT;
            const elevation = clamp(CHASE_ELEVATION + look.pitch, MIN_ELEVATION, MAX_ELEVATION);
            position.copy(target).add(setOrbit(offset, chaseAzimuth + look.yaw, elevation, zoom.third));
        } else if (mode === 'fpv') {
            position.copy(eye);
            const azimuth = fpvAzimuth + look.yaw;
            const pitch = clamp(fpvPitch + look.pitch, -1.45, 1.45);
            target.copy(position).sub(setOrbit(offset, azimuth, -pitch, 1));
        } else if (mode === 'top') {
            target.copy(follow).add(pan);
            position.copy(target).y += zoom.top;
            if (topOrientation === 'north') {
                up.copy(NORTH);
            } else {
                up.set(-Math.sin(headingAzimuth), 0, -Math.cos(headingAzimuth));
            }
        } else {
            target.copy(pivot);
            position.copy(pivot).add(setOrbit(offset, free.azimuth, free.elevation, free.distance));
        }
        matrix.lookAt(position, target, up);
        quaternion.setFromRotationMatrix(matrix);
    };

    const update = (dt: number, now: number, robot: RobotFrame) => {
        trackRobot(dt, robot);
        easeInputs(dt, now);
        solve();

        const progress = (now - transitionStart) / TRANSITION_MS;
        if (progress < 1) {
            const t = easeInOut(clamp(progress, 0, 1));
            camera.position.lerpVectors(fromPosition, position, t);
            camera.quaternion.slerpQuaternions(fromQuaternion, quaternion, t);
        } else {
            camera.position.copy(position);
            camera.quaternion.copy(quaternion);
        }

        const fov = mode === 'fpv' ? zoom.fov : BASE_FOV;
        const nextFov = camera.fov + (fov - camera.fov) * ease(8, dt);
        if (Math.abs(nextFov - camera.fov) > 0.001) {
            camera.fov = nextFov;
            camera.updateProjectionMatrix();
        }
    };

    camera.fov = BASE_FOV;
    camera.updateProjectionMatrix();

    return {
        setMode,
        setTopOrientation: (orientation) => {
            topOrientation = orientation;
        },
        update,
        dispose: () => {
            element.removeEventListener('pointerdown', onPointerDown);
            element.removeEventListener('pointermove', onPointerMove);
            element.removeEventListener('pointerup', onPointerUp);
            element.removeEventListener('pointercancel', onPointerUp);
            element.removeEventListener('wheel', onWheel);
            element.removeEventListener('dblclick', onDoubleClick);
            element.removeEventListener('contextmenu', onContextMenu);
            element.style.cursor = '';
        },
    };
};
