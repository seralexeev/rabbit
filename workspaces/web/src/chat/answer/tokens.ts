export type Token =
    | { kind: 'status'; tone: 'info' | 'ok' | 'warn' | 'alert'; text: string }
    | { kind: 'kpi'; label: string; value: string }
    | { kind: 'spark'; values: number[] }
    | { kind: 'ref'; ref: string; target: string; params: [string, string][] }
    | { kind: 'next'; text: string };

const TOKEN = /^(spark|info|ok|warn|alert|kpi|ref|next):(.+)$/s;

export const parseToken = (text: string): Token | null => {
    const match = TOKEN.exec(text.trim());
    if (match == null) return null;
    const [, kind = '', body = ''] = match;
    const value = body.trim();
    if (value === '') return null;
    if (kind === 'info' || kind === 'ok' || kind === 'warn' || kind === 'alert')
        return { kind: 'status', tone: kind, text: value };
    if (kind === 'next') return { kind: 'next', text: value };
    if (kind === 'spark') {
        const values = value
            .split(/[\s,;]+/)
            .filter((part) => part !== '')
            .map(Number);
        return values.length >= 2 && values.every((number) => Number.isFinite(number)) ? { kind: 'spark', values } : null;
    }
    if (kind === 'kpi') {
        const separator = value.indexOf('=');
        return separator <= 0
            ? null
            : { kind: 'kpi', label: value.slice(0, separator).trim(), value: value.slice(separator + 1).trim() };
    }
    const colon = value.indexOf(':');
    if (colon <= 0) return null;
    const ref = value.slice(0, colon);
    const rest = value.slice(colon + 1);
    const question = rest.indexOf('?');
    const target = (question < 0 ? rest : rest.slice(0, question)).trim();
    if (target === '') return null;
    const params = question < 0 ? [] : [...new URLSearchParams(rest.slice(question + 1)).entries()];
    return { kind: 'ref', ref, target, params };
};

const clock = (value: string) => {
    const match = /(\d{2}:\d{2}(:\d{2})?)/.exec(value);
    return match?.[1] ?? value;
};

export const refLabel = (token: Extract<Token, { kind: 'ref' }>) => {
    const param = (name: string) => token.params.find(([key]) => key === name)?.[1];
    const from = param('from');
    const to = param('to');
    const at = param('at');
    const when =
        at != null
            ? ` @${clock(at)}`
            : from != null && to != null
              ? ` ${clock(from)}–${clock(to)}`
              : from != null
                ? ` from ${clock(from)}`
                : '';
    const names: Record<string, string> = {
        slab: 'SLAB',
        detect: 'ANOMALY',
        investigate: 'TRACE',
        run: 'RUN',
        chart: 'CHART',
        graph: 'GRAPH',
    };
    const target = token.ref === 'run' ? token.target.replace(/^\d{8}-\d{6}-/, '') : token.target;
    return `${names[token.ref] ?? token.ref.toUpperCase()} ${target}${when}`;
};

export const refQuestion = (token: Extract<Token, { kind: 'ref' }>) => {
    const params = token.params.map(([key, value]) => `${key}=${value}`).join(', ');
    const withParams = params === '' ? '' : ` with ${params}`;
    switch (token.ref) {
        case 'slab':
            return `Re-run the ${token.target} slab${withParams} and show the result`;
        case 'detect':
            return `Detect anomalies in ${token.target.split(',').join(', ')}${withParams}`;
        case 'investigate':
            return `Investigate ${token.target}${withParams}`;
        case 'run':
            return `Summarize run ${token.target}`;
        default:
            return `Show the ${token.ref} ${token.target} again`;
    }
};
