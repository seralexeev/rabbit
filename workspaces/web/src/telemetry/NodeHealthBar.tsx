import { css } from '@emotion/css';
import React from 'react';

import { useNats } from '../app/NatsProvider.tsx';
import { ui } from '../ui/index.ts';

const INA_SUBJECT = 'rabbit.ina';

type InaChannel = {
    ch: number;
    voltage: number;
    current: number;
    power: number;
};

type InaData = {
    channels: InaChannel[];
};

export const NodeHealthBar: React.FC = () => {
    const { nc } = useNats();
    const [ina, setIna] = React.useState<InaData | null>(null);

    React.useEffect(() => {
        const sub = nc.subscribe(INA_SUBJECT, {
            callback: (_, msg) => {
                try { setIna(msg.json() as InaData); } catch {}
            },
        });
        return () => { sub.unsubscribe(); };
    }, [nc]);

    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                gap: 8px;
                font-variant-numeric: tabular-nums;
            `}>
            <ui.Card header='POWER RAILS'>
                <Panel>
                    {ina == null ? (
                        <ui.Placeholder label='OFFLINE' />
                    ) : (
                        <>
                            {ina.channels.map((ch) => (
                                <div key={ch.ch}>
                                    <Row label={`CH${ch.ch}`} value={`${ch.voltage.toFixed(2)}V`} />
                                    <Row label='' value={`${(ch.current * 1000).toFixed(0)}mA · ${ch.power.toFixed(2)}W`} sub />
                                </div>
                            ))}
                            <Row
                                label='TOTAL'
                                value={`${ina.channels.reduce((s, c) => s + c.power, 0).toFixed(2)}W`}
                                ok
                            />
                        </>
                    )}
                </Panel>
            </ui.Card>
        </div>
    );
};

const Panel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <div
        className={css`
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 3px;
        `}>
        {children}
    </div>
);

const Row: React.FC<{ label: string; value: string; warn?: boolean; ok?: boolean; sub?: boolean }> = ({
    label,
    value,
    warn,
    ok,
    sub,
}) => (
    <div
        className={css`
            display: flex;
            justify-content: space-between;
            font-size: ${sub ? '10px' : '11px'};
        `}>
        <span
            className={css`
                opacity: ${sub ? 0.35 : 0.5};
            `}>
            {label}
        </span>
        <span
            className={css`
                color: ${warn ? '#ff5533' : ok ? '#00ff41' : 'inherit'};
                ${warn ? 'text-shadow: 0 0 6px #ff553344;' : ''}
                ${ok ? 'text-shadow: 0 0 6px #00ff4144;' : ''}
            `}>
            {value}
        </span>
    </div>
);
