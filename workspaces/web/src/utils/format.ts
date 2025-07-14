export const distance = (meters: number) => {
    const result = (() => {
        if (meters < 1000) {
            return [meters.toFixed(0), 'm'];
        }

        const km = meters / 1000;
        return [km.toFixed(1), 'km'];
    })();

    return result.join(' ');
};
