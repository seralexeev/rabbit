import * as THREE from 'three';

import { HUD_COLOR } from '../hud/Hud.ts';
import type { Contact, ExploreTarget, NavState, TripState } from './Telemetry.ts';
import type { Waypoint } from './mission.ts';

const MAX_PATH_POINTS = 512;
export const MAX_WAYPOINTS = 128;
const MAX_MARKERS = 16;
const TARGET_SIZE = 0.4;
const WAYPOINT_SIZE = 0.035;
const PATH_LIFT = 0.012;
const AMBER = 0xffb547;
const ALERT = 0xff5a4a;
const CONTACT_SIZE = 0.22;
const GOAL_SIZE = 0.5;
const BEAM_HEIGHT = 0.6;
const ROUTE_LIFT = 0.02;
const ROUTE_PHASES = new Set(['planned', 'planning', 'replanning', 'waiting', 'recovering']);

export const sameContact = (a: Contact | null, b: Contact | null) =>
    a != null && b != null && a.point[0] === b.point[0] && a.point[1] === b.point[1] && a.point[2] === b.point[2];

const contactColor = (distance: number) => (distance < 0.5 ? ALERT : distance < 1 ? AMBER : HUD_COLOR);

const ringMaterial = (color: number) =>
    new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        uniforms: { uColor: { value: new THREE.Color(color) }, uTime: { value: 0 }, uPulse: { value: 1 } },
        vertexShader: `
            varying vec2 vUv;
            void main() {
                vUv = uv;
                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
        `,
        fragmentShader: `
            uniform vec3 uColor;
            uniform float uTime;
            uniform float uPulse;
            varying vec2 vUv;
            const float TAU = 6.2831853;
            float band(float d, float w) {
                return 1.0 - smoothstep(w, w + fwidth(d) * 1.5, abs(d));
            }
            void main() {
                vec2 p = (vUv - 0.5) * 2.0;
                float r = length(p);
                float a = atan(p.x, p.y);
                float wave = fract(uTime * 0.9 * uPulse);
                float ring = band(r - 0.62, 0.035);
                float brackets = band(r - 0.9, 0.03) * step(0.62, abs(cos(a * 2.0)));
                float ripple = band(r - wave, 0.03) * (1.0 - wave);
                float dot = 1.0 - smoothstep(0.08, 0.12, r);
                float alpha = ring * 0.9 + brackets * 0.8 + ripple * 0.7 + dot;
                if (alpha < 0.003) discard;
                gl_FragColor = vec4(uColor * alpha, alpha);
            }
        `,
    });

type Polyline = { line: THREE.Line; positions: Float32Array; commit: (count: number) => void };

const createPolyline = (capacity: number, material: THREE.LineBasicMaterial): Polyline => {
    const positions = new Float32Array(capacity * 3);
    const distances = new Float32Array(capacity);
    const geometry = new THREE.BufferGeometry();
    const positionAttr = new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage);
    const distanceAttr = new THREE.BufferAttribute(distances, 1).setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('position', positionAttr);
    geometry.setAttribute('lineDistance', distanceAttr);
    geometry.setDrawRange(0, 0);
    const line = new THREE.Line(geometry, material);
    line.frustumCulled = false;
    return {
        line,
        positions,
        commit: (count) => {
            let distance = 0;
            for (let i = 1; i < count; i++) {
                const a = (i - 1) * 3;
                const b = i * 3;
                distance += Math.hypot(
                    positions[b]! - positions[a]!,
                    positions[b + 1]! - positions[a + 1]!,
                    positions[b + 2]! - positions[a + 2]!,
                );
                distances[i] = distance;
            }
            positionAttr.needsUpdate = true;
            distanceAttr.needsUpdate = true;
            geometry.setDrawRange(0, count);
        },
    };
};

type ContactFx = {
    reticle: THREE.Mesh;
    material: THREE.ShaderMaterial;
    polyline: Polyline;
    lineMaterial: THREE.LineBasicMaterial;
};

export type NavFxFrame = {
    time: number;
    camera: THREE.Camera;
    front: THREE.Vector3;
    nearest: Contact | null;
    ahead: Contact | null;
    nav: NavState | null;
    pendingGoal: THREE.Vector3 | null;
    showLeaders: boolean;
    start: THREE.Vector3;
    waypoints: readonly Waypoint[];
    waypointCount: number;
    target: ExploreTarget | null;
    trip?: TripState | null;
};

export type NavFx = {
    group: THREE.Group;
    update: (frame: NavFxFrame) => void;
    dispose: () => void;
};

export const createNavFx = (): NavFx => {
    const group = new THREE.Group();
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];
    const track = <T extends THREE.Material>(material: T) => {
        materials.push(material);
        return material;
    };
    const addPolyline = (capacity: number, material: THREE.LineBasicMaterial) => {
        const polyline = createPolyline(capacity, track(material));
        geometries.push(polyline.line.geometry);
        group.add(polyline.line);
        return polyline;
    };

    const contactGeo = new THREE.PlaneGeometry(CONTACT_SIZE, CONTACT_SIZE);
    geometries.push(contactGeo);
    const createContact = (dashed: boolean): ContactFx => {
        const material = track(ringMaterial(HUD_COLOR));
        const reticle = new THREE.Mesh(contactGeo, material);
        reticle.renderOrder = 10;
        reticle.visible = false;
        group.add(reticle);
        const lineMaterial = dashed
            ? new THREE.LineDashedMaterial({
                  color: HUD_COLOR,
                  dashSize: 0.04,
                  gapSize: 0.03,
                  transparent: true,
                  opacity: 0.7,
                  depthTest: false,
              })
            : new THREE.LineBasicMaterial({ color: HUD_COLOR, transparent: true, opacity: 0.9, depthTest: false });
        const polyline = addPolyline(2, lineMaterial);
        polyline.line.renderOrder = 10;
        polyline.line.visible = false;
        return { reticle, material, polyline, lineMaterial };
    };
    const nearest = createContact(true);
    const ahead = createContact(false);

    const goalMaterial = track(ringMaterial(AMBER));
    const goalGeo = new THREE.PlaneGeometry(GOAL_SIZE, GOAL_SIZE).rotateX(-Math.PI / 2);
    const beamGeo = new THREE.CylinderGeometry(0.004, 0.004, BEAM_HEIGHT, 6).translate(0, BEAM_HEIGHT / 2, 0);
    const beamMat = track(new THREE.MeshBasicMaterial({ color: AMBER, transparent: true, opacity: 0.6 }));
    const goalMarker = new THREE.Group();
    goalMarker.add(new THREE.Mesh(goalGeo, goalMaterial), new THREE.Mesh(beamGeo, beamMat));
    goalMarker.visible = false;
    group.add(goalMarker);
    geometries.push(goalGeo, beamGeo);

    const targetMaterial = track(ringMaterial(HUD_COLOR));
    const targetGeo = new THREE.PlaneGeometry(TARGET_SIZE, TARGET_SIZE).rotateX(-Math.PI / 2);
    const arrowGeo = new THREE.ConeGeometry(0.04, 0.16, 3).rotateZ(-Math.PI / 2).translate(0.2, 0.02, 0);
    const arrowMat = track(new THREE.MeshBasicMaterial({ color: HUD_COLOR, transparent: true, opacity: 0.85 }));
    const targetMarker = new THREE.Group();
    targetMarker.add(new THREE.Mesh(targetGeo, targetMaterial), new THREE.Mesh(arrowGeo, arrowMat));
    targetMarker.visible = false;
    group.add(targetMarker);
    geometries.push(targetGeo, arrowGeo);

    const path = addPolyline(
        MAX_PATH_POINTS,
        new THREE.LineDashedMaterial({ color: AMBER, dashSize: 0.08, gapSize: 0.05, transparent: true, opacity: 0.85 }),
    );
    const mission = addPolyline(
        MAX_WAYPOINTS + 1,
        new THREE.LineDashedMaterial({ color: AMBER, dashSize: 0.05, gapSize: 0.04, transparent: true, opacity: 0.7 }),
    );

    const route = addPolyline(
        MAX_PATH_POINTS,
        new THREE.LineDashedMaterial({ color: HUD_COLOR, dashSize: 0.03, gapSize: 0.05, transparent: true, opacity: 0.8 }),
    );
    const tripMaterial = track(ringMaterial(HUD_COLOR));
    const tripMarker = new THREE.Mesh(goalGeo, tripMaterial);
    tripMarker.visible = false;
    group.add(tripMarker);

    let routeRef: [number, number, number][] | null = null;
    const updateTrip = (time: number, trip: TripState | null | undefined) => {
        const shown = trip != null && ROUTE_PHASES.has(trip.phase) ? (trip.path ?? null) : null;
        if (shown !== routeRef) {
            routeRef = shown;
            const count = Math.min(shown?.length ?? 0, MAX_PATH_POINTS);
            for (let i = 0; i < count; i++) {
                route.positions[i * 3] = shown?.[i]?.[0] ?? 0;
                route.positions[i * 3 + 1] = ROUTE_LIFT;
                route.positions[i * 3 + 2] = shown?.[i]?.[1] ?? 0;
            }
            route.commit(count);
        }
        const target = trip?.target;
        tripMarker.visible = target != null && target.kind !== 'point' && trip?.phase !== 'idle' && trip?.phase !== 'cancelled';
        if (target != null) tripMarker.position.set(target.x, 0.01, target.z);
        tripMaterial.uniforms['uTime']!.value = time;
    };

    const waypointGeo = new THREE.OctahedronGeometry(WAYPOINT_SIZE);
    const waypointMat = track(new THREE.MeshBasicMaterial({ color: AMBER, wireframe: true, transparent: true, opacity: 0.9 }));
    geometries.push(waypointGeo);
    const markers = Array.from({ length: MAX_MARKERS }, () => {
        const marker = new THREE.Mesh(waypointGeo, waypointMat);
        marker.visible = false;
        group.add(marker);
        return marker;
    });

    const updateMission = (time: number, start: THREE.Vector3, waypoints: readonly Waypoint[], count: number) => {
        const positions = mission.positions;
        positions[0] = start.x;
        positions[1] = PATH_LIFT;
        positions[2] = start.z;
        let used = 0;
        for (let i = 0; i < count; i++) {
            const waypoint = waypoints[i];
            if (waypoint == null) break;
            positions[(i + 1) * 3] = waypoint.x;
            positions[(i + 1) * 3 + 1] = PATH_LIFT;
            positions[(i + 1) * 3 + 2] = waypoint.z;
            if (!waypoint.marker || used >= MAX_MARKERS) continue;
            const marker = markers[used++]!;
            marker.visible = true;
            marker.position.set(waypoint.x, WAYPOINT_SIZE + 0.02 + Math.sin(time * 3 + i) * 0.01, waypoint.z);
            marker.rotation.y = time * 1.5;
        }
        for (let i = used; i < MAX_MARKERS; i++) markers[i]!.visible = false;
        mission.commit(count > 0 ? count + 1 : 0);
    };

    const updateContact = (fx: ContactFx, contact: Contact | null, frame: NavFxFrame) => {
        fx.reticle.visible = contact != null;
        fx.polyline.line.visible = contact != null && frame.showLeaders;
        if (contact == null) return;
        const [x, y, z] = contact.point;
        fx.reticle.position.set(x, y, z);
        fx.reticle.quaternion.copy(frame.camera.quaternion);
        const color = contactColor(contact.distance);
        fx.material.uniforms['uColor']!.value.setHex(color);
        fx.material.uniforms['uTime']!.value = frame.time;
        fx.material.uniforms['uPulse']!.value = contact.distance < 1 ? 2 : 1;
        fx.lineMaterial.color.setHex(color);
        const positions = fx.polyline.positions;
        positions[0] = frame.front.x;
        positions[1] = frame.front.y;
        positions[2] = frame.front.z;
        positions[3] = x;
        positions[4] = y;
        positions[5] = z;
        fx.polyline.commit(2);
    };

    let pathRef: [number, number][] | null = null;
    const updatePath = (nav: NavState | null) => {
        const next = nav?.path ?? null;
        if (next === pathRef) return;
        pathRef = next;
        const count = Math.min(next?.length ?? 0, MAX_PATH_POINTS);
        for (let i = 0; i < count; i++) {
            const point = next?.[i];
            path.positions[i * 3] = point?.[0] ?? 0;
            path.positions[i * 3 + 1] = PATH_LIFT;
            path.positions[i * 3 + 2] = point?.[1] ?? 0;
        }
        path.commit(count);
    };

    return {
        group,
        update: (frame) => {
            updateMission(frame.time, frame.start, frame.waypoints, frame.waypointCount);
            updateContact(nearest, frame.nearest, frame);
            updateContact(ahead, frame.ahead, frame);
            updatePath(frame.nav);
            updateTrip(frame.time, frame.trip);

            const goal = frame.nav?.goal ?? null;
            goalMarker.visible = goal != null || frame.pendingGoal != null;
            if (goal != null) goalMarker.position.set(goal.x, 0, goal.z);
            else if (frame.pendingGoal != null) goalMarker.position.set(frame.pendingGoal.x, 0, frame.pendingGoal.z);
            goalMaterial.uniforms['uTime']!.value = frame.time;
            goalMaterial.uniforms['uColor']!.value.setHex(frame.nav?.mode === 'arrived' ? HUD_COLOR : AMBER);

            targetMarker.visible = frame.target != null;
            if (frame.target != null) {
                targetMarker.position.set(frame.target.x, 0.005, frame.target.z);
                targetMarker.rotation.y = -frame.target.theta;
                targetMaterial.uniforms['uTime']!.value = frame.time;
            }
        },
        dispose: () => {
            for (const geometry of geometries) geometry.dispose();
            for (const material of materials) material.dispose();
        },
    };
};
