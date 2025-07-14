import { gray, green, red, yellow } from 'colorette';
import yaml from 'js-yaml';

import * as assert from './assert.ts';
import { converter } from './json.ts';

export class NiceLogger implements Logger {
    private jsonConverter;
    private level;
    private levelIndex;
    private logger;
    private options;
    private highlight;

    public debug: LogFunction = (message, meta) => this.logImpl('debug', message, meta);
    public info: LogFunction = (message, meta) => this.logImpl('info', message, meta);
    public warn: LogFunction = (message, meta) => this.logImpl('warn', message, meta);
    public error: LogFunction = (message, meta) => this.logImpl('error', message, meta);

    public constructor(options: LoggerOptions = {}, highlight?: (message: string) => string) {
        this.options = options;
        this.highlight = highlight;
        this.level = options.level ?? 'debug';
        this.levelIndex = logLevels.indexOf(this.level);
        this.jsonConverter = options.jsonConverter ?? converter;
        this.logger = options.logger ?? console;

        if (typeof process != 'undefined') {
            process.on('unhandledRejection', (error) => {
                this.error('UnhandledRejection', error);
            });
        }
    }

    public get pretty() {
        return this.options.pretty ?? 'none';
    }

    private logImpl = (level: LogLevel, message: string, data?: unknown) => {
        const logLevel = logLevels.indexOf(level);
        if (logLevel < this.levelIndex) {
            return;
        }

        data = this.jsonConverter.convert(data);
        if (data != null && typeof data === 'object' && Object.keys(data).length === 0) {
            data = undefined;
        }

        const date = new Date();

        if (this.pretty === 'none') {
            this.logger.log(JSON.stringify({ level, message, date, data }));
            return;
        }

        const hh = date.getHours().toString().padStart(2, '0');
        const mm = date.getMinutes().toString().padStart(2, '0');
        const ss = date.getSeconds().toString().padStart(2, '0');
        const levelColor = this.getColor(level);

        this.logger.log(`${gray(`${hh}:${mm}:${ss}`)} ${levelColor(level.toUpperCase())} ${message}`);
        if (data === undefined) {
            return;
        }

        switch (this.pretty) {
            case 'yaml': {
                this.printYaml(data);
                break;
            }
            case 'json': {
                this.logger.log(JSON.stringify(data, null, 2));
                break;
            }
            default: {
                assert.never(this.pretty);
            }
        }

        this.logger.log('');
    };

    private printYaml = (obj: unknown) => {
        let message = yaml.dump(obj, { skipInvalid: true, lineWidth: 240 }).trim();

        if (this.highlight) {
            message = this.highlight(message);
        }

        const lines = message.split('\n').map((x, i, ar) => `${gray(this.getFrameSymbol(i, ar.length))} ` + x);
        for (const line of lines) {
            this.logger.log(line);
        }
    };

    private getFrameSymbol = (index: number, length: number) => {
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

    private getColor = (level: LogLevel) => {
        switch (level) {
            case 'debug':
                return gray;
            case 'info':
                return green;
            case 'warn':
                return yellow;
            case 'error':
                return red;
            default:
                assert.never(level);
        }
    };
}

export type PrettyPrint = 'none' | 'json' | 'yaml';
const logLevels = ['debug', 'info', 'warn', 'error'] as const;

export type LogLevel = (typeof logLevels)[number];
export type JsonConverter = { convert: (value: unknown) => unknown };

type LogFunction = (message: string, meta?: unknown) => void;
export type LoggerOptions = {
    level?: LogLevel;
    pretty?: PrettyPrint;
    jsonConverter?: JsonConverter;
    highlight?: (message: string) => string;
    logger?: {
        log: (...data: unknown[]) => void;
    };
};

export abstract class Logger {
    public abstract debug(message: string, data?: unknown): void;
    public abstract info(message: string, data?: unknown): void;
    public abstract warn(message: string, data?: unknown): void;
    public abstract error(message: string, data?: unknown): void;
}

export const consoleLogger: Logger = {
    debug: (message: string, data?: unknown) => console.debug(message, data),
    info: (message: string, data?: unknown) => console.info(message, data),
    warn: (message: string, data?: unknown) => console.warn(message, data),
    error: (message: string, data?: unknown) => console.error(message, data),
};
