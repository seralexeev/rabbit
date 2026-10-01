import React from 'react';

import { ChartView } from '../chat/ChartView.tsx';
import type { ChartSpec } from '../chat/outputs.ts';
import type { Signal } from '../perception/history.ts';
import { useHud } from './HudContext.ts';

const REFRESH_MS = 1000;

export type HistorySignals = readonly { key: Signal; label: string; unit?: string; axis?: 'left' | 'right' }[];

type HistoryChartProps = {
    title: string;
    signals: HistorySignals;
    seconds?: number;
    height?: number;
};

export const HistoryChart: React.FC<HistoryChartProps> = ({ title, signals, seconds = 300, height = 260 }) => {
    const { history } = useHud();
    const [chart, setChart] = React.useState<ChartSpec | null>(null);

    React.useEffect(() => {
        const keys = signals.map((signal) => signal.key);
        const refresh = () =>
            setChart({
                type: 'line',
                title,
                x: { field: 't', label: 'TIME', time: true },
                series: signals.map(({ key, label, unit, axis }) => ({
                    field: key,
                    label,
                    ...(unit == null ? {} : { unit }),
                    ...(axis == null ? {} : { axis }),
                })),
                rows: history.rows(keys, seconds),
            });
        refresh();
        const timer = window.setInterval(refresh, REFRESH_MS);
        return () => window.clearInterval(timer);
    }, [history, signals, seconds, title]);

    return chart == null ? null : <ChartView chart={chart} height={height} />;
};
