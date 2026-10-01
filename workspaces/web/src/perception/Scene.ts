import type { NatsConnection } from '@nats-io/nats-core';
import * as THREE from 'three';

import type { LinkState } from '../app/NatsProvider.tsx';
import type { HudEngine } from '../hud/Hud.ts';
import { createWorldTag } from '../hud/WorldTag.ts';
import { type Tone, fixed } from '../hud/fields.ts';
import { L } from '../log.ts';
import { type TopOrientation, type ViewMode, createCameraRig } from './CameraRig.ts';
import { createGroundFx } from './GroundFx.ts';
import { MAX_WAYPOINTS, type NavFxFrame, createNavFx, sameContact } from './NavFx.ts';
import { createRobotModel } from './RobotModel.ts';
import { createRoomMap } from './RoomMap.ts';
import type { Contact, TelemetryStore } from './Telemetry.ts';
import { predictWaypoints, remainingMission } from './mission.ts';

const MAP_CHUNKS_SUBJECT = 'rabbit.map.chunks';
const MAP_SNAPSHOT_SUBJECT = 'rabbit.map.snapshot';
const SNAPSHOT_TIMEOUT_MS = 10_000;
const MAX_STEERING_RAD = THREE.MathUtils.degToRad(30);
const MAX_PIXEL_RATIO = 1.5;
const POSE_RATE = 24;
const SPEED_RATE = 0.2;
const MAX_WHEEL_STEP = 0.2;
const G_RATE = 0.25;
const EYE_CLEARANCE = 0.2;
const GRAVITY = 9.80665;
const FLOOR_Y = 0;
const CLEAR_COLOR = 0x0a0f14;
const CONTACT_TIMEOUT_MS = 1000;
const NAV_TIMEOUT_MS = 2000;
const EXPLORE_TIMEOUT_MS = 3000;
const ERROR_LOG_MS = 5000;

type ScreenPoint = { x: number; y: number; visible: boolean };

export type SceneSettings = { viewMode: ViewMode; topOrientation: TopOrientation; mapVisible: boolean; goArmed: boolean };

type SceneOptions = {
    canvas: HTMLCanvasElement;
    container: HTMLElement;
    tags: HTMLElement;
    nc: NatsConnection;
    onLink: (fn: (state: LinkState) => void) => () => void;
    store: TelemetryStore;
    engine: HudEngine;
    settings: SceneSettings;
    onModeChange: (mode: ViewMode) => void;
    onGoal: (point: THREE.Vector3, append: boolean) => void;
};

export type Scene = { apply: (settings: SceneSettings) => void; dispose: () => void };

const allFinite = (values: readonly (number | null)[]) => values.every((value) => value != null && Number.isFinite(value));

const validContact = (contact: Contact | null | undefined) =>
    contact != null && allFinite(contact.point) && contact.distance != null ? contact : null;

const contactTone = (contact: Contact): Tone => (contact.distance < 0.5 ? 'alert' : contact.distance < 1 ? 'warn' : 'normal');

export const createScene = ({
    canvas,
    container,
    tags,
    nc,
    onLink,
    store,
    engine,
    settings,
    onModeChange,
    onGoal,
}: SceneOptions): Scene => {
    let { width, height } = container.getBoundingClientRect();
    let pixelRatio = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO);
    let disposed = false;
    let current = settings;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(pixelRatio);
    renderer.setClearColor(CLEAR_COLOR);
    renderer.setSize(width, height, false);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(CLEAR_COLOR, 0.06);
    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const keyLight = new THREE.DirectionalLight(0xffffff, 0.8);
    keyLight.position.set(3, 8, 5);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0x4488ff, 0.3);
    fillLight.position.set(-3, 4, -5);
    scene.add(fillLight);

    const camera = new THREE.PerspectiveCamera(55, width / height, 0.03, 200);
    camera.position.set(0, 2, 3);

    const robot = createRobotModel();
    scene.add(robot.group);
    robot.group.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(robot.group);
    const centerLocal = bounds.getCenter(new THREE.Vector3());
    const frontLocal = new THREE.Vector3(centerLocal.x, centerLocal.y, bounds.min.z);

    const roomMap = createRoomMap();
    scene.add(roomMap.group);
    const groundFx = createGroundFx();
    scene.add(groundFx.group);
    const navFx = createNavFx();
    scene.add(navFx.group);

    const nearestTag = createWorldTag(tags, false);
    const aheadTag = createWorldTag(tags, true);

    const mapSub = nc.subscribe(MAP_CHUNKS_SUBJECT, {
        callback: (_, msg) => {
            try {
                roomMap.apply(msg.headers?.get('session') ?? '', msg.data);
            } catch (error) {
                L.error('Failed to decode map chunk', error);
            }
        },
    });
    const requestSnapshot = () =>
        nc
            .request(MAP_SNAPSHOT_SUBJECT, undefined, { timeout: SNAPSHOT_TIMEOUT_MS })
            .then((msg) => {
                if (!disposed) roomMap.apply(msg.headers?.get('session') ?? '', msg.data);
            })
            .catch((error) => L.error('Failed to load map snapshot', error));
    void requestSnapshot();
    const offLink = onLink((state) => {
        if (state === 'connected') void requestSnapshot();
    });

    const posePosition = new THREE.Vector3();
    const poseQuaternion = new THREE.Quaternion();
    const center = new THREE.Vector3();
    const front = new THREE.Vector3();
    const ground = new THREE.Vector3();
    const rearAxle = new THREE.Vector3();
    const forward = new THREE.Vector3();
    const sideways = new THREE.Vector3();
    const upward = new THREE.Vector3();
    const scratch = new THREE.Vector3();
    const other = new THREE.Vector3();
    const gravity = new THREE.Vector3();
    const imuQuaternion = new THREE.Quaternion();
    const pendingGoal = new THREE.Vector3();
    const robotFrame = { center, eye: robot.group.position, forward };
    const derived = store.derived;

    const tagAnchor: ScreenPoint = { x: 0, y: 0, visible: false };
    let hasPendingGoal = false;
    const waypoints = Array.from({ length: MAX_WAYPOINTS }, () => ({ x: 0, z: 0, marker: false }));
    let waypointCount = 0;
    const fxFrame: NavFxFrame = {
        time: 0,
        camera,
        front,
        nearest: null,
        ahead: null,
        nav: null,
        pendingGoal: null,
        showLeaders: true,
        start: ground,
        waypoints,
        waypointCount: 0,
        target: null,
    };
    let navVersion = 0;
    let poseVersion = 0;
    let imuVersion = 0;
    let lastPoseTimestamp = 0;
    let travelled = 0;
    const lastPosition = new THREE.Vector3();
    let lastFrame = performance.now();

    const raycaster = new THREE.Raycaster();
    const hits: THREE.Intersection[] = [];
    const floor = new THREE.Plane(new THREE.Vector3(0, 1, 0), -FLOOR_Y);
    const picked = new THREE.Vector3();

    const pick = (ndc: THREE.Vector2) => {
        raycaster.setFromCamera(ndc, camera);
        hits.length = 0;
        raycaster.intersectObject(robot.group, true, hits);
        if (hits.length > 0) return picked.copy(center);
        if (roomMap.group.visible) {
            raycaster.intersectObject(roomMap.group, true, hits);
            const hit = hits[0];
            if (hit != null) return picked.copy(hit.point);
        }
        return raycaster.ray.intersectPlane(floor, picked);
    };

    const pickFloor = (ndc: THREE.Vector2) => {
        raycaster.setFromCamera(ndc, camera);
        return raycaster.ray.intersectPlane(floor, picked);
    };

    const rig = createCameraRig({
        camera,
        element: canvas,
        pick,
        onModeChange,
        onClick: (ndc, append) => {
            if (!current.goArmed) return;
            const point = pickFloor(ndc);
            if (point == null) return;
            pendingGoal.copy(point);
            hasPendingGoal = true;
            onGoal(pendingGoal, append);
        },
    });

    const apply = (next: SceneSettings) => {
        current = next;
        rig.setMode(next.viewMode);
        rig.setTopOrientation(next.topOrientation);
        roomMap.group.visible = next.mapVisible;
    };
    apply(settings);

    const localToWorld = (local: THREE.Vector3, out: THREE.Vector3) =>
        out.copy(local).applyQuaternion(robot.group.quaternion).add(robot.group.position);

    const project = (point: THREE.Vector3, anchor: ScreenPoint) => {
        const distance = point.distanceTo(camera.position);
        scratch.copy(point).project(camera);
        anchor.x = (scratch.x * 0.5 + 0.5) * width;
        anchor.y = (-scratch.y * 0.5 + 0.5) * height;
        anchor.visible = distance > 0.15 && scratch.z < 1 && Math.abs(scratch.x) < 1.02 && Math.abs(scratch.y) < 1.02;
        return anchor;
    };

    const readPose = () => {
        const pose = store.pose.value;
        if (pose == null || store.pose.version === poseVersion) return;
        poseVersion = store.pose.version;
        if (!allFinite(pose.translation) || !allFinite(pose.orientation)) return;
        other.copy(posePosition);
        posePosition.fromArray(pose.translation);
        poseQuaternion.fromArray(pose.orientation).normalize();
        const velocity = pose.velocity == null ? 0 : Math.hypot(pose.velocity[0], pose.velocity[2]);
        const dt = (pose.timestamp - lastPoseTimestamp) / 1e9;
        if (velocity > 0) {
            derived.speed += (velocity - derived.speed) * SPEED_RATE;
        } else if (derived.hasPose && dt > 0.001 && dt < 1) {
            const speed = Math.hypot(posePosition.x - other.x, posePosition.z - other.z) / dt;
            derived.speed += (speed - derived.speed) * SPEED_RATE;
        }
        lastPoseTimestamp = pose.timestamp;
        if (!derived.hasPose || robot.group.position.distanceToSquared(posePosition) > 1) {
            robot.group.position.copy(posePosition);
            robot.group.quaternion.copy(poseQuaternion);
        }
        derived.hasPose = true;
    };

    const readImu = () => {
        const imu = store.imu.value;
        if (imu == null || store.imu.version === imuVersion) return;
        imuVersion = store.imu.version;
        if (!allFinite(imu.orientation) || !allFinite(imu.acceleration)) return;
        imuQuaternion.fromArray(imu.orientation).normalize().invert();
        gravity.set(0, GRAVITY, 0).applyQuaternion(imuQuaternion);
        const [ax, ay, az] = imu.acceleration;
        derived.lateralG += ((ax - gravity.x) / GRAVITY - derived.lateralG) * G_RATE;
        derived.longitudinalG += ((gravity.z - az) / GRAVITY - derived.longitudinalG) * G_RATE;
        derived.g += ((imu.g ?? Math.hypot(ax, ay, az) / GRAVITY) - derived.g) * G_RATE;
    };

    const tagContact = (tag: typeof nearestTag, contact: Contact | null, label: string) => {
        if (contact == null) {
            tag.update(0, 0, false, '', 'normal');
            return;
        }
        const anchor = project(scratch.fromArray(contact.point), tagAnchor);
        const bearing = contact.bearing_deg ?? 0;
        const side = Math.abs(bearing) < 2 ? '' : bearing > 0 ? ` R${bearing.toFixed(0)}°` : ` L${(-bearing).toFixed(0)}°`;
        tag.update(
            anchor.x,
            anchor.y,
            anchor.visible,
            `${label} ${fixed(contact.distance, 2, ' M')}${side}`,
            contactTone(contact),
        );
    };

    const frame = () => {
        const now = performance.now();
        const dt = Math.min((now - lastFrame) / 1000, 0.1);
        lastFrame = now;

        const dpr = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO);
        if (dpr !== pixelRatio) {
            pixelRatio = dpr;
            renderer.setPixelRatio(dpr);
            renderer.setSize(width, height, false);
        }

        readPose();
        readImu();
        if (derived.hasPose) {
            const k = 1 - Math.exp(-POSE_RATE * dt);
            robot.group.position.lerp(posePosition, k);
            robot.group.quaternion.slerp(poseQuaternion, k);
        }

        const quaternion = robot.group.quaternion;
        forward.set(0, 0, -1).applyQuaternion(quaternion);
        sideways.set(1, 0, 0).applyQuaternion(quaternion);
        upward.set(0, 1, 0).applyQuaternion(quaternion);
        derived.heading = (THREE.MathUtils.radToDeg(Math.atan2(forward.x, -forward.z)) + 360) % 360;
        derived.pitch = Math.asin(THREE.MathUtils.clamp(forward.y, -1, 1));
        derived.roll = Math.atan2(-sideways.y, upward.y);
        derived.x = robot.group.position.x;
        derived.y = robot.group.position.y;
        derived.z = robot.group.position.z;
        localToWorld(centerLocal, center);
        localToWorld(frontLocal, front);
        ground.set(center.x, FLOOR_Y, center.z);

        const step = scratch.subVectors(robot.group.position, lastPosition).dot(forward);
        if (Math.abs(step) < MAX_WHEEL_STEP) travelled += step;
        lastPosition.copy(robot.group.position);
        robot.update({
            steering: -(store.steering.value?.angle ?? 0) * MAX_STEERING_RAD,
            travelled,
            time: now / 1000,
        });

        const time = now / 1000;
        robot.wheels.rl
            .getWorldPosition(rearAxle)
            .add(robot.wheels.rr.getWorldPosition(scratch))
            .multiplyScalar(0.5)
            .setY(FLOOR_Y);
        groundFx.update(time, ground, rearAxle, Math.atan2(-forward.x, -forward.z));
        derived.odometer = groundFx.distance();
        rig.update(dt, now, robotFrame);
        robot.group.visible = camera.position.distanceToSquared(robot.group.position) > EYE_CLEARANCE ** 2;

        const obstacle = now - store.obstacle.receivedAt < CONTACT_TIMEOUT_MS ? store.obstacle.value : null;
        const nav = now - store.nav.receivedAt < NAV_TIMEOUT_MS ? store.nav.value : null;
        if (nav?.goal != null) hasPendingGoal = false;
        const ahead = validContact(obstacle?.ahead);
        const candidate = validContact(obstacle?.nearest);
        const nearest = sameContact(candidate, ahead) ? null : candidate;
        if (nav == null) {
            waypointCount = 0;
        } else if (store.nav.version !== navVersion) {
            navVersion = store.nav.version;
            waypointCount = predictWaypoints(
                remainingMission(nav),
                { x: derived.x, z: derived.z, heading: derived.heading },
                waypoints,
            );
        }
        const explore = now - store.explore.receivedAt < EXPLORE_TIMEOUT_MS ? store.explore.value : null;
        fxFrame.time = time;
        fxFrame.nearest = nearest;
        fxFrame.ahead = ahead;
        fxFrame.nav = nav;
        fxFrame.pendingGoal = hasPendingGoal ? pendingGoal : null;
        fxFrame.showLeaders = robot.group.visible;
        fxFrame.waypointCount = waypointCount;
        fxFrame.target = explore?.target ?? null;
        navFx.update(fxFrame);

        roomMap.flush();
        roomMap.setRobot(robot.group.position);
        renderer.render(scene, camera);

        tagContact(nearestTag, nearest, 'CONTACT');
        tagContact(aheadTag, ahead, 'AHEAD');

        engine.frame(dt, now);
    };

    let lastErrorLog = -Infinity;
    renderer.setAnimationLoop(() => {
        try {
            frame();
        } catch (error) {
            const now = performance.now();
            if (now - lastErrorLog > ERROR_LOG_MS) {
                lastErrorLog = now;
                L.error('Perception frame failed', error);
            }
        }
    });

    const observer = new ResizeObserver(() => {
        const rect = container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        width = rect.width;
        height = rect.height;
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
    });
    observer.observe(container);

    return {
        apply,
        dispose: () => {
            disposed = true;
            observer.disconnect();
            renderer.setAnimationLoop(null);
            rig.dispose();
            mapSub.unsubscribe();
            offLink();
            nearestTag.dispose();
            aheadTag.dispose();
            groundFx.dispose();
            navFx.dispose();
            robot.dispose();
            roomMap.dispose();
            renderer.dispose();
        },
    };
};
