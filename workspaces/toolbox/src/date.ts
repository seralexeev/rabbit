import * as fns from 'date-fns';

export type DateFormat = 'HH:mm:ss dd-MM-yyyy' | 'yyyy-MM-dd' | 'd MMM HH:mm';

export const format = (value: Date | number | string, format: DateFormat = 'HH:mm:ss dd-MM-yyyy') => {
    return fns.format(value, format);
};
