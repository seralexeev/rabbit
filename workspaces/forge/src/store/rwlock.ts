type Waiter = { exclusive: boolean; resolve: () => void };

export class RwLock {
  private shared = 0;
  private held = false;
  private readonly queue: Waiter[] = [];

  public async read<T>(fn: () => Promise<T>): Promise<T> {
    if (this.held || this.queue.length > 0) {
      await new Promise<void>((resolve) => {
        this.queue.push({ exclusive: false, resolve });
      });
    } else {
      this.shared += 1;
    }
    try {
      return await fn();
    } finally {
      this.shared -= 1;
      this.next();
    }
  }

  public async write<T>(fn: () => Promise<T> | T): Promise<T> {
    if (this.held || this.shared > 0 || this.queue.length > 0) {
      await new Promise<void>((resolve) => {
        this.queue.push({ exclusive: true, resolve });
      });
    } else {
      this.held = true;
    }
    try {
      return await fn();
    } finally {
      this.held = false;
      this.next();
    }
  }

  private next() {
    if (this.held) {
      return;
    }
    while (this.queue.length > 0) {
      const head = this.queue[0];
      if (head == null) {
        return;
      }
      if (head.exclusive) {
        if (this.shared > 0) {
          return;
        }
        this.queue.shift();
        this.held = true;
        head.resolve();
        return;
      }
      this.queue.shift();
      this.shared += 1;
      head.resolve();
    }
  }
}
