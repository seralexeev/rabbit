# Lessons

Short rules learned the hard way on this robot, each with the reason. Details are in `log/`.

## Robot and camera

- **Never attach gdb to `rabbit-zed`.** A ptrace attach froze the camera for about 2 minutes and the process stayed stopped after the tool timed out; gdb in a container on the Jetson hung over 10 minutes loading CUDA/TensorRT symbols. Use `py-spy dump --nonblocking` and `top -H`.
- **Don't run `systemctl isolate` or `nvpmodel -m` on the live robot.** `isolate` re-ran `nvpmodel.service`, which reset the `jetson_clocks` floors: 85 minutes of low clocks that looked like over-current throttling.
- **nvpmodel ids are board-specific.** `-m 0` is 15 W on this Orin Nano; MAXN_SUPER is 2.
- **Check the clocks before blaming code.** Under schedutil the CPU sat at 730 of 1728 MHz and the camera could not hold 30 fps.
- **Pin IRQs by device-tree hwirq, not by name.** The UART is not in `/proc/interrupts` until it is opened, so name-based pinning silently did nothing after every boot.
- **An area file saved while LOST breaks relocalization.** Save the SDK area map only when localized and in mapping mode; never save a failed session over a good map.
- **Count relocalization only after a localized status holds for 10 s.** The SDK reports KNOWN_MAP, re-initialises 5–8 s later, and LOST is not relocalized.
- **Sanity-check every SDK pose.** For a few seconds after relocalizing GEN_3 returns millimetres instead of metres; those poses corrupted a map and produced kilometre "jumps".
- **Base give-up rules on distance travelled, not time or `camera_moving_state`.** The SDK says MOVING while the robot stands still; timers discarded good maps.
- **Restart the camera process after a tracking failure; don't re-enable tracking in-process.** Re-enabling left the SDK broken and produced poses tens of metres away.
- **Don't switch to localization in front of a blank wall.** It stayed INITIALIZING for over an hour; switch only with an open view and after being localized for a while.
- **GEN_3 lifelong mapping leaks keyframes in SDK 5.5.0.** CPU grows on a standing robot; localize by default, map only for new areas.
- **Don't cap the ZED compute fps to save CPU.** It saved nothing and added about 55 ms of pose latency.
- **Keep heavy native calls out of the camera loop.** The mesh filter held the GIL for up to 2 s; pyzed calls hold the GIL, so per-update work must scale with what changed.
- **Long SDK initialisation (TensorRT engine build, 9 minutes) belongs in a thread.** On the event loop it missed NATS heartbeats and restarted the container.
- **Copy GPU images to the host before indexing them in C++.** Reading the ESDF slice from device memory segfaulted.
- **Do a full ESDF update after loading a map.** Incremental updates ignore loaded blocks and the grid came out empty.
- **Guard the map against pose jumps.** Skip integration above 1.5 m/s, clear blocks beyond 50 m, window the grid; debris 1.5 km away made a message too big to publish.
- **Integrate periodically while static.** Otherwise a freshly reset map stays empty.
- **Stop distances must be outside the depth blind zone, and blind-zone memory must not expire.** At 0.15 m with 4 s memory the robot drove into a wall; at the same time a stuck phantom point must be released eventually (about 30 s).
- **Use the k-th nearest point per scan sector.** Single flying pixels near the lens stopped the robot.
- **Measure obstacle height from a per-frame floor plane.** 1° of tilt is 5 cm at 3 m; the floor was reported as contact.
- **A floor estimate must not follow the robot onto a table.** Adopt a new level only after driving on it.
- **Track Ackermann paths by the rear axle.** Tracking the camera point 0.18 m ahead made reverse drift sideways.
- **Calibrate curvature per side and use the same tables everywhere.** Left and right turns differ (servo neutral).
- **IMU bump thresholds need margin over normal start jerk.** Launch jerk reached 3.49 m/s² against a 3.5 threshold.
- **Benchmark on a recorded SVO, on a stationary robot, with nothing else running.** Live numbers were contaminated by driving from the public HUD and by other sessions.
- **Separate odometry from the global fix.** With nav on `odom`, map corrections no longer jerk the steering.

## Hardware and OS

- **Use `/dev/serial/by-id/...` for USB serial, and catch `termios.error`.** ttyACM numbers change after a replug or reboot.
- **Turn off Wi-Fi power save in the NetworkManager connection itself.** The Realtek driver re-enabled it after each reconnect; global settings did not stick.
- **The rtl88x2ce driver ignores the country code.** Power comes from its limit table.
- **Make Wi-Fi changes with an automatic rollback.** Wi-Fi is the robot's only link.
- **Take device timestamps through an offset to the system clock.** After an NTP step at boot the camera clock was 5.7 minutes behind.
- **The RTC does not keep time and the board is often powered off hard.** Expect wrong timestamps right after boot.
- **Fit printed parts to the robot, not to `model/chassis.step`.** The kit model has 50 mm standoffs and two decks; the robot has three (deck 1, the body PCB, deck 3 on 45 + 45 mm), so deck 3 is ~42 mm higher and the PCB hangs ~3 mm over the ToF heads. The owner's V-mount plate is twice as long as assumed. `cad/brackets/assembly.py` rebuilds the stack with the PCB STEP and boxes for the ZED, V-mount plate and battery; check against a current photo too.
- **Fill KiCad zones with `kicad-cli pcb drc --refill-zones --save-board`, not the Python `ZONE_FILLER`.** From a standalone script the filler ignored hole and board-edge clearances (`log/2026-10-03-body-pcb.md`).
- **On a Raspberry Pi a GPIO output outlives the process that drove it.** Raspberry Pi kernels 6.6 and 6.12 set `pinctrl_bcm2835.persist_gpio_outputs` to true, so a crashed process leaves the pin at its last level; a fail-safe "held high while alive" line needs `pinctrl_bcm2835.persist_gpio_outputs=n` on the kernel command line, a check of `/sys/module/pinctrl_bcm2835/parameters/persist_gpio_outputs` before raising it, and a `docker kill` test on the real board (`log/2026-10-03-body-software.md`).
- **Read a lidar's zero angle from its datasheet, not from where the cable goes.** The RPLIDAR C1's 0° is opposite the cable; mounted cable-forward its scan is turned by 180°.
- **Export the DSN for Freerouting without full-board fills and run it with `-mt 1`.** KiCad exports every zone as a plane that blocks the layer; the multi-threaded optimiser adds clearance violations. It is deterministic: when a net stays unrouted, change the input (placement, widths, keepouts), re-running does nothing. Inner cut-outs need a keepout, the DSN does not carry them.

## Software and data

- **Never use a bare `except:` in async node code.** It swallowed `CancelledError`, nodes never shut down and the map was never saved.
- **Never call blocking libraries on the asyncio loop.** One `jtop.ok()` gave a node a 2.4 s NATS RTT.
- **Publish JSON with `allow_nan=False`.** Python writes `NaN`, which browsers reject.
- **Don't write hardware-read values back into persistent KV as defaults.** It froze white balance at 4000 K.
- **Fixed-point wire formats need a per-chunk origin.** int16 millimetres overflowed when the pose ran away to −138 m.
- **Set explicit NATS pings on long-lived clients and tolerate reconnects on publish.** The default 2-minute ping hid dead links for minutes; a NATS restart crashed a node.
- **A recorder must validate rows and retry only connection errors.** One bad timestamp blocked a table for 8 minutes.
- **Batch ClickHouse inserts on a small host.** Parts and merges, not rows, cost the CPU (1 s → 10 s flushes cut it in half).
- **Raise the request body limit in front of a chat that resends its history** (413 on long chats).
- **AI SDK tool approvals need the approval response to be the last message.** A system reminder appended after it meant approved missions never ran.
- **Approval decisions come from code, not the model.** Spoken approval is parsed from the operator's own short utterance; negation wins.
- **Give the agent local time and the UTC offset from code**, keep data in UTC.
- **Open-vocabulary detectors need per-class thresholds and track confirmation**, and the HUD must merge by class and position, not by SDK id.
- **Record the reason with every stop, not only the stop.** Nav's `free_distance = 0` meant an obstacle, a blind camera, a stale scan or a stale pose, and a stale pose stopped the robot without a trace; "why did it stop" was unanswerable from data. Nav now records `nav.hold` and `nav.safety_stop` with the reason and the measurement behind it.
- **One missing field drops the whole message in Forge.** The full-stack simulator's pose, motor, telemetry and camera-health messages lacked fields Forge requires, so sim runs recorded none of them, silently except for the writer's `malformed` counter. Make new fields optional, and check `malformed` after every sim run.

## Deploying and working with agents

- **Never run a plain `vite build` in `workspaces/web`.** `dist/` ships on every deploy; a default build broke the public HUD with CORS errors. Check with `tsc`.
- **Deploy with force-recreate; `docker compose restart` keeps the old image.**
- **Mount code, bake only dependencies, and keep a `.dockerignore` next to data.** Deploys went from over 10 minutes to about 30 s.
- **Any deploy rsyncs the whole tree and starts stopped services.** Coordinate with other sessions and don't deploy during a benchmark window.
- **Start servers the owner relies on with `nohup`.** Agent background tasks die after 2 hours.
- **Export the data before switching the robot off for offline work.** The overnight forensics needed the Parquet export.
- **Check new DNS names only against a public resolver.** The home router cached NXDOMAIN for 30 minutes.
- **Use HTTP/2 for the Cloudflare tunnel.** QUIC connections stayed stuck after a Wi-Fi drop.
- **Serve `index.html` with `no-cache`.** Browsers kept an old HUD after deploys.
- **Focus the HUD chat input by reference before typing in browser automation.** Single-letter hotkeys arm GO TO.
- **No motion without the owner's go-ahead in the session**, and stop at once when told the robot is not on the floor.
- **Far floor needs range-aware handling in the depth kernel.** At 4–5 m a 1° pose pitch error lifts the floor ~7 cm, above the 4 cm obstacle band; on 2026-10-03 integration to 5 m filled the clearance grid with phantom obstacles ("obstacles where the robot stands"). `depth.cu` now drops near-floor points beyond 2 m (3 cm + 2 cm/m of range); keep that before raising `MAX_INTEGRATION_DISTANCE` further.
- **IMU bump detection needs averaging.** With `SENSOR_PUBLISH_S = 0.01` each IMU message carries ~1 sample and floor vibration reaches 8–10 m/s², tripping the 5 m/s² collision threshold; nav now averages 50 ms.
- **Motor current alone can't detect a stall at low duty.** Reversing into an unseen wall at 17% duty draws 0.5–0.7 A, far below the 1.8 A stall threshold; nav also trips `stuck` when it commands motion and the pose hasn't moved for 2.5 s.
- **Back up only over trail the robot drove forward, and check it against the map.** A trail of positions taken in reverse order crosses gear changes; deriving headings from it flipped them by 180° and moved the camera points 0.37 m off the trail. 10 of 15 recoveries were malformed, one reversed into a wall that was in the map and one ran blind for 4.3 m. Keep the trail in the odometry frame, drop it when the robot is lifted, and cap every recovery in time and distance.
- **Don't plan a manoeuvre for a goal the robot already meets.** A viewpoint 7 cm away and 22.5° off produced a 2.2 m loop, 198 times; finish such trips at once.
- **Send the planned heading with every path point.** The heading derived from neighbouring camera points is off by up to ~23° on tight arcs (the camera sits ahead of the rear axle), so the rear-axle path was 3–5 cm off and any tracker followed it with a steady error.
- **The IMU can't see slow contacts.** At ~0.1 m/s a contact peaks at 1.7–2.5 m/s², inside floor vibration (50 ms mean, max 4.5); only pose-based `stuck` and current-based `stall` catch them.
- **A generated KiCad board inherits the old project file.** `pcbnew.NewBoard` reads the existing `.kicad_pro`, so net class patterns from earlier runs pile up and a width change in the generator silently loses to a stale class; clear classes and patterns before defining them (`pcb/rabbit-body/gen/build_board.py`).
- **Budget low-voltage sensor rails by path resistance, not by net class.** The rev A body board fed four ToF carriers (VIN ≥ 3.2 V) from a 3.3 V LDO over 0.4 mm tracks on a 0.5 oz inner layer: 0.72 Ω to the far connector. Compute the path, keep supply runs off thin inner copper.
- **Check LCSC stock for every assembled part before calling a board ready.** On the review day PCA9685PW had 0 and INA4235 1 in stock, which blocks JLC assembly regardless of the design.
