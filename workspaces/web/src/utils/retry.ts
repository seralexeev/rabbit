export const retry = async <T>({
    fn,
    strategy,
    onError,
}: {
    fn: () => Promise<T>;
    strategy: RetryStrategy;
    onError?: (error: unknown) => void;
}) => {
    let attempt = 0;

    while (true) {
        try {
            return await fn();
        } catch (error) {
            onError?.(error);

            const shouldRetry = await strategy(error, attempt);
            if (!shouldRetry) {
                throw error;
            }
        }

        attempt++;
    }
};

interface RetryStrategy {
    (error: unknown, attempt: number): Promise<boolean>;
}

export const constant = ({
    attempts,
    when = () => true,
}: {
    attempts: number;
    when?: (error: Error) => boolean;
}): RetryStrategy => {
    return async (error) => {
        if (error instanceof Error && attempts-- > 0 && when(error)) {
            return true;
        }

        return false;
    };
};
