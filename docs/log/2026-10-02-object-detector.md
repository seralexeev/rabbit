# Object detector (YOLOE) and object memory in Forge

Date: 2026-10-02, 06:33–13:07 UTC, plus a Forge fix at 22:26 UTC. Built by a parallel agent session; uncommitted at the time of writing.

## Goal

Label furniture and people while driving (table, chair, nightstand, fridge, person…), with correct 3D positions in the HUD, and let the agent answer "where is the TV, when was a person seen".

## Options considered

| Option | Verdict |
|---|---|
| ZED SDK custom ONNX detector (`CUSTOM_YOLOLIKE_BOX_OBJECTS`): the SDK builds the TensorRT engine, computes 3D boxes from depth and tracks in world coordinates | chosen |
| ZED built-in `MULTI_CLASS_BOX` | no furniture classes |
| COCO / Objects365 YOLO | wrong labels from a 13 cm high viewpoint (TV stand → "bench", TV → "blackboard") |
| Gemini Flash / Flash-Lite | good boxes, 0.2–4 s per frame: for rare questions, not live |
| OpenAI mini/nano vision | seconds per frame, unreliable boxes |
| TypeSafe Jev | text only |

Models compared on robot frames: yoloe-11s/m/l, yoloe-26s/m/l, yoloe-v8l. **yoloe-26m** with 58 household classes baked into the ONNX (including prompt-tuned names such as "low wooden cabinet", which found the TV stand) was best (`workspaces/rabbit/tools/export_detector.py`; the model lives in `data/detector/`, not in git).

## Integration

- `lib/detector.py`, `zed.py`: detection on every 3rd, later every 4th frame; results on `rabbit.zed.objects` (id, label, confidence, position, dimensions, 8 world corners, normalised 2D box, `moving`).
- The first TensorRT engine build took 544.8 s inside `rabbit-zed`, blocked the event loop, missed NATS heartbeats and restarted the container once. From cache it loads in 1.4 s; the enable call now runs in a thread.
- Cost: GPU 21 % → 36.5 % at 10 Hz detection; about 2 ms per retrieve.
- A person labelled "lamp" looked like a class-index mismatch; an SVO replay and offline comparison showed a transient tracker label.

## Filtering (2026-10-02 13:02–13:07 UTC)

The 3D view showed objects the video did not: a "laptop" that was sheet music on the piano, a desk as a 2.6 × 2.6 m cube, about 15 junk tracks in 30 s.

| Cause | Fix |
|---|---|
| confidence threshold 20 % for all classes | 35 %, and 50 % for small classes the open-vocabulary model hallucinates (laptop, cup, bottle, kettle, monitor, clock, …) |
| one- or two-frame detections published | `TrackConfirmer`: publish a track after 3 detections (on the robot, so planner and Forge get only confirmed objects) |
| for custom YOLO-like models the SDK makes box depth = width | per-class depth along the view ray (door 0.1 m, TV 0.15, desk 0.75, fridge 0.7, …) |
| HUD kept every id for 2 minutes; the SDK issues a new id on every re-detection (~480 ids for ~10 objects in 10 min) | merge same-class detections by proximity; forget an object in view and undetected for 2.5 s |

After: 4 stable objects in 30 s, matching the video. Downside: the door (27–55 %) no longer always appears. Pillows sometimes get 2–3 m boxes from depth errors (a box-size limit was offered, not done).

## Forge

- Table `forge.objects` (one row per object per detection frame), slabs `objects_seen` (inventory: same class in the same ~0.75 m cell merged, because ids restart) and `object_sightings` (time series), an `objects` section in `robot_status`, landmarks in the chat's top-down widgets. A `;` inside a column COMMENT broke the multi-query split when creating the table.
- Object lookups ignore detections made while the camera was INITIALIZING/SEARCHING (temporary frame): an early "refrigerator" at (1.44, −2.61) was such an artefact.
- 2026-10-02 22:25 UTC: the agent said the robot had never seen the fridge on the current map. After the morning map reset there were only 6 fridge detections (max confidence 61 %): the robot passed quickly, 5–6 m away, with detection on every 4th frame, and clusters needed ≥ 10 frames. Now `frames >= 10 || (frames >= 3 && confidence >= 55)`.

## Open

Fine-tuning on a few hundred robot frames labelled by a cloud model; a box-size limit; a CLIP/SigLIP embedding per object (from the SLAM survey).
