type Options = {
    cause?: unknown;
    internal?: unknown;
    public?: { message?: string; data?: unknown };
};

export class InternalError extends Error {
    public public;
    public internal;

    public constructor(message: string, options?: Options) {
        super(message, {
            cause: options?.cause as Error,
        });

        this.public = options?.public;
        this.internal = options?.internal;
    }

    public shouldLog() {
        return true;
    }

    public get code() {
        return 500;
    }

    public get type() {
        return this.constructor.name;
    }
}

export class UnreachableError extends InternalError {
    public value;

    public constructor(value: never, message?: string) {
        super('Unreachable code reached', {
            internal: { value, message },
        });

        this.value = value;
    }
}

export class InvalidOperationError extends InternalError {
    public override get code() {
        return 400;
    }
}

export class BadRequestError extends InternalError {
    public override get code() {
        return 400;
    }
}

export class NotFoundError extends InternalError {
    public override get code() {
        return 400;
    }

    public static throw(message: string = 'Not Found', options?: Options): never {
        throw new NotFoundError(message, options);
    }
}

export class UnauthorizedError extends InternalError {
    public override get code() {
        return 401;
    }

    public override shouldLog() {
        return false;
    }
}

export class ForbiddenError extends InternalError {
    public override get code() {
        return 400;
    }
}
