import { stringify } from 'yaml';

import { config } from '../config.ts';
import { listRuns } from '../runs.ts';
import { searchSlabs } from '../slabs/search_slabs.ts';

const zoneParts = (now: Date, timeZoneName: 'short' | 'longOffset') =>
  Object.fromEntries(
    new Intl.DateTimeFormat('en-AU', {
      timeZone: config.operatorTimeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
      timeZoneName,
    })
      .formatToParts(now)
      .map((part) => [part.type, part.value]),
  );

export const operatorClock = (now = new Date()) => {
  const local = zoneParts(now, 'short');
  const offset =
    zoneParts(now, 'longOffset').timeZoneName?.replace('GMT', 'UTC') ?? 'UTC';
  const utc = now.toISOString().slice(0, 16).replace('T', ' ');
  return `The operator is in ${config.operatorTimeZone}. Now it is ${local.year}-${local.month}-${local.day} ${local.hour}:${local.minute} ${local.timeZoneName} (${offset}), which is ${utc} UTC.`;
};

export const groundingContext = async (question: string) => {
  const runs = await listRuns(10);
  const slabs = searchSlabs(question, 5);
  return `# Operator clock\n\n${operatorClock()}\n\n# Recent runs\n\n${stringify(runs)}\n# Nearest slabs\n\n${stringify(slabs)}`;
};
