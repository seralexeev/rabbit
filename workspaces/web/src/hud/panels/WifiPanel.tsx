import { css } from '@emotion/css';
import React from 'react';

import { isLive } from '../../perception/Telemetry.ts';
import { HistoryChart, type HistorySignals } from '../HistoryChart.tsx';
import { useHud, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { Rows } from '../Rows.tsx';
import { detailGridCss } from '../detail.ts';
import { fixed, scaled, useFields, writeText } from '../fields.ts';
import { LINK_STALE_MS, SignalBars, band, rttTone, signalBars, signalTone, writeBars } from '../wifi.tsx';

const ROWS = [
    { label: 'SSID' },
    { label: 'SIG' },
    { label: 'PHY' },
    { label: 'RTT' },
    { label: 'UP' },
    { label: 'DOWN' },
    { label: 'DROP' },
] as const;

const WIFI_CHARTS = {
    rtt: [{ key: 'rtt_ms', label: 'ROUTER RTT', unit: 'ms' }],
    signal: [{ key: 'signal_dbm', label: 'SIGNAL', unit: 'dBm' }],
    traffic: [
        { key: 'uplink_kbps', label: 'UPLINK', unit: 'KB/s' },
        { key: 'downlink_kbps', label: 'DOWNLINK', unit: 'KB/s' },
    ],
} as const satisfies Record<string, HistorySignals>;

const kbps = (bytesPerSecond: number | undefined) => fixed(scaled(bytesPerSecond, 1 / 1024), 1, ' KB/s');

export const WifiPanel: React.FC = () => {
    const { store } = useHud();
    const fields = useFields();
    const barsRef = React.useRef<SVGSVGElement | null>(null);

    useHudTick((now) => {
        const wifi = isLive(store.system, now, LINK_STALE_MS) ? store.system.value?.wifi : null;
        const [ssid, signal, phy, rtt, up, down, drops] = fields.current.values;
        if (wifi == null) {
            writeBars(barsRef.current, 0, 'alert');
            writeText(ssid, 'NO TELEMETRY', 'alert');
            return;
        }
        const bars = signalBars(wifi.signal_dbm);
        writeBars(barsRef.current, wifi.connected ? bars : 0, signalTone(bars));
        writeText(
            ssid,
            wifi.connected ? `${wifi.ssid ?? '?'} · ${band(wifi.frequency_mhz)}` : 'DISCONNECTED',
            wifi.connected ? 'normal' : 'alert',
        );
        writeText(signal, wifi.signal_dbm == null ? '—' : `${wifi.signal_dbm} dBm`, signalTone(bars));
        writeText(phy, `↓${fixed(wifi.rx_bitrate_mbps, 0)} ↑${fixed(wifi.tx_bitrate_mbps, 0)} Mb/s`);
        writeText(
            rtt,
            wifi.gateway_rtt_ms == null ? 'NO REPLY' : fixed(wifi.gateway_rtt_ms, 1, ' ms'),
            rttTone(wifi.gateway_rtt_ms),
        );
        writeText(up, kbps(wifi.tx_bytes_per_s));
        writeText(down, kbps(wifi.rx_bytes_per_s));
        const lost =
            (wifi.tx_dropped_per_s ?? 0) +
            (wifi.rx_dropped_per_s ?? 0) +
            (wifi.tx_errors_per_s ?? 0) +
            (wifi.rx_errors_per_s ?? 0);
        writeText(
            drops,
            `${(wifi.tx_dropped ?? 0) + (wifi.rx_dropped ?? 0)} / ${(wifi.tx_errors ?? 0) + (wifi.rx_errors ?? 0)} err`,
            lost > 0 ? 'warn' : 'normal',
        );
    });

    return (
        <HudPanel
            id='wifi'
            code='WF'
            title='WIFI // LINK'
            source='system'
            detail={
                <div className={detailGridCss}>
                    <HistoryChart title='ROUTER RTT' signals={WIFI_CHARTS.rtt} />
                    <HistoryChart title='SIGNAL' signals={WIFI_CHARTS.signal} />
                    <HistoryChart title='TRAFFIC' signals={WIFI_CHARTS.traffic} />
                </div>
            }>
            <div className={barsRowCss}>
                <SignalBars ref={barsRef} size={18} />
            </div>
            <Rows rows={ROWS} fields={fields} />
        </HudPanel>
    );
};

const barsRowCss = css`
    display: flex;
    justify-content: flex-end;
    margin: -2px 0 2px;
`;
