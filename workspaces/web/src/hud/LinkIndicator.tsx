import { css, cx } from '@emotion/css';
import React from 'react';

import { useNats } from '../app/NatsProvider.tsx';
import { isLive } from '../perception/Telemetry.ts';
import { useHud, useHudTick } from './HudContext.ts';
import { fixed, toneCss, writeText } from './fields.ts';
import { LINK_STALE_MS, SignalBars, rttTone, signalBars, signalTone, writeBars } from './wifi.tsx';

export const LinkIndicator: React.FC = () => {
    const { store } = useHud();
    const { link } = useNats();
    const stateRef = React.useRef<HTMLSpanElement | null>(null);
    const rttRef = React.useRef<HTMLSpanElement | null>(null);
    const barsRef = React.useRef<SVGSVGElement | null>(null);

    useHudTick((now) => {
        const nats = link();
        const live = nats === 'connected' && isLive(store.system, now, LINK_STALE_MS);
        const wifi = live ? store.system.value?.wifi : null;
        const label =
            nats === 'reconnecting'
                ? 'NATS RECONNECTING'
                : nats === 'disconnected'
                  ? 'NATS DOWN'
                  : live
                    ? 'LINK'
                    : 'LINK DEGRADED';
        writeText(stateRef.current, label, live ? 'good' : 'alert');
        const bars = wifi?.connected === true ? signalBars(wifi.signal_dbm) : 0;
        writeBars(barsRef.current, bars, wifi == null ? 'alert' : signalTone(bars));
        writeText(rttRef.current, fixed(wifi?.gateway_rtt_ms, 0, ' ms'), rttTone(wifi?.gateway_rtt_ms));
    });

    return (
        <div className={rootCss} title='NATS telemetry freshness, WiFi signal and router round-trip'>
            <span ref={stateRef} className={cx(toneCss, labelCss)}>
                LINK
            </span>
            <SignalBars ref={barsRef} />
            <span ref={rttRef} className={cx(toneCss, labelCss)}>
                — ms
            </span>
        </div>
    );
};

const rootCss = css`
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 8px;
    border: 1px solid var(--hud-faint);
    font-size: 10px;
    letter-spacing: 0.08em;
`;

const labelCss = css`
    white-space: nowrap;
`;
