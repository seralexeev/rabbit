CREATE TABLE IF NOT EXISTS forge.run_events
(
    run_id LowCardinality(String) COMMENT 'Run id, e.g. 20261001-101500-hard-launch',
    name String COMMENT 'Human name given at start; auto for writer-created runs',
    kind Enum8('manual' = 1, 'auto' = 2) COMMENT 'manual: started with forge run start; auto: opened by the writer while no manual run is recording',
    event Enum8('start' = 1, 'stop' = 2),
    at DateTime64(9, 'UTC'),
    note String DEFAULT ''
)
ENGINE = MergeTree
ORDER BY (run_id, at)
COMMENT 'Append-only start and stop events of runs; read the runs view instead';

CREATE VIEW IF NOT EXISTS forge.runs AS
SELECT
    run_id,
    any(name) AS name,
    any(kind) AS kind,
    minIf(at, event = 'start') AS started_at,
    if(countIf(event = 'stop') = 0, NULL, maxIf(at, event = 'stop')) AS stopped_at,
    dateDiff('millisecond', started_at, coalesce(stopped_at, now64(9))) / 1000 AS duration_s,
    anyIf(note, event = 'start') AS note
FROM forge.run_events
GROUP BY run_id
COMMENT 'One row per run (a recording session). stopped_at is NULL while the run is still recording.';

CREATE TABLE IF NOT EXISTS forge.roboclaw
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    left_command Float32 COMMENT 'Commanded duty for the left motor (M1), -1..1, before the duty_max voltage cap',
    left_pwm Float32 COMMENT 'Applied PWM duty for the left motor, -1..1, as read back from the RoboClaw: command x duty_max after the slew',
    left_current Float32 COMMENT 'Left motor current, A',
    left_speed Int32 COMMENT 'Measured left wheel speed, encoder counts/s; always 0 for now because the encoders are not connected',
    left_encoder Int64 COMMENT 'Left encoder position, counts; always 0 for now because the encoders are not connected',
    right_command Float32 COMMENT 'Commanded duty for the right motor (M2), -1..1, before the duty_max voltage cap',
    right_pwm Float32 COMMENT 'Applied PWM duty for the right motor, -1..1, as read back from the RoboClaw: command x duty_max after the slew',
    right_current Float32 COMMENT 'Right motor current, A',
    right_speed Int32 COMMENT 'Measured right wheel speed, encoder counts/s; always 0 for now because the encoders are not connected',
    right_encoder Int64 COMMENT 'Right encoder position, counts; always 0 for now because the encoders are not connected',
    supply_voltage Float32 COMMENT '12 V buck converter output feeding the RoboClaw, V; not the battery (see power.battery_voltage)',
    duty_max Nullable(Float32) COMMENT 'Voltage cap on the motor duty: rabbit-roboclaw sends command x duty_max with duty_max = min(1, 12 V / highest supply_voltage of the last second), so the 12 V motors never see more than 12 V; 1 on the 12 V buck, 0.71 on a full 4S pack; NULL before 2026-10-03',
    temperature Float32 COMMENT 'RoboClaw board temperature, C',
    status UInt32 COMMENT 'RoboClaw status bit flags, 0 is normal',
    errors UInt32 COMMENT 'Cumulative count of failed serial commands since the node started',
    retries UInt32 DEFAULT 0 COMMENT 'Cumulative serial command retries since the node started; a rising count means a noisy or failing serial link',
    reconnects UInt32 DEFAULT 0 COMMENT 'Times the node reopened the serial port since it started'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'RoboClaw motor controller at 50 Hz: both drive motors and the battery';

CREATE TABLE IF NOT EXISTS forge.power
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    battery_voltage Float32 COMMENT 'Battery voltage (INA channel 1), V; 99 Wh 4S Li-ion V-mount pack, 16.8 V full, 14.8 V nominal',
    battery_current Float32 COMMENT 'Total battery current, A: motors through the 12 V buck, Jetson, camera and servos',
    battery_power Float32 COMMENT 'Total battery power, W',
    battery_charge_pct Nullable(Float32) COMMENT 'State-of-charge estimate from the 4S Li-ion voltage curve, percent; it reads low under load; NULL before the robot published it',
    battery_clipped Nullable(Bool) COMMENT 'The battery shunt voltage was at or above 90% of the INA ±81.92 mV range (7.37 A on the 10 mOhm shunt): battery_current is at the ceiling and the true peak may be higher; NULL before 2026-10-03. The shunt value and calibration of each start are in events power.calibrated',
    rail_6v_voltage Float32 COMMENT '6 V servo rail voltage (INA channel 2), V',
    rail_6v_current Float32 COMMENT '6 V servo rail current, A',
    rail_6v_power Float32 COMMENT '6 V servo rail power, W',
    rail_6v_clipped Nullable(Bool) COMMENT 'The 6 V rail shunt voltage was at or above 90% of the INA range: rail_6v_current is at the ceiling; NULL before 2026-10-03',
    errors UInt32 COMMENT 'Cumulative INA read errors since the node started'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'INA4235 power monitor at 50 Hz: the battery (channel 1) and the 6 V servo rail (channel 2)';

CREATE TABLE IF NOT EXISTS forge.steering
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    angle Float32 COMMENT 'Applied steering angle, -1 (full left) .. 1 (full right)',
    pulse_us Float32 COMMENT 'Servo pulse width, microseconds (1500 is centered)',
    errors UInt32 DEFAULT 0 COMMENT 'Cumulative failed servo writes since the node started'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Steering servo at 20 Hz';

CREATE TABLE IF NOT EXISTS forge.imu
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    accel_x Float32 COMMENT 'Linear acceleration including gravity, m/s2 (camera frame, gravity is mostly on y)',
    accel_y Float32 COMMENT 'Linear acceleration including gravity, m/s2',
    accel_z Float32 COMMENT 'Linear acceleration including gravity, m/s2',
    gyro_x Float32 COMMENT 'Angular velocity, deg/s',
    gyro_y Float32 COMMENT 'Angular velocity, deg/s',
    gyro_z Float32 COMMENT 'Angular velocity, deg/s',
    qx Float32 COMMENT 'IMU orientation quaternion',
    qy Float32,
    qz Float32,
    qw Float32,
    g Float32 DEFAULT sqrt(accel_x * accel_x + accel_y * accel_y + accel_z * accel_z) / 9.80665 COMMENT 'Magnitude of total acceleration, g; 1 at rest',
    samples UInt16 DEFAULT 1 COMMENT 'Raw IMU samples averaged into this row'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'ZED 2i IMU, published by the camera node at about 30 Hz';

CREATE TABLE IF NOT EXISTS forge.pose
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    frame_number UInt64,
    x Float32 COMMENT 'Position in the ZED world frame, m',
    y Float32 COMMENT 'Position in the ZED world frame, m',
    z Float32 COMMENT 'Position in the ZED world frame, m',
    qx Float32 COMMENT 'Orientation quaternion in the world frame',
    qy Float32,
    qz Float32,
    qw Float32,
    roll_deg Float32 DEFAULT 0 COMMENT 'Rotation about the camera z axis (forward-backward), deg. Rows recorded before the writer fix of 2026-10-03 hold yaw in pitch_deg, roll in yaw_deg and pitch in roll_deg',
    pitch_deg Float32 DEFAULT 0 COMMENT 'Rotation about the x axis (right), deg; nose up is positive. Before the 2026-10-03 fix this column held yaw',
    yaw_deg Float32 DEFAULT 0 COMMENT 'Rotation about the vertical y axis, deg; positive turns left, so it is minus heading_deg of robot_status. Before the 2026-10-03 fix this column held roll',
    vx Float32 DEFAULT 0 COMMENT 'Linear velocity in the camera frame, m/s',
    vy Float32 DEFAULT 0,
    vz Float32 DEFAULT 0,
    wx Float32 DEFAULT 0 COMMENT 'Angular velocity from the pose estimate',
    wy Float32 DEFAULT 0,
    wz Float32 DEFAULT 0,
    std_x Float32 DEFAULT 0 COMMENT 'Position standard deviation, m',
    std_y Float32 DEFAULT 0,
    std_z Float32 DEFAULT 0,
    confidence UInt8 DEFAULT 0 COMMENT 'Tracking confidence, 0-100'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'ZED positional tracking at about 30 Hz; only frames with tracking OK are published';

CREATE TABLE IF NOT EXISTS forge.magnetometer
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    field_x Float32 COMMENT 'Magnetic field, microtesla',
    field_y Float32 COMMENT 'Magnetic field, microtesla',
    field_z Float32 COMMENT 'Magnetic field, microtesla',
    heading_deg Float32 COMMENT 'Magnetic heading, deg; meaningless while heading_state is NOT_CALIBRATED',
    heading_state LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'ZED magnetometer at 50 Hz';

CREATE TABLE IF NOT EXISTS forge.barometer
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    pressure_hpa Float32 COMMENT 'Barometric pressure, hPa'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'ZED barometer at 25 Hz';

CREATE TABLE IF NOT EXISTS forge.jetson
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    cpu_load Array(Float32) COMMENT 'Load per CPU core, percent (6 cores)',
    cpu_freq_mhz Array(UInt32) COMMENT 'Clock per CPU core, MHz; a drop below the usual maximum means throttling',
    gpu_load Float32 COMMENT 'GPU load, percent',
    gpu_freq_mhz UInt32 COMMENT 'GPU clock, MHz',
    ram_used_bytes UInt64,
    ram_total_bytes UInt64,
    swap_used_bytes UInt64,
    temp_cpu Float32 COMMENT 'C',
    temp_gpu Float32 COMMENT 'C',
    temp_soc0 Float32 COMMENT 'C',
    temp_soc1 Float32 COMMENT 'C',
    temp_soc2 Float32 COMMENT 'C',
    temp_tj Float32 COMMENT 'Junction temperature, C; the throttling reference',
    power_mw UInt32 COMMENT 'Total board power, mW',
    input_mv UInt32 COMMENT 'Board input voltage, mV',
    input_ma UInt32 COMMENT 'Board input current, mA',
    rail_cpu_gpu_cv_mw UInt32 COMMENT 'VDD_CPU_GPU_CV rail power, mW',
    rail_soc_mw UInt32 COMMENT 'VDD_SOC rail power, mW',
    disk_used_gb Float32,
    uptime_s UInt32 COMMENT 'Jetson uptime, s',
    fan_pct Float32 COMMENT 'Fan duty, percent',
    fan_rpm UInt32,
    cpu_actual_mhz Array(UInt32) DEFAULT [] COMMENT 'Clock each CPU core actually ran at when sampled (cpuinfo_cur_freq), MHz; unlike cpu_freq_mhz (the requested clock) it shows the 50 % cuts of over-current throttling. Empty before 2026-10-03',
    cpu_min_freq_mhz Array(UInt32) DEFAULT [] COMMENT 'CPU frequency floor per core (scaling_min_freq), MHz; 1728 while jetson_clocks pins the clocks, 729.6 after nvpmodel reset them',
    gpu_min_freq_mhz Nullable(UInt32) COMMENT 'GPU frequency floor, MHz; 1020 while pinned, 306 after a reset',
    gpu_max_freq_mhz Nullable(UInt32) COMMENT 'GPU frequency ceiling, MHz',
    emc_freq_mhz Nullable(UInt32) COMMENT 'Memory controller (EMC) clock, MHz; 3199 while pinned',
    oc1_events Nullable(UInt64) COMMENT 'soctherm OC1 events since boot: VDD_IN under-voltage (about 4.5 V); any increase means the supply sagged',
    oc2_events Nullable(UInt64) COMMENT 'soctherm OC2 events since boot: average input power over the limit (25 W)',
    oc3_events Nullable(UInt64) COMMENT 'soctherm OC3 events since boot: instantaneous input power over the limit; each event halves the CPU and GPU clocks for about 1 ms; 1-2 per second is normal for this board',
    oc_throttle_ticks Nullable(UInt64) COMMENT 'BPMP accumulated over-current throttle time (soctherm oc2 event_time) since boot, undocumented units of about 31.25 MHz ticks',
    power_mode LowCardinality(String) DEFAULT '' COMMENT 'nvpmodel power mode, e.g. MAXN_SUPER',
    ram_shared_bytes Nullable(UInt64) COMMENT 'Shared RAM as jtop reports it, bytes; on the Jetson mostly memory the GPU (CUDA, nvblox, TensorRT) holds; NULL before 2026-10-03',
    boot_id LowCardinality(String) DEFAULT '' COMMENT 'Linux boot id; a new value means the Jetson rebooted (join with events.boot_id and node_starts)'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Jetson Orin board telemetry at 1 Hz';

CREATE TABLE IF NOT EXISTS forge.jetson_containers
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    name LowCardinality(String) COMMENT 'Docker container name on the Jetson, e.g. rabbit-zed, rabbit-roboclaw',
    cpu Float32 COMMENT 'CPU usage, percent of one core (can exceed 100)',
    mem_bytes UInt64,
    mem_limit_bytes UInt64
)
ENGINE = MergeTree
ORDER BY (run_id, name, ts)
COMMENT 'Per-container CPU and memory on the Jetson at 1 Hz, one row per container per sample';

CREATE TABLE IF NOT EXISTS forge.zed_health
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    camera_fps Float32 COMMENT 'Configured camera fps',
    current_fps Float32 COMMENT 'Measured grab fps',
    capture_ms Float32 COMMENT 'Duration of the last grab and processing, ms',
    pose_state LowCardinality(String) COMMENT 'OK or LOST',
    pose_messages UInt64 COMMENT 'Cumulative pose messages published',
    pose_drop_count UInt64 COMMENT 'Cumulative frames without a tracked pose',
    frames_dropped UInt64 DEFAULT 0 COMMENT 'Cumulative camera frames dropped',
    tracking_state LowCardinality(String) DEFAULT '' COMMENT 'Positional tracking fusion status, e.g. VISUAL_INERTIAL, INERTIAL',
    odometry_status LowCardinality(String) DEFAULT '',
    spatial_memory_status LowCardinality(String) DEFAULT '' COMMENT 'e.g. KNOWN_MAP once relocalized in a saved area map',
    camera_moving_state LowCardinality(String) DEFAULT '' COMMENT 'STATIC, MOVING or FALLING',
    low_image_quality Bool DEFAULT false,
    low_lighting Bool DEFAULT false,
    low_depth_reliability Bool DEFAULT false,
    low_motion_sensors_reliability Bool DEFAULT false,
    preview_skipped UInt64 COMMENT 'Cumulative preview frames skipped',
    mapping_state LowCardinality(String),
    map_chunks UInt32,
    map_points UInt64,
    map_triangles UInt64 DEFAULT 0,
    temp_imu Float32 COMMENT 'C',
    temp_barometer Float32 COMMENT 'C',
    temp_onboard_left Float32 COMMENT 'C',
    temp_onboard_right Float32 COMMENT 'C',
    loc_status LowCardinality(String) DEFAULT '' COMMENT 'rabbit-loc status as rabbit-zed last heard it: relocalizing, localized, lost; empty without rabbit-loc',
    gen3_from_loc_x Nullable(Float32) COMMENT 'Shadow check: x of the transform from the RTAB-Map map frame to the GEN_3 map frame, m; constant while both localizations agree; NULL unless both are localized',
    gen3_from_loc_z Nullable(Float32) COMMENT 'Shadow check: z of the same transform, m',
    gen3_from_loc_yaw_deg Nullable(Float32) COMMENT 'Shadow check: rotation about the vertical of the same transform, degrees',
    relocalizing Nullable(Bool) COMMENT 'Relocalizing against the saved map: poses are in a temporary frame and the planner refuses trips; NULL before 2026-10-03',
    map_mode LowCardinality(String) DEFAULT '' COMMENT 'Tracking mode: localization (the saved area is only used), mapping (it is extended) or loc (rabbit-loc gives the map frame)',
    map_id LowCardinality(String) DEFAULT '' COMMENT 'Saved map id (data/map/room.id); a new value means the map was reset or archived',
    map_session LowCardinality(String) DEFAULT '' COMMENT 'Camera process session; a new value means rabbit-zed restarted (it is also the odometry session)',
    idle Nullable(Bool) COMMENT 'Nothing has moved for 3 s, so the camera runs at the idle frame rate',
    implausible_poses Nullable(UInt64) COMMENT 'Cumulative poses dropped as implausible (millimetre glitches after relocalizing)',
    held_poses Nullable(UInt64) COMMENT 'Cumulative poses held back by the jump gate',
    odom_rejected Nullable(UInt64) COMMENT 'Cumulative odometry steps rejected as too large',
    dropped_publishes Nullable(UInt64) COMMENT 'Cumulative messages dropped while NATS reconnected',
    corrupted_frames Nullable(UInt64) COMMENT 'Cumulative frames the SDK reported corrupted',
    map_rebuilds Nullable(UInt32) COMMENT 'Cumulative nvblox rebuilds after pose corrections',
    stored_frames Nullable(UInt32) COMMENT 'Depth frames kept for rebuilds',
    keyframes Nullable(UInt32) COMMENT 'GEN_3 keyframes in the tracking memory',
    integrate_ms Nullable(Float32) COMMENT 'Last nvblox depth integration, ms',
    mesh_ms Nullable(Float32) COMMENT 'Last mesh extraction, ms',
    grid_ms Nullable(Float32) COMMENT 'Last clearance-grid extraction, ms',
    skipped_jumps Nullable(UInt64) COMMENT 'Cumulative depth frames not integrated because the pose jumped',
    floor_y Nullable(Float32) COMMENT 'Floor estimate in the raw ZED frame, m',
    detector_ms Nullable(Float32) COMMENT 'Last object detection read, ms',
    pose_tilt_deg Nullable(Float32) COMMENT 'Tilt of the tracked pose, deg; compared with imu_tilt_deg to detect tracking failure',
    imu_tilt_deg Nullable(Float32) COMMENT 'Tilt from the IMU gravity vector, deg'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'ZED camera node health at 1 Hz';

CREATE TABLE IF NOT EXISTS forge.joy
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Receive time on the Forge host (gamepad messages carry no robot ts)',
    throttle Float32 COMMENT 'r2 minus l2 trigger, -1..1; the speed the driver asked for',
    steer Float32 COMMENT 'Left stick x, -1..1',
    raw String COMMENT 'Full DualSense JSON state'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Gamepad commands at 30 Hz while a gamepad is connected';

CREATE TABLE IF NOT EXISTS forge.map_chunks
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Receive time on the Forge host',
    session String COMMENT 'ZED mapping session id',
    chunk_index UInt32 COMMENT 'Spatial map chunk; a later row for the same chunk replaces the earlier one',
    vertices UInt32 COMMENT 'Mesh vertices in this chunk',
    triangles UInt32 COMMENT 'Mesh triangles in this chunk',
    cx Float32 COMMENT 'Centroid of the chunk vertices, m',
    cy Float32 COMMENT 'Centroid of the chunk vertices, m',
    cz Float32 COMMENT 'Centroid of the chunk vertices, m'
)
ENGINE = MergeTree
ORDER BY (run_id, chunk_index, ts)
COMMENT 'Spatial-map mesh chunk updates, one row each time a chunk changes its vertex or triangle count (summaries only; the mesh itself is not stored)';

CREATE TABLE IF NOT EXISTS forge.obstacle
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Camera frame time (robot clock)',
    nearest_distance Nullable(Float32) COMMENT 'Horizontal distance to the nearest obstacle point in range, m; NULL when nothing is in range',
    nearest_bearing_deg Nullable(Float32) COMMENT 'Bearing of the nearest point, deg; 0 is straight ahead',
    nearest_x Nullable(Float32) COMMENT 'Nearest point in the ZED world frame, m',
    nearest_y Nullable(Float32),
    nearest_z Nullable(Float32),
    ahead_distance Nullable(Float32) COMMENT 'Distance to the nearest point inside the driving corridor ahead, m; NULL when the corridor is clear',
    ahead_bearing_deg Nullable(Float32),
    ahead_x Nullable(Float32),
    ahead_y Nullable(Float32),
    ahead_z Nullable(Float32),
    blind Bool DEFAULT false COMMENT 'Too much of the depth image is invalid to see obstacles; navigation refuses to drive forward while blind',
    blind_fraction Nullable(Float32) COMMENT 'Share of the depth window without valid depth, 0..1',
    scan_angle_min_deg Nullable(Float32) COMMENT 'Bearing of the first scan bin, deg; 0 is straight ahead, negative is left',
    scan_angle_step_deg Nullable(Float32) COMMENT 'Width of one scan bin, deg',
    scan_ranges Array(Nullable(Float32)) DEFAULT [] COMMENT 'Nearest obstacle per bearing bin from the axle-centred scan the navigation safety governor uses, m; NULL when the bin is clear'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Obstacles from the ZED depth map at 10 Hz';

CREATE TABLE IF NOT EXISTS forge.objects
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Camera frame time (robot clock)',
    object_id UInt32 COMMENT 'ZED tracking id of the object, stable while it stays tracked, restarts from 0 when rabbit-zed restarts',
    label LowCardinality(String) COMMENT 'Detected class: person, chair, sofa, refrigerator, door, television, ... (YOLOE open-vocabulary detector, see rabbit/data/detector/detector.json)',
    confidence Float32 COMMENT 'Detector confidence, 0..100',
    x Float32 COMMENT 'Object centre in the ZED world frame (same frame as pose), m',
    y Float32 COMMENT 'Height of the object centre above the floor, m',
    z Float32,
    width Float32 COMMENT '3D box size, m',
    height Float32,
    length Float32,
    box Array(Float32) COMMENT 'Box in the camera image [x0, y0, x1, y1], normalized 0..1',
    moving Bool DEFAULT false COMMENT 'Class that can move on its own (person, pet, robot vacuum)'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Tracked objects from the on-robot detector, one row per object per detection frame (5-10 Hz)';

CREATE TABLE IF NOT EXISTS forge.nav_state
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    mode LowCardinality(String) COMMENT 'idle, driving, maneuvering, blocked, arrived or fault',
    goal_x Nullable(Float32) COMMENT 'Goal in the ZED world frame (x, z), m; NULL without a goal',
    goal_z Nullable(Float32),
    distance_to_goal Float32 COMMENT 'm',
    heading_error_deg Float32 COMMENT 'Angle between heading and the goal direction, deg',
    speed Float32 COMMENT 'Commanded speed, duty -1..1',
    steer Float32 COMMENT 'Commanded steering, -1..1',
    path_points UInt16 COMMENT 'Points in the predicted path; the path itself is not stored',
    step_type LowCardinality(String) DEFAULT '' COMMENT 'Current mission step: turn, move or goto; empty without a mission',
    step_index UInt16 DEFAULT 0 COMMENT 'Current step, 1-based; 0 without a mission',
    steps_total UInt16 DEFAULT 0,
    turn_remaining_deg Nullable(Float32) COMMENT 'Heading change left in a turn step, deg',
    free_distance Nullable(Float32) COMMENT 'Free travel along the commanded arc from the safety governor, m: below 0.3 it holds the robot, below 0.6 it slows to the minimum speed',
    fault LowCardinality(String) DEFAULT '' COMMENT 'Why navigation stopped: stall, collision, blocked, step timeout, operator link lost, control error, manoeuvre failed, manual override or rejected: ...; empty when none. It stays set until the next mission',
    mission_id String DEFAULT '' COMMENT 'Mission nav accepted most recently: the id the sender gave (forge-... from chat, explore ids) or one nav assigned. It stays set after the mission ends (arrived, fault, idle after a cancel) until the next one, so use mode to tell whether a mission is running. Joins with logs.mission_id, which is empty between missions',
    hold LowCardinality(String) DEFAULT '' COMMENT 'Why the safety governor holds the robot right now: obstacle ahead, obstacle behind, blind, no fresh scan, no fresh pose; empty when it lets it drive. Each new hold is also a nav.hold event',
    mission_source LowCardinality(String) DEFAULT '' COMMENT 'Who sent the current mission: planner, forge, hud or empty',
    trip_id String DEFAULT '' COMMENT 'Planner trip the current mission belongs to; joins with planner_state.trip_id and events.trip_id'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Autonomous navigation state at 10 Hz';

CREATE TABLE IF NOT EXISTS forge.drive
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when nav sent it, Forge host clock for commands from Forge, receive time on the Forge host for HUD commands (they carry no ts)',
    speed Float32 COMMENT 'Commanded speed, duty -1..1',
    steer Float32 COMMENT 'Commanded steering, -1..1',
    source LowCardinality(String) DEFAULT '' COMMENT 'Who sent it: nav (autonomous navigation after the safety governor), forge (chat stop) or hud (the operator HUD stop button)'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Drive commands on rabbit.cmd.drive: nav at 20 Hz while navigating, plus stop commands from Forge and the HUD (joy holds manual commands)';

CREATE TABLE IF NOT EXISTS forge.nav_events
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock for commands from the explore node, Forge host clock for commands from Forge, receive time on the Forge host for HUD commands',
    event Enum8('goal' = 1, 'cancel' = 2, 'mission' = 3),
    goal_x Nullable(Float32) COMMENT 'New goal (x, z) in the ZED world frame, m; NULL for cancel and mission',
    goal_z Nullable(Float32),
    steps String DEFAULT '' COMMENT 'Mission steps as JSON for mission events',
    source LowCardinality(String) DEFAULT '' COMMENT 'Who sent it: explore (autonomous exploration), forge (chat run_mission and stop) or hud (the operator HUD)'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Navigation goals, missions and cancels';

CREATE TABLE IF NOT EXISTS forge.wifi
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    connected Bool,
    ssid LowCardinality(Nullable(String)),
    frequency_mhz Nullable(Float32) COMMENT 'Channel frequency, MHz',
    signal_dbm Nullable(Float32) COMMENT 'Received signal strength, dBm; above -60 is good, below -75 is poor',
    rx_bitrate_mbps Nullable(Float32) COMMENT 'Negotiated downlink rate, Mbit/s',
    tx_bitrate_mbps Nullable(Float32) COMMENT 'Negotiated uplink rate, Mbit/s',
    gateway_rtt_ms Nullable(Float32) COMMENT 'Ping round trip to the router, ms; NULL when the ping was lost',
    tx_bytes_per_s Nullable(Float32) COMMENT 'Uplink throughput from the robot, bytes/s (telemetry and video to the Mac)',
    rx_bytes_per_s Nullable(Float32) COMMENT 'Downlink throughput to the robot, bytes/s',
    tx_errors_per_s Nullable(Float32),
    rx_errors_per_s Nullable(Float32),
    tx_dropped_per_s Nullable(Float32) COMMENT 'Uplink packets dropped per second',
    rx_dropped_per_s Nullable(Float32) COMMENT 'Downlink packets dropped per second'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Robot Wi-Fi link at 1 Hz from the telemetry node';

CREATE TABLE IF NOT EXISTS forge.explore_state
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    exploration_id String DEFAULT '' COMMENT 'Exploration the explore node is running or last ran; joins with logs.fields exploration context',
    phase LowCardinality(String) COMMENT 'idle, planning, driving, done or failed',
    message String DEFAULT '' COMMENT 'Why the last exploration ended, e.g. distance limit reached, no reachable frontiers left, cancelled',
    elapsed_s Nullable(Float32) COMMENT 'Time since the exploration started, s',
    travelled_m Float32 COMMENT 'Distance driven in this exploration, m',
    max_duration_s Nullable(Float32) COMMENT 'Time limit of the exploration, s',
    max_distance_m Nullable(Float32) COMMENT 'Distance limit of the exploration, m',
    frontiers UInt32 COMMENT 'Frontiers (edges of the known map) found by the last plan',
    failed_frontiers UInt32 COMMENT 'Frontiers given up on in this exploration',
    target_x Nullable(Float32) COMMENT 'Viewpoint the robot is driving to (x, z) in the ZED world frame, m',
    target_z Nullable(Float32),
    target_path_m Nullable(Float32) COMMENT 'Planned path length to the target, m',
    planning_ms Nullable(Float32) COMMENT 'Time the last plan took, ms',
    map_chunks UInt32 COMMENT 'Spatial-map chunks the planner knows'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Autonomous exploration state at 2 Hz from the explore node';

CREATE TABLE IF NOT EXISTS forge.planner_state
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    trip_id String COMMENT 'Trip of the route planner: forge-... from the chat go_to and plan_route, explore-... from exploration, or the id another sender gave',
    phase LowCardinality(String) COMMENT 'planning, driving, replanning, recovering (backing up along its own trail), waiting (no route, retrying), arrived, failed, cancelled, or planned (a preview that does not drive)',
    source LowCardinality(String) DEFAULT '' COMMENT 'Who asked for the trip: forge, hud or explore',
    preview Bool DEFAULT false COMMENT 'Route preview only; the robot does not move',
    target_kind LowCardinality(String) DEFAULT '' COMMENT 'object, place, point or room',
    target_label String DEFAULT '' COMMENT 'Object class or place name, e.g. refrigerator, kitchen',
    target_x Nullable(Float32) COMMENT 'Target (x, z) in the ZED world frame, m: the object centre or the requested point',
    target_z Nullable(Float32),
    goal_x Nullable(Float32) COMMENT 'Where the planner drives the camera (x, z), m: a viewpoint facing the object, or the nearest free spot to a point',
    goal_z Nullable(Float32),
    goal_heading_deg Nullable(Float32) COMMENT 'Heading at the goal, deg (0 faces world -z, positive turns right); NULL for position goals',
    path_length_m Nullable(Float32) COMMENT 'Length of the current planned route, m',
    remaining_m Nullable(Float32) COMMENT 'Route left to drive, m',
    replans UInt16 COMMENT 'Times the route was replanned in this trip',
    recoveries UInt16 COMMENT 'Times the robot backed up to get unstuck in this trip',
    reason String DEFAULT '' COMMENT 'Why the last route was planned: start, path blocked 1.2 m ahead, obstacle in the way, off the path by 0.40 m, pose corrected, after backing up, retry',
    message String DEFAULT '' COMMENT 'Status text; for a failed trip the reason, e.g. cannot reach the target: no route, route blocked: ..., stuck: ...',
    plan_ms Nullable(Float32) COMMENT 'Time the last plan took, ms',
    expansions UInt32 DEFAULT 0 COMMENT 'Search nodes the last plan expanded',
    mission_id String DEFAULT '' COMMENT 'Nav mission carrying the current route (<trip_id>.<n>); joins with nav_state.mission_id',
    exploration_id String DEFAULT '' COMMENT 'Exploration that asked for this trip; empty for trips from the chat or the HUD'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Route planner (rabbit-planner) trips at 2 Hz while a trip runs, plus its final state: routes to objects, places and points, replans and recoveries';

CREATE TABLE IF NOT EXISTS forge.operator_heartbeat
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Time the operator HUD sent it, Forge host clock (the HUD runs on the same Mac)',
    round_trip_ms Float32 COMMENT 'From the HUD through the robot NATS server back to the Forge writer, ms; it rises with Wi-Fi latency'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Operator HUD heartbeats at about 2 Hz while the HUD is open; navigation trips with operator link lost after 3 s without one';

CREATE TABLE IF NOT EXISTS forge.command_events
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when the robot sent it, else receive time on the Forge host',
    subject LowCardinality(String) COMMENT 'rabbit.nav.explore (start an exploration), rabbit.planner.goal (a planned trip to an object, place or point, see planner_state), rabbit.map.save (save the spatial map), rabbit.map.reset, rabbit.safety.estop and rabbit.safety.reset (latched software E-stop and its release), rabbit.power.request (shutdown, reboot_jetson, power_cycle_jetson)',
    source LowCardinality(String) COMMENT 'Who sent it: explore, forge or hud',
    payload String COMMENT 'The command as JSON, e.g. the exploration limits'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Low-rate robot commands other than navigation goals, missions and cancels (see nav_events) and drive commands (see drive, joy)';

CREATE TABLE IF NOT EXISTS forge.kv_changes
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Time the robot NATS server stored the change (robot clock)',
    key LowCardinality(String) COMMENT 'Key in the robot rabbit key-value bucket, e.g. rabbit.zed.camera_settings, rabbit.zed.intrinsics',
    revision UInt64 COMMENT 'Bucket revision of the change',
    operation LowCardinality(String) COMMENT 'PUT, DEL or PURGE',
    value String COMMENT 'New value, usually JSON; camera settings hold BRIGHTNESS, CONTRAST, GAIN, EXPOSURE, AEC_AGC (auto exposure), WHITEBALANCE_AUTO and similar'
)
ENGINE = ReplacingMergeTree
ORDER BY (run_id, ts, key, revision)
COMMENT 'Changes of the robot configuration in its key-value bucket (camera settings and intrinsics, operator and UI state); the writer also records the current value of every key when it starts';

CREATE TABLE IF NOT EXISTS forge.logs
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when the log record was created',
    node LowCardinality(String) COMMENT 'Robot node that logged it: rabbit-zed, nav, explore, roboclaw, steering, ina4235 or telemetry (container lifecycle events come from telemetry with logger docker.events)',
    level Enum8('debug' = 10, 'info' = 20, 'warning' = 30, 'error' = 40, 'critical' = 50) COMMENT 'Compare as level >= ''warning'' to keep warnings and worse',
    logger LowCardinality(String) COMMENT 'Python logger name: the node name, a library such as nats, or docker.events',
    message String COMMENT 'Formatted message',
    template String COMMENT 'Message before argument substitution; equal to message for logs written with f-strings',
    exception_type LowCardinality(String) COMMENT 'Exception class, e.g. OSError; empty without one',
    exception String COMMENT 'Full traceback; empty without one',
    location LowCardinality(String) COMMENT 'module:function:line that logged it',
    fields Map(LowCardinality(String), String) COMMENT 'Structured fields: extra values the node attached (fault, container, exit_code, action, steps) and context such as exploration_id',
    mission_id String COMMENT 'Mission nav was executing when the record was logged (nav only); joins with nav_state.mission_id',
    map_session String COMMENT 'ZED mapping session at the time (rabbit-zed and explore)',
    repeats UInt32 COMMENT 'Identical records (same logger, level, template with numbers ignored, exception) suppressed in the 10 s before this one; the record stands for 1 + repeats occurrences',
    pid UInt32 COMMENT 'Process id inside the container; a new pid means the node restarted',
    seq UInt64 COMMENT 'Sequence in the robot LOGS JetStream stream',
    fingerprint UInt64 MATERIALIZED cityHash64(node, logger, exception_type, replaceRegexpAll(template, '[0-9]+(\\.[0-9]+)?', '#')) COMMENT 'Groups records of the same kind regardless of the numbers in them'
)
ENGINE = ReplacingMergeTree
ORDER BY (run_id, ts, seq)
COMMENT 'Log records of every robot node, shipped through the robot LOGS JetStream stream so nothing is lost while the Wi-Fi is down. Search words with hasAllTokens(lower(message), ''word another'') (lower case: the search is case-sensitive). Info and debug are kept 30 days, warnings and worse 180 days';

CREATE TABLE IF NOT EXISTS forge.loc
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when published',
    keyframe_ts Nullable(DateTime64(9, 'UTC')) COMMENT 'Keyframe the transform was last updated on',
    status LowCardinality(String) COMMENT 'relocalizing, localized or lost',
    mode LowCardinality(String) COMMENT 'RTAB-Map mode: localization, growing (adding new views to the map), mapping (first session) or new session',
    map_id LowCardinality(String) COMMENT 'Id of the RTAB-Map database (data/map/rtabmap.id)',
    odom_session LowCardinality(String) COMMENT 'rabbit-zed odometry session the transform applies to',
    x Nullable(Float32) COMMENT 'map<-odom translation in the raw ZED Y-up world (not floor-shifted), m; NULL before the first fix',
    y Nullable(Float32),
    z Nullable(Float32),
    yaw_deg Nullable(Float32) COMMENT 'map<-odom rotation about the vertical (+y), degrees',
    matches UInt32 COMMENT 'Accepted matches since rabbit-loc started',
    corrections UInt32 COMMENT 'Accepted jumps of map<-odom (each confirmed by 2 agreeing matches)',
    pending UInt16 COMMENT 'Unconfirmed candidate matches',
    grown_nodes UInt32 COMMENT 'Nodes added to the map while localized since rabbit-loc started',
    last_match_ts Nullable(DateTime64(9, 'UTC')) COMMENT 'Keyframe of the last match'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'rabbit-loc map<-odom (RTAB-Map global localization), after each processed keyframe and at 1 Hz';

CREATE TABLE IF NOT EXISTS forge.events
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when the node decided',
    node LowCardinality(String) COMMENT 'Node that emitted it: nav, planner, explore, rabbit-zed, roboclaw, steering, ina4235, telemetry, sim; on the Raspberry Pi safety, power, lidar, tof',
    name LowCardinality(String) COMMENT 'What happened, <area>.<what>: node.start, node.stop, nav.mission_started, nav.mission_arrived, nav.mission_cancelled, nav.mission_rejected, nav.safety_stop, nav.hold, nav.manual_override, nav.pose_jump, nav.odometry_reset, nav.blocked_at_goal, planner.trip_started, planner.trip_rejected, planner.plan, planner.waiting, planner.recovery, planner.recovery_ended, planner.bump, planner.trip_finished, explore.started, explore.goal_chosen, explore.trip_outcome, explore.frontier_abandoned, explore.finished, camera.opened, camera.restart, camera.relocalization_started, camera.relocalized, camera.relocalization_failed, camera.tracking_failed, camera.implausible_poses, map.saved, map.save_skipped, map.loaded, map.archived, map.reset, map.rebuilt, map.extend_requested, map.session_changed, mapping.enabled, motors.command_timeout, motors.connected, motors.port_lost, power.calibrated, drive.owner_changed, drive.command_ignored; on the Raspberry Pi (Rabbit 2.0) safety.started, safety.self_test, safety.estop_line, safety.limit, safety.bump, safety.bump_released, safety.brain_lost, safety.brain_restored, safety.input_stale, safety.input_restored, safety.roboclaw_lost, safety.roboclaw_ready, safety.overcurrent, safety.battery_low, safety.battery_critical, safety.estop, safety.reset, power.state_changed, power.request, power.button_short, power.battery_low, power.brain_lost, power.jetson_reboot, power.jetson_cycle_skipped, lidar.connected, lidar.connect_failed, lidar.device_error, lidar.stalled, lidar.port_lost, tof.sensor_ready, tof.sensor_reset, tof.read_failed, tof.power_cycled; and others',
    severity Enum8('debug' = 10, 'info' = 20, 'warning' = 30, 'error' = 40, 'critical' = 50) COMMENT 'Compare as severity >= ''warning''',
    reason String COMMENT 'Why, in words: the fault (stall, collision, stuck, blocked), the replan trigger (path blocked 1.2 m ahead, off the path by 0.40 m), the restart reason, who cancelled',
    mission_id String DEFAULT '' COMMENT 'Nav mission at the time; joins with nav_state.mission_id',
    trip_id String DEFAULT '' COMMENT 'Planner trip at the time; joins with planner_state.trip_id',
    exploration_id String DEFAULT '' COMMENT 'Exploration at the time; joins with explore_state.exploration_id',
    odom_session LowCardinality(String) DEFAULT '' COMMENT 'Camera odometry session; changes when rabbit-zed restarts',
    map_id LowCardinality(String) DEFAULT '' COMMENT 'Saved map id; changes after a map reset or archive',
    map_session LowCardinality(String) DEFAULT '' COMMENT 'Map session of the camera process',
    boot_id LowCardinality(String) DEFAULT '' COMMENT 'Linux boot id; a new value means the Jetson rebooted',
    instance_id String DEFAULT '' COMMENT 'Node process (start time and pid); a new value means the node restarted',
    values Map(LowCardinality(String), Float64) COMMENT 'Numbers measured at the decision, unit in the key: free_distance_m, motor_current_a, ground_speed_mps, accel_mps2, plan_ms, length_m, duration_s, uptime_s, travel_m',
    labels Map(LowCardinality(String), String) COMMENT 'Other details as text: source, mode, step_type, outcome, target_label, fault',
    suppressed UInt32 DEFAULT 0 COMMENT 'Events of the same name and reason skipped by the rate limit since the previous one',
    seq UInt64 COMMENT 'Sequence in the robot LOGS JetStream stream'
)
ENGINE = ReplacingMergeTree
ORDER BY (run_id, ts, seq)
COMMENT 'Structured decisions and state changes of every robot node with their reason, ids and measured values (subject rabbit.log.<node>.event, durable through the LOGS stream). Every event is also a log record with fields[''event''] set. Start here for why the robot did something';

CREATE TABLE IF NOT EXISTS forge.node_starts
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when the node started',
    node LowCardinality(String),
    boot_id LowCardinality(String) COMMENT 'Linux boot id of the Jetson',
    instance_id String COMMENT 'Node process; joins with events.instance_id and node_metrics.instance_id',
    host LowCardinality(String),
    pid UInt32,
    code_hash LowCardinality(String) COMMENT 'Hash of the robot Python sources the node ran (src/**/*.py), so uncommitted changes show',
    git_rev LowCardinality(String) COMMENT 'git describe of the deployed tree (REVISION written by deploy.sh), -dirty with uncommitted changes',
    versions Map(LowCardinality(String), String) COMMENT 'python, numpy, numba, nats-py and other package versions',
    env Map(LowCardinality(String), String) COMMENT 'Settings from the environment: SIM_*, LOC_MODE, USE_*, ROBOCLAW_PORT, NATS_URL',
    config Map(LowCardinality(String), String) COMMENT 'Every upper-case constant of the node and the lib modules it loaded, e.g. nav.Node.SAFETY_STOP, trip.DETOUR_HOLD',
    seq UInt64
)
ENGINE = ReplacingMergeTree
ORDER BY (run_id, ts, seq)
COMMENT 'One row per node start: code version, package versions, environment and every constant in effect. Answers which parameters and which code were running at a moment';

CREATE TABLE IF NOT EXISTS forge.node_metrics
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    node LowCardinality(String),
    instance_id String COMMENT 'Node process; resets of the counters below happen when it changes',
    boot_id LowCardinality(String),
    uptime_s Float32 COMMENT 'Seconds since the node process started',
    interval_s Nullable(Float32) COMMENT 'Seconds covered by this row (normally 10)',
    cpu_pct Nullable(Float32) COMMENT 'Process CPU over the interval, percent of one core (all threads)',
    rss_bytes Nullable(UInt64) COMMENT 'Resident memory of the process, bytes',
    threads Nullable(UInt16) COMMENT 'OS threads of the process',
    loop_lag_max_ms Nullable(Float32) COMMENT 'Worst asyncio event-loop lateness in the interval, ms; above 100 means callbacks, NATS reads and publishing stalled (GIL or blocking calls)',
    loop_lag_mean_ms Nullable(Float32),
    sent_msgs UInt32 COMMENT 'NATS messages published in the interval',
    sent_bytes UInt64,
    received_msgs UInt32 COMMENT 'NATS messages received in the interval',
    received_bytes UInt64,
    reconnects UInt32 COMMENT 'Cumulative NATS reconnects of this process',
    dropped_publishes UInt64 COMMENT 'Cumulative publishes dropped while NATS reconnected',
    log_dropped UInt64 COMMENT 'Cumulative log records lost because the queue was full',
    events UInt32 COMMENT 'Events published in the interval',
    events_suppressed UInt32 COMMENT 'Events skipped by per-name rate limits in the interval',
    events_dropped UInt32 COMMENT 'Events dropped by the node-wide limit (20/s) in the interval; should be 0',
    callback_errors UInt64 COMMENT 'Cumulative exceptions caught in subscriptions, intervals and tasks',
    values Map(LowCardinality(String), Float64) COMMENT 'Node-specific timings over the interval as <name>_max, _mean, _count: nav control_ms and control_period_ms, planner plan_ms and map_build_ms, rabbit-zed grab_ms, frame_ms and gil_gap_ms, task_<name>_tps'
)
ENGINE = MergeTree
ORDER BY (run_id, node, ts)
COMMENT 'Per-node process health every 10 s: CPU, memory, event-loop stalls, NATS traffic and drops, error counters and loop timings';

CREATE TABLE IF NOT EXISTS forge.nats_server
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock',
    boot_id LowCardinality(String) DEFAULT '',
    connections UInt32 COMMENT 'Client connections',
    subscriptions UInt32,
    slow_consumers UInt64 COMMENT 'Cumulative slow-consumer events since the server started: the server dropped messages for a client that could not keep up; any increase is message loss',
    in_msgs UInt64 COMMENT 'Cumulative messages received by the server',
    out_msgs UInt64,
    in_bytes UInt64,
    out_bytes UInt64,
    mem_bytes UInt64 COMMENT 'Server resident memory, bytes',
    cpu_pct Float32 COMMENT 'Server CPU, percent of one core',
    slow_consumer_stats Map(LowCardinality(String), UInt64) COMMENT 'Slow consumers by client kind: clients, routes, gateways, leafs'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'Robot NATS server from its monitoring endpoint (/varz) every 5 s, sampled by the telemetry node at 1 Hz';

CREATE TABLE IF NOT EXISTS forge.lidar_health
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock (Raspberry Pi of Rabbit 2.0)',
    connected Bool COMMENT 'The RPLIDAR C1 answered and is scanning',
    model Nullable(UInt8) COMMENT 'Device model byte from GET_INFO (0x41 for a C1)',
    firmware LowCardinality(String) DEFAULT '' COMMENT 'Device firmware major.minor',
    device_health LowCardinality(String) DEFAULT '' COMMENT 'GET_HEALTH status: good, warning or error (protection stop; rabbit-lidar resets the device)',
    error_code Nullable(UInt16) COMMENT 'GET_HEALTH error code',
    scan_hz Float32 COMMENT 'Full rotations per second over the last 2 s; 10 nominal, the safety loop treats a scan older than 0.3 s as stale',
    points Float32 COMMENT 'Mean points per rotation with a return and outside the masked sectors (about 450-500 at 5 kHz and 10 Hz)',
    measurements Float32 COMMENT 'Mean measurements per rotation including the ones without a return',
    rotation_s Nullable(Float32) COMMENT 'Duration of the last rotation, s (ts_end - ts_start of the scan)',
    scan_age_s Nullable(Float32) COMMENT 'Seconds since the last full rotation was published',
    rotations UInt64 COMMENT 'Rotations published since the node started (the scan seq)',
    bad_nodes UInt64 COMMENT 'Cumulative 5-byte nodes that failed the start-flag or check-bit test (UART noise or a lost byte); each costs a one-byte resync',
    skipped_bytes UInt64 COMMENT 'Cumulative bytes skipped while resynchronising',
    short_rotations UInt64 COMMENT 'Cumulative rotations dropped because they had fewer than 50 measurements (motor spin-up, restarts)',
    restarts UInt32 COMMENT 'Scan restarts after 1 s without a full rotation',
    reconnects UInt32 COMMENT 'Times the serial port was reopened',
    errors UInt32 COMMENT 'Cumulative failed starts and I/O errors',
    sector_min_m Array(Nullable(Float32)) DEFAULT [] COMMENT 'Nearest return per 30 deg sector of the last scan, m, in the robot frame: sector 0 starts straight ahead and sectors run counter-clockwise (left) seen from above, so 5-6 are behind; NULL when the sector is empty'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'RPLIDAR C1 health at 1 Hz from rabbit-lidar. The scans themselves (rabbit.lidar.scan, 10 Hz, ~2 kB) are not stored: ~70 MB/h raw; the per-second sector minimums and the safety_state clearances answer "what did the lidar see"';

CREATE TABLE IF NOT EXISTS forge.tof_health
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock (Raspberry Pi)',
    sensor LowCardinality(String) COMMENT 'FL, FR (front left and right, on i2c-3 and i2c-4), RL, RR (rear, on i2c-5 and i2c-6)',
    bus UInt8 COMMENT 'Linux I2C bus number',
    state LowCardinality(String) COMMENT 'starting (firmware upload, ~2 s), ranging or failed',
    hz Float32 COMMENT 'Frames in the last second; 15 nominal for 8x8 zones',
    frame_age_s Nullable(Float32) COMMENT 'Seconds since the last frame; the safety loop treats a sensor older than 0.25 s as stale',
    valid Nullable(UInt8) COMMENT 'Zones of the last frame with a valid range (target status 5 or 9, 2 cm - 4 m), of 64',
    floor Nullable(UInt8) COMMENT 'Valid zones rejected as floor (point lower than 3 cm); the sensors look 15 deg up from 6 cm, so the floor appears from ~0.46 m',
    overhead Nullable(UInt8) COMMENT 'Valid zones rejected as higher than the robot (above 0.26 m)',
    obstacles UInt8 COMMENT 'Zones of the last frame reported as near-field obstacles in the robot frame',
    nearest_m Nullable(Float32) COMMENT 'Horizontal distance from the sensor to the nearest obstacle point of the last frame, m',
    errors UInt32 COMMENT 'Cumulative read and start errors of this sensor',
    resets UInt32 COMMENT 'Cumulative re-initialisations after a failed start or 0.5 s without a frame',
    init_s Nullable(Float32) COMMENT 'Seconds the last start took (firmware upload and configuration)',
    power_cycles UInt32 COMMENT 'Cumulative power cycles of all four sensors (TOF_PWR_OFF) after one failed three times in a row'
)
ENGINE = MergeTree
ORDER BY (run_id, sensor, ts)
COMMENT 'VL53L8CX near-field ToF sensors, one row per sensor at 1 Hz from rabbit-tof. The frames (rabbit.tof, 4 x 15 Hz, zones and obstacle points) are not stored';

CREATE TABLE IF NOT EXISTS forge.safety_state
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock (Raspberry Pi)',
    mode LowCardinality(String) COMMENT 'ok, limited (the command was slowed), stopped (the command was cut to zero) or estop (the E-stop line is low: hard stop)',
    reason LowCardinality(String) COMMENT 'What limited or stopped the current command: obstacle ahead/behind <m> m, lidar stale, tof <sensor> stale, front/rear bumper, crawling off the bumper, ina stale, battery low/critical, brain lost, estop by <source>, power stopping, roboclaw lost, overcurrent, estop_line_fault, self test <phase>; empty when the command passed',
    reasons Array(String) COMMENT 'Every active constraint, also the ones not binding the current command',
    shadow Bool COMMENT 'Shadow mode: rabbit-safety computes and reports but roboclaw and steering still obey rabbit.cmd.* and the E-stop line is not driven',
    estop_line Bool COMMENT 'ESTOP_RUN (GPIO16) high: the RoboClaw may drive. Low on any hard stop, before the self-test passes and whenever the process is not running',
    estop_latched Bool COMMENT 'A software E-stop (rabbit.safety.estop) is latched until rabbit.safety.reset',
    estop_source LowCardinality(String) DEFAULT '' COMMENT 'Who latched it: hud, forge, power',
    self_test LowCardinality(String) COMMENT 'E-stop line self-test: waiting (inputs not fresh yet), line_low, line_high, passed, failed (estop_line_fault: motors never allowed) or skipped (shadow)',
    speed Float32 COMMENT 'Allowed speed sent on rabbit.safety.drive, duty -1..1 (0.464 m/s per unit)',
    steer Float32 COMMENT 'Steering sent on rabbit.safety.drive, -1..1',
    requested_speed Float32 COMMENT 'Speed of the winning command before the limits, duty',
    requested_steer Float32,
    source LowCardinality(String) COMMENT 'Winning command: joystick, nav, forge, hud, e2e; none without a fresh command; nav rejected while the brain is lost',
    owner LowCardinality(String) COMMENT 'joystick for 1 s after active gamepad input, else auto',
    cap_fwd Float32 COMMENT 'Highest forward speed allowed right now, duty',
    cap_rev Float32 COMMENT 'Highest reverse speed allowed right now, duty',
    clearance_fwd_m Nullable(Float32) COMMENT 'Free travel forward along the commanded arc with the 2.0 footprint, from fresh lidar and ToF points, m (capped at 1 m); NULL without a fresh range sensor',
    clearance_rev_m Nullable(Float32) COMMENT 'Free travel in reverse, m',
    brain_ok Bool COMMENT 'rabbit.nav.state (the Jetson) heard within 0.5 s',
    bumper_front Bool COMMENT 'Front bumper pressed (or its wire broken)',
    bumper_rear Bool,
    battery_low Bool COMMENT 'Battery mean over 5 s at or below 13.2 V: speed halved',
    battery_critical Bool COMMENT 'Battery at or below 12.8 V for 10 s: stopped; rabbit-power shuts down',
    power_state LowCardinality(String) COMMENT 'Last rabbit.power.state',
    input_age_s Map(LowCardinality(String), Float32) COMMENT 'Age of each input, s: command, brain, roboclaw, ina, lidar, tof_FL, tof_FR, tof_RL, tof_RR; a missing key was never heard'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'rabbit-safety (Raspberry Pi, the independent safety loop of Rabbit 2.0) at 10 Hz: mode, the binding reason, allowed vs requested command, per-direction caps and clearances, E-stop line and input freshness. rabbit.safety.drive (50 Hz) is not stored: these rows carry the same command. Decisions are events from node safety';

CREATE TABLE IF NOT EXISTS forge.power_state
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock (Raspberry Pi)',
    state LowCardinality(String) COMMENT 'booting, body_ready (safety self-tested), running (brain heard), jetson_cycle (Jetson power off 5 s), stopping (E-stop, nav cancel, map save), jetson_halt (waiting for the Jetson to power off), jetson_off, pi_halt',
    reason String COMMENT 'Why the supervisor entered the state: button held 2 s, battery below 12.8 V for 10 s, requested by <source>, map saved, Jetson current ...',
    state_s Float32 COMMENT 'Seconds in the state',
    battery_v Nullable(Float32) COMMENT 'Last battery voltage from rabbit.ina, V',
    battery_low Bool COMMENT 'Battery mean over 5 s at or below 13.2 V',
    charge_pct Nullable(Float32) COMMENT 'Battery charge estimate from rabbit.ina, percent',
    jetson_a Nullable(Float32) COMMENT 'Jetson 12 V current (INA channel jetson_12v), A; NULL until that channel exists',
    brain_ok Bool COMMENT 'rabbit.nav.state heard within 1 s',
    safety_ready Bool COMMENT 'rabbit-safety reports a passed (or skipped) self-test',
    button Bool COMMENT 'Power button pressed',
    jetson_cycles_last_hour UInt8 COMMENT 'Jetson power cycles in the last hour (at most 2 automatic ones)'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
COMMENT 'rabbit-power (host service on the Raspberry Pi) at 1 Hz and on every state change: the shutdown state machine, battery policy and Jetson power. Transitions are also power.state_changed events';
