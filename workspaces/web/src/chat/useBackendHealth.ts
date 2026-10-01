import React from 'react';

import { HEALTH_URL } from './session.ts';

const POLL_MS = 5000;
const STALE_DATA_S = 30;

type Health = {
    ok: boolean;
    model?: string;
    clickhouse?: boolean;
    latest_data_age_s?: number | null;
    run?: { run_id: string; name: string } | null;
};

type HealthView = { state: 'unknown' | 'ok' | 'degraded' | 'down'; label: string; detail: string };

const describe = (health: Health | null, failed: boolean): HealthView => {
    if (failed) return { state: 'down', label: 'OFFLINE', detail: 'Chat backend unreachable' };
    if (health == null) return { state: 'unknown', label: 'LINKING', detail: 'Checking chat backend' };
    const age = health.latest_data_age_s;
    const detail = [
        `model ${health.model ?? '?'}`,
        `clickhouse ${health.clickhouse === false ? 'down' : 'ok'}`,
        `data age ${age == null ? '?' : `${age.toFixed(0)} s`}`,
        health.run == null ? 'no active run' : `run ${health.run.name}`,
    ].join(' · ');
    const degraded = !health.ok || health.clickhouse === false || (age != null && age > STALE_DATA_S);
    return { state: degraded ? 'degraded' : 'ok', label: (health.model ?? 'ONLINE').toUpperCase(), detail };
};

export const useBackendHealth = () => {
    const [health, setHealth] = React.useState<Health | null>(null);
    const [failed, setFailed] = React.useState(false);

    React.useEffect(() => {
        let cancelled = false;
        const poll = async () => {
            try {
                const response = await fetch(HEALTH_URL);
                const body = (await response.json()) as Health;
                if (cancelled) return;
                setHealth(body);
                setFailed(false);
            } catch {
                if (!cancelled) setFailed(true);
            }
        };
        void poll();
        const timer = window.setInterval(() => void poll(), POLL_MS);
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, []);

    return describe(health, failed);
};
