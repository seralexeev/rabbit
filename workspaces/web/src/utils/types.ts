export type Json = JsonPrimitive | Json[] | { [key: string]: Json };
export type JsonPrimitive = string | number | boolean | null;

export type OmitNever<T> = {
    [K in keyof T as T[K] extends never ? never : K]: T[K];
};

type PickType<T, K extends AllKeys<T>> = T extends { [k in K]?: any } ? T[K] : never;
export type AllKeys<T> = T extends any ? keyof T : never;
export type Merge<T extends object> = {
    [K in AllKeys<T>]: PickType<T, K>;
};

export type Simplify<T> = { [K in keyof T]: T[K] } & {};
export type IsAny<T> = 0 extends 1 & T ? true : false;

export type OptionalKeys<T> = { [K in keyof T]: undefined extends T[K] ? K : never }[keyof T];
export type RequiredKeys<T> = { [K in keyof T]: undefined extends T[K] ? never : K }[keyof T];
export type MakeOptional<T> = { [K in OptionalKeys<T>]?: T[K] } & { [K in RequiredKeys<T>]: T[K] };

declare const brand: unique symbol;
export type Brand<B> = { readonly [brand]: B };
export type Branded<T, B> = T & Brand<B>;

export const isDate = (obj: unknown): obj is Date => obj instanceof Date;
export const isRegExp = (obj: unknown): obj is RegExp => obj instanceof RegExp;
export const isProxy = (_obj: unknown): boolean => false; // Browsers can't detect proxies
export const isAnyArrayBuffer = (obj: unknown): obj is ArrayBuffer => obj instanceof ArrayBuffer;
export const isArrayBufferView = (obj: unknown): obj is ArrayBufferView => ArrayBuffer.isView(obj);
export const isMap = (obj: unknown): obj is Map<unknown, unknown> => obj instanceof Map;
export const isSet = (obj: unknown): obj is Set<unknown> => obj instanceof Set;
export const isNativeError = (obj: unknown): obj is Error => obj instanceof Error;
