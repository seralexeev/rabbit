import React from 'react';

import type { HistorySignals } from '../HistoryChart.tsx';
import { HistoryChart } from '../HistoryChart.tsx';
import { useHud, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { Rows } from '../Rows.tsx';
import { detailGridCss } from '../detail.ts';
import { above, below, fixed, scaled, signed, useFields, writeBar, writeText } from '../fields.ts';

const MAX_STEERING_DEG = 30;
const MOTOR_MAX_A = 4;
const SUPPLY_NOMINAL_V = 12;

const DRIVE_CHARTS = {
    left: {
        command: [
            { key: 'left_cmd', label: 'COMMAND', unit: '%' },
            { key: 'left_pwm', label: 'PWM', unit: '%' },
        ],
        motion: [
            { key: 'left_cmd', label: 'COMMAND', unit: '%' },
            { key: 'speed', label: 'GROUND SPEED', unit: 'm/s', axis: 'right' },
        ],
        current: [{ key: 'left_a', label: 'CURRENT', unit: 'A' }],
    },
    right: {
        command: [
            { key: 'right_cmd', label: 'COMMAND', unit: '%' },
            { key: 'right_pwm', label: 'PWM', unit: '%' },
        ],
        motion: [
            { key: 'right_cmd', label: 'COMMAND', unit: '%' },
            { key: 'speed', label: 'GROUND SPEED', unit: 'm/s', axis: 'right' },
        ],
        current: [{ key: 'right_a', label: 'CURRENT', unit: 'A' }],
    },
} as const satisfies Record<string, Record<string, HistorySignals>>;

const STEERING_CHART: HistorySignals = [{ key: 'steer_deg', label: 'ANGLE', unit: '°' }];
const ROBOCLAW_CHARTS = {
    supply: [{ key: 'supply_v', label: 'SUPPLY', unit: 'V' }],
    temperature: [{ key: 'roboclaw_c', label: 'BOARD', unit: '°C' }],
    current: [
        { key: 'left_a', label: 'LEFT', unit: 'A' },
        { key: 'right_a', label: 'RIGHT', unit: 'A' },
    ],
} as const satisfies Record<string, HistorySignals>;
const POWER_CHARTS = {
    battery: [
        { key: 'battery_v', label: 'VOLTAGE', unit: 'V' },
        { key: 'battery_a', label: 'CURRENT', unit: 'A', axis: 'right' },
    ],
    power: [{ key: 'battery_w', label: 'POWER', unit: 'W' }],
    charge: [{ key: 'charge_pct', label: 'CHARGE', unit: '%' }],
    rail: [
        { key: 'rail_v', label: '6V RAIL', unit: 'V' },
        { key: 'rail_a', label: '6V CURRENT', unit: 'A', axis: 'right' },
    ],
} as const satisfies Record<string, HistorySignals>;

const DRIVE_ROWS = [
    { label: 'CMD', bar: 'center' },
    { label: 'PWM', bar: 'center' },
    { label: 'AMP', bar: 'fill' },
] as const;

export const DrivePanel: React.FC<{ side: 'left' | 'right' }> = ({ side }) => {
    const { store } = useHud();
    const fields = useFields();

    useHudTick(() => {
        const motor = store.roboclaw.value?.[side];
        if (motor == null) return;
        const { values, bars } = fields.current;
        const current = motor.current == null ? null : Math.abs(motor.current);
        writeText(values[0], signed(scaled(motor.command, 100), 0, '%'));
        writeBar(bars[0], motor.command ?? 0);
        writeText(values[1], signed(scaled(motor.pwm, 100), 0, '%'));
        writeBar(bars[1], motor.pwm ?? 0);
        writeText(values[2], fixed(current, 2, ' A'), above(current, 2.5, MOTOR_MAX_A));
        writeBar(bars[2], (current ?? 0) / MOTOR_MAX_A);
    });

    return (
        <HudPanel
            id={side === 'left' ? 'drive-left' : 'drive-right'}
            code={side === 'left' ? 'DL' : 'DR'}
            title={side === 'left' ? 'L-REAR DRIVE' : 'R-REAR DRIVE'}
            source='roboclaw'
            detail={
                <div className={detailGridCss}>
                    <HistoryChart title='COMMAND VS PWM' signals={DRIVE_CHARTS[side].command} />
                    <HistoryChart title='COMMAND VS GROUND SPEED' signals={DRIVE_CHARTS[side].motion} />
                    <HistoryChart title='MOTOR CURRENT' signals={DRIVE_CHARTS[side].current} />
                </div>
            }>
            <Rows rows={DRIVE_ROWS} fields={fields} />
        </HudPanel>
    );
};

const STEERING_ROWS = [{ label: 'ANG', bar: 'center' }, { label: 'PLS' }] as const;

export const SteeringPanel: React.FC = () => {
    const { store } = useHud();
    const fields = useFields();

    useHudTick(() => {
        const steering = store.steering.value;
        if (steering == null) return;
        const degrees = scaled(steering.angle, MAX_STEERING_DEG);
        const direction = degrees == null || Math.abs(degrees) < 0.05 ? 'C' : degrees > 0 ? 'R' : 'L';
        writeText(fields.current.values[0], `${direction} ${fixed(degrees == null ? null : Math.abs(degrees), 1, '°')}`);
        writeBar(fields.current.bars[0], steering.angle ?? 0);
        writeText(fields.current.values[1], fixed(steering.pulse_us, 0, ' µs'));
    });

    return (
        <HudPanel
            id='steering'
            code='ST'
            title='STEERING'
            source='steering'
            detail={<HistoryChart title='STEERING ANGLE' signals={STEERING_CHART} height={320} />}>
            <Rows rows={STEERING_ROWS} fields={fields} />
        </HudPanel>
    );
};

const ROBOCLAW_ROWS = [
    { label: 'SUP', bar: 'fill' },
    { label: 'TMP' },
    { label: 'AMP', bar: 'fill' },
    { label: 'STAT' },
    { label: 'ERR' },
] as const;

export const RoboclawPanel: React.FC = () => {
    const { store } = useHud();
    const fields = useFields();

    useHudTick(() => {
        const roboclaw = store.roboclaw.value;
        if (roboclaw == null) return;
        const { values, bars } = fields.current;
        const supply = roboclaw.supply_voltage;
        const deviation = supply == null ? null : Math.abs(supply - SUPPLY_NOMINAL_V);
        writeText(values[0], fixed(supply, 2, ' V'), above(deviation, 0.8, 1.5));
        writeBar(bars[0], (supply ?? 0) / (SUPPLY_NOMINAL_V * 1.25));
        writeText(values[1], fixed(roboclaw.temperature, 1, '°C'), above(roboclaw.temperature, 60, 80));
        const current = Math.abs(roboclaw.left.current ?? 0) + Math.abs(roboclaw.right.current ?? 0);
        writeText(values[2], fixed(current, 2, ' A'), above(current, 5, 2 * MOTOR_MAX_A));
        writeBar(bars[2], current / (2 * MOTOR_MAX_A));
        writeText(
            values[3],
            roboclaw.status == null ? '—' : `0x${roboclaw.status.toString(16).padStart(4, '0')}`,
            roboclaw.status == null || roboclaw.status === 0 ? 'normal' : 'warn',
        );
        writeText(values[4], fixed(roboclaw.errors, 0), (roboclaw.errors ?? 0) > 0 ? 'warn' : 'normal');
    });

    return (
        <HudPanel
            id='roboclaw'
            code='RC'
            title='ROBOCLAW // 12V'
            source='roboclaw'
            detail={
                <div className={detailGridCss}>
                    <HistoryChart title='12 V SUPPLY' signals={ROBOCLAW_CHARTS.supply} />
                    <HistoryChart title='BOARD TEMPERATURE' signals={ROBOCLAW_CHARTS.temperature} />
                    <HistoryChart title='MOTOR CURRENT' signals={ROBOCLAW_CHARTS.current} />
                </div>
            }>
            <Rows rows={ROBOCLAW_ROWS} fields={fields} />
        </HudPanel>
    );
};

const POWER_ROWS = [
    { label: 'CHG', bar: 'fill' },
    { label: 'BAT' },
    { label: 'CUR' },
    { label: 'PWR' },
    { label: '6V' },
    { label: '6V I' },
] as const;

export const PowerPanel: React.FC = () => {
    const { store } = useHud();
    const fields = useFields();

    useHudTick(() => {
        const ina = store.ina.value;
        if (ina == null) return;
        const { values, bars } = fields.current;
        const battery = ina.channels.find((channel) => channel.ch === 1);
        const rail = ina.channels.find((channel) => channel.ch === 2);
        writeText(values[0], fixed(ina.battery_charge_pct, 0, '%'), below(ina.battery_charge_pct, 25, 10));
        writeBar(bars[0], (ina.battery_charge_pct ?? 0) / 100);
        if (battery != null) {
            writeText(values[1], fixed(battery.voltage, 2, ' V'), below(battery.voltage, 13.6, 13.2));
            writeText(values[2], fixed(battery.current, 2, ' A'));
            writeText(values[3], fixed(battery.power, 1, ' W'));
        }
        if (rail != null) {
            writeText(values[4], fixed(rail.voltage, 2, ' V'));
            writeText(values[5], `${fixed(rail.current, 2, ' A')} · ${fixed(rail.power, 1, ' W')}`);
        }
    });

    return (
        <HudPanel
            id='power'
            code='PW'
            title='POWER // 4S 99WH'
            source='ina'
            detail={
                <div className={detailGridCss}>
                    <HistoryChart title='BATTERY VOLTAGE / CURRENT' signals={POWER_CHARTS.battery} />
                    <HistoryChart title='BATTERY POWER' signals={POWER_CHARTS.power} />
                    <HistoryChart title='STATE OF CHARGE' signals={POWER_CHARTS.charge} />
                    <HistoryChart title='6 V RAIL' signals={POWER_CHARTS.rail} />
                </div>
            }>
            <Rows rows={POWER_ROWS} fields={fields} />
        </HudPanel>
    );
};
