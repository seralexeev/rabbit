export const log = (message: string, fields: Record<string, unknown> = {}) => {
  const time = new Date().toISOString().slice(11, 23);
  const details =
    Object.keys(fields).length > 0 ? ` ${JSON.stringify(fields)}` : '';
  process.stderr.write(`${time} ${message}${details}\n`);
};
