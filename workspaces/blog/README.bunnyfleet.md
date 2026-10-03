```yaml
id: 1
date: 04-09-2023
media:
    - bf_1-1.jpg
```

The first preview of a new last-mile delivery platform. There's still so much to do 🚀

---

```yaml
id: 2
date: 05-09-2023
media:
    - bf_2-1.jpg
```

Just dropped a new task filter. The `courier_id` field on the task table was a bad idea so introduced a new entity called `run` to model task sequences.

---

```yaml
id: 3
date: 05-09-2023
```

Implementing real-time UIs in not about WebSockets and protocols, it's mostly about state management and cache invalidation. Moreover, WebSockets and pg LISTEN/NOTIFY introduce a new level of complexity and problems. Proper events and polling make the problem almost trivial.

---

```yaml
id: 4
date: 12-09-2023
media:
    - bf_4-1.jpg
```

New object explorer

---

```yaml
id: 5
date: 15-09-2023
```

TIL: You can plug a small Bluetooth device into the OBD port of your car to get many metrics in real-time. Looks like a fun weekend project: building a box (BunnyBox) and sending telemetry from couriers' vehicles using a Raspberry Pi to TimescaleDB 💡

---

```yaml
id: 5
date: 18-09-2023
```

Got access to the public beta of Mapbox Optimization API. Excited to compare it with OR-Tools, VROOM, and jsprit 🐇

---

```yaml
id: 6
date: 18-09-2023
```

A sneak peek of vehicles management right on the dashboard

---

```yaml
id: 6
date: 21-09-2023
```

TIL: [Hologram](https://hologram.io) and [Freematics](https://freematics.com)

---

```yaml
id: 7
date: 10-10-2023
media:
    - bf_7-1.jpg
```

NewProfilePic

---

```yaml
id: 8
date: 30-10-2023
media:
    - bf_8-1.jpg
```

WIP

---

```yaml
id: 9
date: 01-11-2023
media:
    - bf_9-1.jpg
    - bf_9-2.jpg
```

Which side are you on?

---

```yaml
id: 10
date: 02-11-2023
media:
    - bf_10-1.jpg
```

Prototyping route optimization 🚴‍♂️

---

```yaml
id: 11
date: 20-11-2023
media:
    - bf_11-1.jpg
```

WIP: markers and cards refactored

---

```yaml
id: 12
date: 03-12-2023
media:
    - bf_12-1.mp4
```

WIP: just dropped new command menu

---

```yaml
id: 13
date: 06-12-2023
```

It almost works well, but I'm left with more questions than confidence that I understand how it works. I've gone back to classic triggers and a change log table.

---

```yaml
id: 14
date: 06-12-2023
```

It ended with a custom aggressive cache and a react hook for smart batching on the client side, a change queue, and web sockets in combination with LISTEN/NOTIFY at the database level. By the time I got to this, I had the chance to try logical replication and wal2json.

---

```yaml
id: 15
date: 06-12-2023
```

It turns out that creating a convenient real-time cache invalidation mechanism for clients is far from a trivial task. It all started with react-query and cache invalidation after mutations + periodic updates at intervals.

---

```yaml
id: 16
date: 07-12-2023
media:
    - bf_16-1.mp4
```

I think I know why I love working with maps. It's the feeling that you're observing everything from above and can move to any point in just a few seconds.

---

```yaml
id: 17
date: 09-02-2024
media:
    - bf_17-1.mp4
```

Finally found time to return to my project. I slightly refined the UI and added a Command Palette to quickly access frequently used contextual actions. By default, if no object is selected, it includes search and some basic actions and settings.
