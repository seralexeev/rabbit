export const slicer = (page: number, pageSize: number) => {
    const limit = pageSize + 1;
    const slice = <T>(items: T[]) => {
        return {
            items: items.slice(0, pageSize),
            hasMore: items.length > pageSize,
        };
    };

    return { limit, offset: pageSize * (page - 1), slice };
};

export const limit_offset = (page: number, page_size: number) => {
    const offset = page_size * (page - 1);
    return { _limit: page_size, _offset: offset };
};

export const to_items = <T extends Record<string, unknown>>(
    rows: Array<T & { total: number }>,
): { items: T[]; total: number } => {
    return {
        items: rows.map(({ total: _, ...rest }) => rest as unknown as T),
        total: rows[0]?.total ?? 0,
    };
};
