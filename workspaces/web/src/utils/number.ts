export const clamp = (number: number | null | undefined, lower: number, upper: number) => {
    return Math.min(Math.max(number ?? lower, lower), upper);
};
