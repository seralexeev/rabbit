import * as THREE from 'three';

import { type WorldTag, createWorldTag } from '../hud/WorldTag.ts';
import type { Tone } from '../hud/fields.ts';
import type { DetectedObject, DetectedObjects } from './Telemetry.ts';

const MAX_SHOWN = 16;
const MERGE_MIN_M = 0.3;
const MERGE_MAX_DY_M = 0.5;
const VIEW_HALF_ANGLE_RAD = THREE.MathUtils.degToRad(35);
const VIEW_MIN_M = 0.5;
const VIEW_MAX_M = 5;
const UNSEEN_IN_VIEW_MS = 2500;
const FRESH_MS = 1500;
const MOVING_MEMORY_MS = 3000;
const STATIC_MEMORY_MS = 120_000;
const FRESH_COLOR = new THREE.Color(0xe8fbff);
const MOVING_COLOR = new THREE.Color(0xffb547);
const MEMORY_COLOR = new THREE.Color(0x3a8fb0);
const EDGES = [0, 1, 1, 2, 2, 3, 3, 0, 4, 5, 5, 6, 6, 7, 7, 4, 0, 4, 1, 5, 2, 6, 3, 7];
const VERTICES_PER_BOX = EDGES.length;

type Memory = { object: DetectedObject; seenAt: number };
type ScreenPoint = { x: number; y: number; visible: boolean };

export type ObjectsFxFrame = {
    now: number;
    objects: DetectedObjects | null;
    version: number;
    robot: THREE.Vector3;
    forward: THREE.Vector3;
    project: (point: THREE.Vector3, anchor: ScreenPoint) => ScreenPoint;
};

export type ObjectsFx = {
    group: THREE.Group;
    update: (frame: ObjectsFxFrame) => void;
    reset: () => void;
    dispose: () => void;
};

export const createObjectsFx = (tagParent: HTMLElement): ObjectsFx => {
    const group = new THREE.Group();
    const positions = new Float32Array(MAX_SHOWN * VERTICES_PER_BOX * 3);
    const colors = new Float32Array(MAX_SHOWN * VERTICES_PER_BOX * 3);
    const geometry = new THREE.BufferGeometry();
    const positionAttr = new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage);
    const colorAttr = new THREE.BufferAttribute(colors, 3).setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('position', positionAttr);
    geometry.setAttribute('color', colorAttr);
    geometry.setDrawRange(0, 0);
    const material = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
    });
    const lines = new THREE.LineSegments(geometry, material);
    lines.frustumCulled = false;
    group.add(lines);

    const tags: WorldTag[] = Array.from({ length: MAX_SHOWN }, () => createWorldTag(tagParent, false));
    const memory = new Map<number, Memory>();
    const shown: Memory[] = [];
    const anchor: ScreenPoint = { x: 0, y: 0, visible: false };
    const top = new THREE.Vector3();
    let version = -1;

    const sameObject = (a: DetectedObject, b: DetectedObject) => {
        if (a.label !== b.label) return false;
        const reach = Math.max(MERGE_MIN_M, a.dimensions[0] / 2, a.dimensions[2] / 2, b.dimensions[0] / 2, b.dimensions[2] / 2);
        return (
            Math.hypot(a.position[0] - b.position[0], a.position[2] - b.position[2]) < reach &&
            Math.abs(a.position[1] - b.position[1]) < MERGE_MAX_DY_M
        );
    };

    const remember = (objects: DetectedObjects, now: number) => {
        for (const object of objects.objects) {
            if (!memory.has(object.id)) {
                for (const [id, entry] of memory) {
                    if (entry.seenAt !== now && sameObject(entry.object, object)) memory.delete(id);
                }
            }
            memory.set(object.id, { object, seenAt: now });
        }
    };

    const inView = (entry: Memory, robot: THREE.Vector3, forward: THREE.Vector3) => {
        const dx = entry.object.position[0] - robot.x;
        const dz = entry.object.position[2] - robot.z;
        const distance = Math.hypot(dx, dz);
        if (distance < VIEW_MIN_M || distance > VIEW_MAX_M) return false;
        const cos = (dx * forward.x + dz * forward.z) / (distance * Math.hypot(forward.x, forward.z));
        return cos > Math.cos(VIEW_HALF_ANGLE_RAD);
    };

    const forget = ({ now, robot, forward }: ObjectsFxFrame, detecting: boolean) => {
        for (const [id, entry] of memory) {
            const ttl = entry.object.moving ? MOVING_MEMORY_MS : STATIC_MEMORY_MS;
            const missed = detecting && now - entry.seenAt > UNSEEN_IN_VIEW_MS && inView(entry, robot, forward);
            if (now - entry.seenAt > ttl || missed) memory.delete(id);
        }
    };

    const colorOf = (entry: Memory, now: number) =>
        now - entry.seenAt > FRESH_MS ? MEMORY_COLOR : entry.object.moving ? MOVING_COLOR : FRESH_COLOR;

    const toneOf = (entry: Memory, now: number): Tone =>
        now - entry.seenAt > FRESH_MS ? 'normal' : entry.object.moving ? 'warn' : 'good';

    const writeBoxes = (now: number) => {
        let box = 0;
        for (const entry of shown) {
            const color = colorOf(entry, now);
            const corners = entry.object.corners;
            for (let i = 0; i < VERTICES_PER_BOX; i++) {
                const corner = corners[EDGES[i]!]!;
                const offset = (box * VERTICES_PER_BOX + i) * 3;
                positions[offset] = corner[0];
                positions[offset + 1] = corner[1];
                positions[offset + 2] = corner[2];
                colors[offset] = color.r;
                colors[offset + 1] = color.g;
                colors[offset + 2] = color.b;
            }
            box++;
        }
        geometry.setDrawRange(0, box * VERTICES_PER_BOX);
        positionAttr.needsUpdate = true;
        colorAttr.needsUpdate = true;
    };

    const distanceTo = (entry: Memory, robot: THREE.Vector3) =>
        Math.hypot(entry.object.position[0] - robot.x, entry.object.position[2] - robot.z);

    const pickShown = (robot: THREE.Vector3) => {
        shown.length = 0;
        for (const entry of memory.values()) shown.push(entry);
        shown.sort((a, b) => b.seenAt - a.seenAt || distanceTo(a, robot) - distanceTo(b, robot));
        shown.length = Math.min(shown.length, MAX_SHOWN);
    };

    const writeTags = ({ now, robot, project }: ObjectsFxFrame) => {
        for (let i = 0; i < MAX_SHOWN; i++) {
            const tag = tags[i]!;
            const entry = shown[i];
            if (entry == null) {
                tag.update(0, 0, false, '', 'normal');
                continue;
            }
            const corners = entry.object.corners;
            top.set(0, -Infinity, 0);
            for (const corner of corners) {
                top.x += corner[0] / corners.length;
                top.z += corner[2] / corners.length;
                top.y = Math.max(top.y, corner[1]);
            }
            project(top, anchor);
            const label = `${entry.object.label.toUpperCase()} ${distanceTo(entry, robot).toFixed(1)} M`;
            tag.update(anchor.x, anchor.y, anchor.visible, label, toneOf(entry, now));
        }
    };

    return {
        group,
        update: (frame) => {
            if (frame.objects != null && frame.version !== version) {
                version = frame.version;
                remember(frame.objects, frame.now);
            }
            forget(frame, frame.objects != null);
            pickShown(frame.robot);
            writeBoxes(frame.now);
            writeTags(frame);
        },
        reset: () => memory.clear(),
        dispose: () => {
            for (const tag of tags) tag.dispose();
            geometry.dispose();
            material.dispose();
        },
    };
};
