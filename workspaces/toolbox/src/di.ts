import type { Constructor } from 'type-fest';

export interface ContainerType {
    resolve<T>(token: Constructor<T>): T;
}

export class Container implements ContainerType {
    public resolve;

    public constructor(container: ContainerType) {
        this.resolve = container.resolve.bind(container);
    }
}
