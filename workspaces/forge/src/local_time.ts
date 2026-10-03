import { config } from './config.ts';

const UTC_TIME = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)(\.\d+)?Z?$/;

export const TIMEZONE_NOTE = `Times without a suffix are UTC on the robot clock. Every such time has a twin field ending in _local with the same instant in the operator's time zone (${config.operatorTimeZone}, with its abbreviation: AEST is UTC+10, AEDT UTC+11). Quote the _local values to the operator; never convert times yourself.`;

const parts = (ms: number) =>
  Object.fromEntries(
    new Intl.DateTimeFormat('en-AU', {
      timeZone: config.operatorTimeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
      timeZoneName: 'short',
    })
      .formatToParts(ms)
      .map((part) => [part.type, part.value]),
  );

export const localTime = (utc: string) => {
  const match = UTC_TIME.exec(utc.trim());
  if (match == null) {
    return null;
  }
  const [, day, clock, fraction = ''] = match;
  const ms = Date.parse(`${day}T${clock}${fraction.slice(0, 4)}Z`);
  if (Number.isNaN(ms)) {
    return null;
  }
  const local = parts(ms);
  const seconds = (clock ?? '').length > 5 ? `:${local.second}` : '';
  const millis = seconds === '' ? '' : fraction.slice(0, 4);
  return `${local.year}-${local.month}-${local.day} ${local.hour}:${local.minute}${seconds}${millis} ${local.timeZoneName}`;
};

const addLocal = (value: unknown, found: { any: boolean }): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => addLocal(item, found));
  }
  if (typeof value !== 'object' || value == null) {
    return value;
  }
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    result[key] = addLocal(item, found);
    const local =
      typeof item === 'string' && !key.endsWith('_local')
        ? localTime(item)
        : null;
    if (local != null) {
      result[`${key}_local`] = local;
      found.any = true;
    }
  }
  return result;
};

export const withLocalTimes = (value: unknown) => {
  const found = { any: false };
  const converted = addLocal(value, found);
  return found.any &&
    typeof converted === 'object' &&
    converted != null &&
    !Array.isArray(converted)
    ? { timezone: TIMEZONE_NOTE, ...converted }
    : converted;
};
