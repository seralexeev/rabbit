type ForgeErrorOptions = {
  llm?: string;
  internal?: Record<string, unknown>;
  cause?: unknown;
};

export class ForgeError extends Error {
  public readonly llm: string | undefined;
  public readonly internal: Record<string, unknown> | undefined;

  public constructor(message: string, options: ForgeErrorOptions = {}) {
    super(message, { cause: options.cause });
    this.name = 'ForgeError';
    this.llm = options.llm;
    this.internal = options.internal;
  }
}

export const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

export const describeForModel = (error: unknown) =>
  error instanceof ForgeError
    ? { error: error.message, hint: error.llm, ...error.internal }
    : { error: errorMessage(error) };
