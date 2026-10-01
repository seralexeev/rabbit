import { css, cx } from '@emotion/css';
import React from 'react';

import { useLinkState, useNats } from '../app/NatsProvider.tsx';
import { ChatPanel } from '../chat/ChatPanel.tsx';
import { createKeyboardDriver, isEditable } from '../controller/keyboard.ts';
import { useGamepadPublisher } from '../controller/useGamepadPublisher.ts';
import { useEvent, useLocalState } from '../hooks.ts';
import { Compass } from '../hud/Compass.tsx';
import { createHudEngine } from '../hud/Hud.ts';
import { HudProvider } from '../hud/HudProvider.tsx';
import { KeyboardIndicator } from '../hud/KeyboardIndicator.tsx';
import { LinkIndicator } from '../hud/LinkIndicator.tsx';
import { DrivePanel, PowerPanel, RoboclawPanel, SteeringPanel } from '../hud/panels/DrivePanels.tsx';
import { ExplorePanel } from '../hud/panels/ExplorePanel.tsx';
import { GamepadPanel } from '../hud/panels/GamepadPanel.tsx';
import { MinimapPanel } from '../hud/panels/MinimapPanel.tsx';
import { NavPanel } from '../hud/panels/NavPanel.tsx';
import { RoutePanel } from '../hud/panels/RoutePanel.tsx';
import { SystemPanel } from '../hud/panels/SystemPanel.tsx';
import { WifiPanel } from '../hud/panels/WifiPanel.tsx';
import { ZedPanel } from '../hud/panels/ZedPanel.tsx';
import { L } from '../log.ts';
import { ui } from '../ui/index.ts';
import { TOP_ORIENTATIONS, type TopOrientation, VIEW_MODES, type ViewMode } from './CameraRig.ts';
import { createFloorPlan } from './FloorPlan.ts';
import { type Scene, type SceneSettings, createScene } from './Scene.ts';
import { createTelemetryStore } from './Telemetry.ts';
import { createHistory } from './history.ts';
import { type MissionStep, remainingMission } from './mission.ts';
import { createStopper } from './stopper.ts';

const VIEW_MODE_KEY = 'rabbit.perception.view_mode';
const MISSION_SUBJECT = 'rabbit.nav.mission';

const MAP_TOGGLE = [
    { id: 'show', label: 'MAP' },
    { id: 'hide', label: 'OFF' },
] as const;

const HINTS: Record<ViewMode, string> = {
    fpv: 'DRAG LOOK · WHEEL FOV · DBL-CLICK FOCUS',
    third: 'DRAG ORBIT · WHEEL ZOOM · DBL-CLICK FOCUS',
    top: 'DRAG PAN · WHEEL ZOOM · DBL-CLICK FOCUS',
    free: 'DRAG ORBIT · RIGHT-DRAG PAN · WHEEL ZOOM · DBL-CLICK FOCUS',
};

export const PerceptionView: React.FC = () => {
    const { nc, link, onLink } = useNats();
    const connected = useLinkState() === 'connected';
    useGamepadPublisher();
    const [keyboard] = React.useState(createKeyboardDriver);
    React.useEffect(() => keyboard.start(nc), [keyboard, nc]);

    const [engine] = React.useState(createHudEngine);
    const [store] = React.useState(createTelemetryStore);
    const [floorPlan] = React.useState(createFloorPlan);
    const [history] = React.useState(() => createHistory(store));
    const containerRef = React.useRef<HTMLDivElement | null>(null);
    const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
    const tagsRef = React.useRef<HTMLDivElement | null>(null);
    const sceneRef = React.useRef<Scene | null>(null);
    const publishedRef = React.useRef<{ steps: MissionStep[]; navVersion: number } | null>(null);
    const settingsRef = React.useRef<SceneSettings>({
        viewMode: 'third',
        topOrientation: 'heading',
        mapVisible: true,
        goArmed: false,
    });

    const [viewMode, setViewMode] = useLocalState<ViewMode>(
        VIEW_MODE_KEY,
        (raw) => VIEW_MODES.find((mode) => mode.id === raw)?.id ?? 'third',
        'third',
    );
    const [topOrientation, setTopOrientation] = React.useState<TopOrientation>('heading');
    const [mapVisible, setMapVisible] = React.useState(true);
    const [goArmed, setGoArmed] = React.useState(false);

    const changeViewMode = useEvent((mode: ViewMode) => setViewMode(() => mode));

    const publishGoal = useEvent((point: { x: number; z: number }, append: boolean) => {
        if (link() !== 'connected') {
            L.warn('Mission not sent: NATS is not connected');
            setGoArmed(false);
            return;
        }
        const goto: MissionStep = { type: 'goto', x: Math.round(point.x * 1000) / 1000, z: Math.round(point.z * 1000) / 1000 };
        const published = publishedRef.current;
        const base =
            published != null && published.navVersion === store.nav.version
                ? published.steps
                : remainingMission(store.nav.value);
        const steps = append ? [...base, goto] : [goto];
        nc.publish(MISSION_SUBJECT, JSON.stringify({ steps }));
        publishedRef.current = { steps, navVersion: store.nav.version };
        L.info(append ? 'Mission step appended' : 'Mission sent', { steps });
        if (!append) setGoArmed(false);
    });

    const [stopper] = React.useState(() => createStopper(nc, store));
    const stopRobot = useEvent(() => {
        stopper.stop();
        setGoArmed(false);
    });

    React.useEffect(() => store.connect(nc), [nc, store]);
    React.useEffect(() => stopper.dispose, [stopper]);
    React.useEffect(() => {
        if (!connected) setGoArmed(false);
    }, [connected]);
    React.useEffect(() => history.start(), [history]);
    React.useEffect(() => floorPlan.start(), [floorPlan]);

    React.useLayoutEffect(() => {
        const container = containerRef.current;
        if (container == null) return;
        return engine.attach(container);
    }, [engine]);

    React.useEffect(() => {
        const settings = { viewMode, topOrientation, mapVisible, goArmed };
        settingsRef.current = settings;
        sceneRef.current?.apply(settings);
    }, [viewMode, topOrientation, mapVisible, goArmed]);

    React.useLayoutEffect(() => {
        const container = containerRef.current;
        const canvas = canvasRef.current;
        const tags = tagsRef.current;
        if (container == null || canvas == null || tags == null) return;

        const scene = createScene({
            canvas,
            container,
            tags,
            nc,
            onLink,
            store,
            floorPlan,
            engine,
            settings: settingsRef.current,
            onModeChange: changeViewMode,
            onGoal: publishGoal,
        });
        sceneRef.current = scene;

        return () => {
            sceneRef.current = null;
            scene.dispose();
        };
    }, [nc, onLink, store, floorPlan, engine, changeViewMode, publishGoal]);

    React.useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (isEditable(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
            const key = event.key.toLowerCase();
            if (key === 'g') setGoArmed((armed) => connected && !armed);
            else if (key === 'escape') setGoArmed(false);
            else if (key === 'x') stopRobot();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [stopRobot, connected]);

    return (
        <HudProvider
            engine={engine}
            store={store}
            floorPlan={floorPlan}
            history={history}
            connected={connected}
            stopRobot={stopRobot}>
            <div ref={containerRef} className={rootCss} data-armed={goArmed}>
                <canvas ref={canvasRef} className={canvasCss} />
                <div ref={tagsRef} className={overlayCss} />
                <div className={scanlinesCss} />

                <Compass />
                <div className={cx(hintCss, goArmed && armedHintCss)}>
                    {goArmed ? 'CLICK THE FLOOR TO GO · SHIFT+CLICK TO APPEND A STEP · ESC TO DISARM' : HINTS[viewMode]}
                </div>

                <div className={cx(controlsCss, leftControlsCss)}>
                    <ui.SegmentedControl
                        segments={VIEW_MODES}
                        value={viewMode}
                        onChange={(id) => changeViewMode(id as ViewMode)}
                    />
                </div>
                <div className={cx(controlsCss, rightControlsCss)}>
                    <KeyboardIndicator driver={keyboard} />
                    <LinkIndicator />
                    {viewMode === 'top' && (
                        <ui.SegmentedControl
                            segments={TOP_ORIENTATIONS}
                            value={topOrientation}
                            onChange={(id) => setTopOrientation(id as TopOrientation)}
                        />
                    )}
                    <ui.SegmentedControl
                        segments={MAP_TOGGLE}
                        value={mapVisible ? 'show' : 'hide'}
                        onChange={(id) => setMapVisible(id === 'show')}
                    />
                </div>

                <MinimapPanel armed={goArmed} onGoal={publishGoal} />
                <NavPanel />
                <RoutePanel armed={goArmed} onArm={() => setGoArmed((armed) => !armed)} onCancel={stopRobot} />
                <ExplorePanel />
                <SystemPanel />
                <ZedPanel />
                <PowerPanel />
                <WifiPanel />
                <DrivePanel side='left' />
                <DrivePanel side='right' />
                <SteeringPanel />
                <RoboclawPanel />
                <GamepadPanel />
                <ChatPanel />
            </div>
        </HudProvider>
    );
};

const rootCss = css`
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: #0a0f14;

    &[data-armed='true'] canvas {
        cursor: crosshair;
    }
`;

const canvasCss = css`
    position: absolute;
    inset: 0;
    display: block;
    width: 100%;
    height: 100%;
    touch-action: none;
`;

const overlayCss = css`
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: visible;
    pointer-events: none;
`;

const scanlinesCss = css`
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
        repeating-linear-gradient(180deg, rgba(98, 232, 255, 0.03) 0 1px, transparent 1px 3px),
        radial-gradient(ellipse at center, transparent 60%, rgba(0, 6, 10, 0.55) 100%);
`;

const hintCss = css`
    position: absolute;
    top: 72px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 9px;
    letter-spacing: 0.12em;
    color: var(--hud);
    opacity: 0.45;
    white-space: nowrap;
    pointer-events: none;
`;

const armedHintCss = css`
    color: var(--hud-amber);
    opacity: 1;
    font-weight: 600;
`;

const controlsCss = css`
    position: absolute;
    top: 10px;
    display: flex;
    gap: 6px;
    background: var(--hud-bg);
`;

const leftControlsCss = css`
    left: 12px;
`;

const rightControlsCss = css`
    right: 12px;
`;
