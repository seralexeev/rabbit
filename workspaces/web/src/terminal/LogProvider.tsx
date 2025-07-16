import { css } from '@emotion/css';
import { json } from '@untype/toolbox';
import yaml from 'js-yaml';
import React from 'react';

import { useEvent } from '../hooks.ts';

type LogProviderProps = {
    children?: React.ReactNode;
};

export const LogProvider: React.FC<LogProviderProps> = React.memo(({ children }) => {
    const [expanded, setExpanded] = React.useState(false);
    const ref = React.useRef<HTMLDivElement>(null);
    const scrollToBottom = useEvent(() => {
        if (ref.current) {
            ref.current.scrollTo({
                top: ref.current.scrollHeight,
                behavior: 'smooth',
            });
        }
    });

    React.useLayoutEffect(() => {
        target = ref.current;
        const controller = new AbortController();

        window.addEventListener(
            'keydown',
            (e: KeyboardEvent) => {
                if (!e.ctrlKey || (e.key !== '`' && e.key !== '~' && e.key !== ']')) {
                    return;
                }

                e.preventDefault();
                e.stopPropagation();
                setExpanded((prev) => !prev);
                scrollToBottom();
            },
            { signal: controller.signal },
        );

        L.warn('LogProvider initialized');

        return () => controller.abort();
    }, []);

    return (
        <div
            className={css`
                width: 100%;
                height: 100%;
                position: relative;
            `}>
            <div
                className={css`
                    position: absolute;
                    top: 8px;
                    right: 8px;
                    left: 8px;
                    height: 75%;
                    display: flex;
                    flex-direction: column;
                    transform: translateY(${expanded ? '0' : 'calc(-100% + 40px)'});
                    transition: transform 0.25s ease-in-out;
                    backdrop-filter: blur(5px);
                    background-color: rgba(0, 0, 0, 0.5);
                    border: 1px solid var(--color-primary);
                    z-index: 1000;
                    white-space: pre;
                    padding: 8px;
                `}>
                <div
                    className={css`
                        flex: 1;
                        height: 100%;
                        display: flex;
                        flex-direction: column-reverse;
                        overflow-x: scroll;
                    `}>
                    <div
                        ref={ref}
                        className={css`
                            & > .inf {
                                color: var(--color-primary);
                            }

                            & > .err {
                                color: var(--color-danger);
                            }

                            & > .wrn {
                                color: var(--color-warning);
                            }
                        `}
                    />
                </div>

                {expanded && (
                    <input
                        className={css`
                            display: flex;
                            flex-shrink: 0;
                            width: 100%;
                            overflow-x: auto;
                            background-color: transparent;
                            color: var(--color-text);
                            border: none;
                            font-weight: 500;
                            padding: 0;
                        `}
                        type='text'
                        autoFocus
                    />
                )}
            </div>
            {children}
        </div>
    );
});

export const L = {
    info: (message: string, data?: unknown) => add('INF', message, data),
    warn: (message: string, data?: unknown) => add('WRN', message, data),
    error: (message: string, data?: unknown) => add('ERR', message, data),
};

let target: HTMLElement | null = null;

const add = (level: 'INF' | 'ERR' | 'WRN', message: string, data?: unknown) => {
    console.log(`[${level}] ${message}`, data);

    const date = new Date();
    const hh = date.getHours().toString().padStart(2, '0');
    const mm = date.getMinutes().toString().padStart(2, '0');
    const ss = date.getSeconds().toString().padStart(2, '0');
    const text = `${hh}:${mm}:${ss} ${level} ${message}`;
    raw(text, level.toLowerCase());

    data = json.converter.convert(data);
    if (data != null && typeof data === 'object' && Object.keys(data).length === 0) {
        data = undefined;
    }

    if (data != null) {
        printYaml(data);
    }
};

const raw = (line: string, className?: string) => {
    if (target == null) {
        console.warn('Log target is not set');
        return;
    }

    const entry = document.createElement('div');
    entry.innerText = line;
    if (className != null) {
        entry.className = className;
    }
    target.appendChild(entry);
};

const printYaml = (obj: unknown) => {
    let message = yaml.dump(obj, { skipInvalid: true, lineWidth: 240 }).trim();

    const lines = message.split('\n').map((x, i, ar) => `${getFrameSymbol(i, ar.length)} ` + x);
    for (const line of lines) {
        raw(line, 'obj');
    }
};

const getFrameSymbol = (index: number, length: number) => {
    switch (true) {
        case length === 0:
            return '';
        case length === 1:
            return ' ';
        case index === 0:
            return '│';
        case index === length - 1:
            return '└';
        default:
            return '│';
    }
};
