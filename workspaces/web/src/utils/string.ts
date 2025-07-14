export const trimToNull = (value: string | null | undefined) => {
    return value?.trim() || null;
};

export const trimToUndefined = (value: string | null | undefined) => {
    return value?.trim() || undefined;
};

export const trimToEmpty = (value: string | null | undefined) => {
    return value?.trim() || '';
};
