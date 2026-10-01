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
SETTINGS non_replicated_deduplication_window = 1000
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
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    left_command Float32 COMMENT 'Commanded duty for the left motor (M1), -1..1' CODEC(Gorilla, ZSTD(1)),
    left_pwm Float32 COMMENT 'Applied PWM duty for the left motor, -1..1' CODEC(Gorilla, ZSTD(1)),
    left_current Float32 COMMENT 'Left motor current, A' CODEC(Gorilla, ZSTD(1)),
    left_speed Int32 COMMENT 'Measured left wheel speed, encoder counts/s; always 0 for now because the encoders are not connected' CODEC(Delta, ZSTD(1)),
    left_encoder Int64 COMMENT 'Left encoder position, counts; always 0 for now because the encoders are not connected' CODEC(Delta, ZSTD(1)),
    right_command Float32 COMMENT 'Commanded duty for the right motor (M2), -1..1' CODEC(Gorilla, ZSTD(1)),
    right_pwm Float32 COMMENT 'Applied PWM duty for the right motor, -1..1' CODEC(Gorilla, ZSTD(1)),
    right_current Float32 COMMENT 'Right motor current, A' CODEC(Gorilla, ZSTD(1)),
    right_speed Int32 COMMENT 'Measured right wheel speed, encoder counts/s; always 0 for now because the encoders are not connected' CODEC(Delta, ZSTD(1)),
    right_encoder Int64 COMMENT 'Right encoder position, counts; always 0 for now because the encoders are not connected' CODEC(Delta, ZSTD(1)),
    supply_voltage Float32 COMMENT '12 V buck converter output feeding the RoboClaw, V; not the battery (see power.battery_voltage)' CODEC(Gorilla, ZSTD(1)),
    temperature Float32 COMMENT 'RoboClaw board temperature, C' CODEC(Gorilla, ZSTD(1)),
    status UInt32 COMMENT 'RoboClaw status bit flags, 0 is normal' CODEC(ZSTD(1)),
    errors UInt32 COMMENT 'Cumulative count of failed serial commands since the node started' CODEC(Delta, ZSTD(1)),
    retries UInt32 DEFAULT 0 COMMENT 'Cumulative serial command retries since the node started; a rising count means a noisy or failing serial link' CODEC(Delta, ZSTD(1)),
    reconnects UInt32 DEFAULT 0 COMMENT 'Times the node reopened the serial port since it started' CODEC(Delta, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'RoboClaw motor controller at 50 Hz: both drive motors and the battery';

CREATE TABLE IF NOT EXISTS forge.power
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    battery_voltage Float32 COMMENT 'Battery voltage (INA channel 1), V; 99 Wh 4S Li-ion V-mount pack, 16.8 V full, 14.8 V nominal' CODEC(Gorilla, ZSTD(1)),
    battery_current Float32 COMMENT 'Total battery current, A: motors through the 12 V buck, Jetson, camera and servos' CODEC(Gorilla, ZSTD(1)),
    battery_power Float32 COMMENT 'Total battery power, W' CODEC(Gorilla, ZSTD(1)),
    battery_charge_pct Nullable(Float32) COMMENT 'State-of-charge estimate from the 4S Li-ion voltage curve, percent; it reads low under load; NULL before the robot published it' CODEC(Gorilla, ZSTD(1)),
    rail_6v_voltage Float32 COMMENT '6 V servo rail voltage (INA channel 2), V' CODEC(Gorilla, ZSTD(1)),
    rail_6v_current Float32 COMMENT '6 V servo rail current, A' CODEC(Gorilla, ZSTD(1)),
    rail_6v_power Float32 COMMENT '6 V servo rail power, W' CODEC(Gorilla, ZSTD(1)),
    errors UInt32 COMMENT 'Cumulative INA read errors since the node started' CODEC(Delta, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'INA4235 power monitor at 50 Hz: the battery (channel 1) and the 6 V servo rail (channel 2)';

CREATE TABLE IF NOT EXISTS forge.steering
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    angle Float32 COMMENT 'Applied steering angle, -1 (full left) .. 1 (full right)' CODEC(Gorilla, ZSTD(1)),
    pulse_us Float32 COMMENT 'Servo pulse width, microseconds (1500 is centered)' CODEC(Gorilla, ZSTD(1)),
    errors UInt32 DEFAULT 0 COMMENT 'Cumulative failed servo writes since the node started' CODEC(Delta, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Steering servo at 20 Hz';

CREATE TABLE IF NOT EXISTS forge.imu
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    accel_x Float32 COMMENT 'Linear acceleration including gravity, m/s2 (camera frame, gravity is mostly on y)' CODEC(Gorilla, ZSTD(1)),
    accel_y Float32 COMMENT 'Linear acceleration including gravity, m/s2' CODEC(Gorilla, ZSTD(1)),
    accel_z Float32 COMMENT 'Linear acceleration including gravity, m/s2' CODEC(Gorilla, ZSTD(1)),
    gyro_x Float32 COMMENT 'Angular velocity, deg/s' CODEC(Gorilla, ZSTD(1)),
    gyro_y Float32 COMMENT 'Angular velocity, deg/s' CODEC(Gorilla, ZSTD(1)),
    gyro_z Float32 COMMENT 'Angular velocity, deg/s' CODEC(Gorilla, ZSTD(1)),
    qx Float32 COMMENT 'IMU orientation quaternion' CODEC(Gorilla, ZSTD(1)),
    qy Float32 CODEC(Gorilla, ZSTD(1)),
    qz Float32 CODEC(Gorilla, ZSTD(1)),
    qw Float32 CODEC(Gorilla, ZSTD(1)),
    g Float32 DEFAULT sqrt(accel_x * accel_x + accel_y * accel_y + accel_z * accel_z) / 9.80665 COMMENT 'Magnitude of total acceleration, g; 1 at rest' CODEC(Gorilla, ZSTD(1)),
    samples UInt16 DEFAULT 1 COMMENT 'Raw IMU samples averaged into this row'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'ZED 2i IMU, published by the camera node at about 30 Hz';

CREATE TABLE IF NOT EXISTS forge.pose
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    frame_number UInt64 CODEC(Delta, ZSTD(1)),
    x Float32 COMMENT 'Position in the ZED world frame, m' CODEC(Gorilla, ZSTD(1)),
    y Float32 COMMENT 'Position in the ZED world frame, m' CODEC(Gorilla, ZSTD(1)),
    z Float32 COMMENT 'Position in the ZED world frame, m' CODEC(Gorilla, ZSTD(1)),
    qx Float32 COMMENT 'Orientation quaternion in the world frame' CODEC(Gorilla, ZSTD(1)),
    qy Float32 CODEC(Gorilla, ZSTD(1)),
    qz Float32 CODEC(Gorilla, ZSTD(1)),
    qw Float32 CODEC(Gorilla, ZSTD(1)),
    roll_deg Float32 DEFAULT 0 COMMENT 'Euler angles of the orientation, deg' CODEC(Gorilla, ZSTD(1)),
    pitch_deg Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    yaw_deg Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    vx Float32 DEFAULT 0 COMMENT 'Linear velocity in the camera frame, m/s' CODEC(Gorilla, ZSTD(1)),
    vy Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    vz Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    wx Float32 DEFAULT 0 COMMENT 'Angular velocity from the pose estimate' CODEC(Gorilla, ZSTD(1)),
    wy Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    wz Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    std_x Float32 DEFAULT 0 COMMENT 'Position standard deviation, m' CODEC(Gorilla, ZSTD(1)),
    std_y Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    std_z Float32 DEFAULT 0 CODEC(Gorilla, ZSTD(1)),
    confidence UInt8 DEFAULT 0 COMMENT 'Tracking confidence, 0-100'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'ZED positional tracking at about 30 Hz; only frames with tracking OK are published';

CREATE TABLE IF NOT EXISTS forge.magnetometer
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    field_x Float32 COMMENT 'Magnetic field, microtesla' CODEC(Gorilla, ZSTD(1)),
    field_y Float32 COMMENT 'Magnetic field, microtesla' CODEC(Gorilla, ZSTD(1)),
    field_z Float32 COMMENT 'Magnetic field, microtesla' CODEC(Gorilla, ZSTD(1)),
    heading_deg Float32 COMMENT 'Magnetic heading, deg; meaningless while heading_state is NOT_CALIBRATED' CODEC(Gorilla, ZSTD(1)),
    heading_state LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'ZED magnetometer at 50 Hz';

CREATE TABLE IF NOT EXISTS forge.barometer
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    pressure_hpa Float32 COMMENT 'Barometric pressure, hPa' CODEC(Gorilla, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'ZED barometer at 25 Hz';

CREATE TABLE IF NOT EXISTS forge.jetson
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
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
    fan_rpm UInt32
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Jetson Orin board telemetry at 1 Hz';

CREATE TABLE IF NOT EXISTS forge.jetson_containers
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    name LowCardinality(String) COMMENT 'Docker container name on the Jetson, e.g. rabbit-zed, rabbit-roboclaw',
    cpu Float32 COMMENT 'CPU usage, percent of one core (can exceed 100)',
    mem_bytes UInt64,
    mem_limit_bytes UInt64
)
ENGINE = MergeTree
ORDER BY (run_id, name, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Per-container CPU and memory on the Jetson at 1 Hz, one row per container per sample';

CREATE TABLE IF NOT EXISTS forge.zed_health
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
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
    temp_onboard_right Float32 COMMENT 'C'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'ZED camera node health at 1 Hz';

CREATE TABLE IF NOT EXISTS forge.joy
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Receive time on the Forge host (gamepad messages carry no robot ts)' CODEC(DoubleDelta, ZSTD(1)),
    throttle Float32 COMMENT 'r2 minus l2 trigger, -1..1; the speed the driver asked for' CODEC(Gorilla, ZSTD(1)),
    steer Float32 COMMENT 'Left stick x, -1..1' CODEC(Gorilla, ZSTD(1)),
    raw String COMMENT 'Full DualSense JSON state' CODEC(ZSTD(3))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Gamepad commands at 30 Hz while a gamepad is connected';

CREATE TABLE IF NOT EXISTS forge.map_chunks
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Receive time on the Forge host' CODEC(DoubleDelta, ZSTD(1)),
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
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Spatial-map mesh chunk updates, one row each time a chunk changes its vertex or triangle count (summaries only; the mesh itself is not stored)';

CREATE TABLE IF NOT EXISTS forge.obstacle
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Camera frame time (robot clock)' CODEC(DoubleDelta, ZSTD(1)),
    nearest_distance Nullable(Float32) COMMENT 'Horizontal distance to the nearest obstacle point in range, m; NULL when nothing is in range' CODEC(Gorilla, ZSTD(1)),
    nearest_bearing_deg Nullable(Float32) COMMENT 'Bearing of the nearest point, deg; 0 is straight ahead' CODEC(Gorilla, ZSTD(1)),
    nearest_x Nullable(Float32) COMMENT 'Nearest point in the ZED world frame, m' CODEC(Gorilla, ZSTD(1)),
    nearest_y Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    nearest_z Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    ahead_distance Nullable(Float32) COMMENT 'Distance to the nearest point inside the driving corridor ahead, m; NULL when the corridor is clear' CODEC(Gorilla, ZSTD(1)),
    ahead_bearing_deg Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    ahead_x Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    ahead_y Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    ahead_z Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    blind Bool DEFAULT false COMMENT 'Too much of the depth image is invalid to see obstacles; navigation refuses to drive forward while blind',
    blind_fraction Nullable(Float32) COMMENT 'Share of the depth window without valid depth, 0..1' CODEC(Gorilla, ZSTD(1)),
    scan_angle_min_deg Nullable(Float32) COMMENT 'Bearing of the first scan bin, deg; 0 is straight ahead, negative is left',
    scan_angle_step_deg Nullable(Float32) COMMENT 'Width of one scan bin, deg',
    scan_ranges Array(Nullable(Float32)) DEFAULT [] COMMENT 'Nearest obstacle per bearing bin from the axle-centred scan the navigation safety governor uses, m; NULL when the bin is clear' CODEC(ZSTD(3))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Obstacles from the ZED depth map at 10 Hz';

CREATE TABLE IF NOT EXISTS forge.nav_state
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    mode LowCardinality(String) COMMENT 'idle, driving, maneuvering, blocked, arrived or fault',
    goal_x Nullable(Float32) COMMENT 'Goal in the ZED world frame (x, z), m; NULL without a goal',
    goal_z Nullable(Float32),
    distance_to_goal Float32 COMMENT 'm' CODEC(Gorilla, ZSTD(1)),
    heading_error_deg Float32 COMMENT 'Angle between heading and the goal direction, deg' CODEC(Gorilla, ZSTD(1)),
    speed Float32 COMMENT 'Commanded speed, duty -1..1' CODEC(Gorilla, ZSTD(1)),
    steer Float32 COMMENT 'Commanded steering, -1..1' CODEC(Gorilla, ZSTD(1)),
    path_points UInt16 COMMENT 'Points in the predicted path; the path itself is not stored',
    step_type LowCardinality(String) DEFAULT '' COMMENT 'Current mission step: turn, move or goto; empty without a mission',
    step_index UInt16 DEFAULT 0 COMMENT 'Current step, 1-based; 0 without a mission',
    steps_total UInt16 DEFAULT 0,
    turn_remaining_deg Nullable(Float32) COMMENT 'Heading change left in a turn step, deg',
    free_distance Nullable(Float32) COMMENT 'Free travel along the commanded arc from the safety governor, m: below 0.3 it holds the robot, below 0.6 it slows to the minimum speed' CODEC(Gorilla, ZSTD(1)),
    fault LowCardinality(String) DEFAULT '' COMMENT 'Why navigation stopped: stall, collision, blocked, step timeout, operator link lost, control error, manoeuvre failed, manual override or rejected: ...; empty when none. It stays set until the next mission',
    mission_id String DEFAULT '' COMMENT 'Mission the robot is executing (nav assigns it when it accepts a mission); empty between missions. Joins with logs.mission_id'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Autonomous navigation state at 10 Hz';

CREATE TABLE IF NOT EXISTS forge.drive
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when nav sent it, Forge host clock for commands from Forge, receive time on the Forge host for HUD commands (they carry no ts)' CODEC(DoubleDelta, ZSTD(1)),
    speed Float32 COMMENT 'Commanded speed, duty -1..1' CODEC(Gorilla, ZSTD(1)),
    steer Float32 COMMENT 'Commanded steering, -1..1' CODEC(Gorilla, ZSTD(1)),
    source LowCardinality(String) DEFAULT '' COMMENT 'Who sent it: nav (autonomous navigation after the safety governor), forge (chat stop) or hud (the operator HUD stop button)'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Drive commands on rabbit.cmd.drive: nav at 20 Hz while navigating, plus stop commands from Forge and the HUD (joy holds manual commands)';

CREATE TABLE IF NOT EXISTS forge.nav_events
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock for commands from the explore node, Forge host clock for commands from Forge, receive time on the Forge host for HUD commands' CODEC(DoubleDelta, ZSTD(1)),
    event Enum8('goal' = 1, 'cancel' = 2, 'mission' = 3),
    goal_x Nullable(Float32) COMMENT 'New goal (x, z) in the ZED world frame, m; NULL for cancel and mission',
    goal_z Nullable(Float32),
    steps String DEFAULT '' COMMENT 'Mission steps as JSON for mission events',
    source LowCardinality(String) DEFAULT '' COMMENT 'Who sent it: explore (autonomous exploration), forge (chat run_mission and stop) or hud (the operator HUD)'
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Navigation goals, missions and cancels';

CREATE TABLE IF NOT EXISTS forge.wifi
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
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
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Robot Wi-Fi link at 1 Hz from the telemetry node';

CREATE TABLE IF NOT EXISTS forge.explore_state
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock' CODEC(DoubleDelta, ZSTD(1)),
    exploration_id String DEFAULT '' COMMENT 'Exploration the explore node is running or last ran; joins with logs.fields exploration context',
    phase LowCardinality(String) COMMENT 'idle, planning, driving, done or failed',
    message String DEFAULT '' COMMENT 'Why the last exploration ended, e.g. distance limit reached, no reachable frontiers left, cancelled',
    elapsed_s Nullable(Float32) COMMENT 'Time since the exploration started, s',
    travelled_m Float32 COMMENT 'Distance driven in this exploration, m' CODEC(Gorilla, ZSTD(1)),
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
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Autonomous exploration state at 2 Hz from the explore node';

CREATE TABLE IF NOT EXISTS forge.operator_heartbeat
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Time the operator HUD sent it, Forge host clock (the HUD runs on the same Mac)' CODEC(DoubleDelta, ZSTD(1)),
    round_trip_ms Float32 COMMENT 'From the HUD through the robot NATS server back to the Forge writer, ms; it rises with Wi-Fi latency' CODEC(Gorilla, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Operator HUD heartbeats at about 2 Hz while the HUD is open; navigation trips with operator link lost after 3 s without one';

CREATE TABLE IF NOT EXISTS forge.command_events
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when the robot sent it, else receive time on the Forge host' CODEC(DoubleDelta, ZSTD(1)),
    subject LowCardinality(String) COMMENT 'rabbit.nav.explore (start an exploration) or rabbit.map.save (save the spatial map)',
    source LowCardinality(String) COMMENT 'Who sent it: explore, forge or hud',
    payload String COMMENT 'The command as JSON, e.g. the exploration limits' CODEC(ZSTD(3))
)
ENGINE = MergeTree
ORDER BY (run_id, ts)
SETTINGS non_replicated_deduplication_window = 1000
COMMENT 'Low-rate robot commands other than navigation goals, missions and cancels (see nav_events) and drive commands (see drive, joy)';

CREATE TABLE IF NOT EXISTS forge.kv_changes
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Time the robot NATS server stored the change (robot clock)' CODEC(DoubleDelta, ZSTD(1)),
    key LowCardinality(String) COMMENT 'Key in the robot rabbit key-value bucket, e.g. rabbit.zed.camera_settings, rabbit.zed.intrinsics',
    revision UInt64 COMMENT 'Bucket revision of the change',
    operation LowCardinality(String) COMMENT 'PUT, DEL or PURGE',
    value String COMMENT 'New value, usually JSON; camera settings hold BRIGHTNESS, CONTRAST, GAIN, EXPOSURE, AEC_AGC (auto exposure), WHITEBALANCE_AUTO and similar' CODEC(ZSTD(3))
)
ENGINE = ReplacingMergeTree
ORDER BY (run_id, ts, key, revision)
COMMENT 'Changes of the robot configuration in its key-value bucket (camera settings and intrinsics, operator and UI state); the writer also records the current value of every key when it starts';

CREATE TABLE IF NOT EXISTS forge.logs
(
    run_id LowCardinality(String),
    ts DateTime64(9, 'UTC') COMMENT 'Robot wall clock when the log record was created' CODEC(DoubleDelta, ZSTD(1)),
    node LowCardinality(String) COMMENT 'Robot node that logged it: rabbit-zed, nav, explore, roboclaw, steering, ina4235 or telemetry (container lifecycle events come from telemetry with logger docker.events)',
    level Enum8('debug' = 10, 'info' = 20, 'warning' = 30, 'error' = 40, 'critical' = 50) COMMENT 'Compare as level >= ''warning'' to keep warnings and worse',
    logger LowCardinality(String) COMMENT 'Python logger name: the node name, a library such as nats, or docker.events',
    message String COMMENT 'Formatted message' CODEC(ZSTD(3)),
    template String COMMENT 'Message before argument substitution; equal to message for logs written with f-strings' CODEC(ZSTD(3)),
    exception_type LowCardinality(String) COMMENT 'Exception class, e.g. OSError; empty without one',
    exception String COMMENT 'Full traceback; empty without one' CODEC(ZSTD(3)),
    location LowCardinality(String) COMMENT 'module:function:line that logged it',
    fields Map(LowCardinality(String), String) COMMENT 'Structured fields: extra values the node attached (fault, container, exit_code, action, steps) and context such as exploration_id' CODEC(ZSTD(3)),
    mission_id String COMMENT 'Mission nav was executing when the record was logged (nav only); joins with nav_state.mission_id',
    map_session String COMMENT 'ZED mapping session at the time (rabbit-zed and explore)',
    repeats UInt32 COMMENT 'Identical records (same logger, level, template with numbers ignored, exception) suppressed in the 10 s before this one; the record stands for 1 + repeats occurrences',
    pid UInt32 COMMENT 'Process id inside the container; a new pid means the node restarted',
    seq UInt64 COMMENT 'Sequence in the robot LOGS JetStream stream',
    fingerprint UInt64 MATERIALIZED cityHash64(node, logger, exception_type, replaceRegexpAll(template, '[0-9]+(\\.[0-9]+)?', '#')) COMMENT 'Groups records of the same kind regardless of the numbers in them',
    INDEX message_text message TYPE text(tokenizer = splitByNonAlpha, preprocessor = lower(message)),
    INDEX exception_text exception TYPE text(tokenizer = splitByNonAlpha, preprocessor = lower(exception))
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (run_id, ts, seq)
TTL toDateTime(ts) + INTERVAL 30 DAY DELETE WHERE level < 'warning', toDateTime(ts) + INTERVAL 180 DAY
COMMENT 'Log records of every robot node, shipped through the robot LOGS JetStream stream so nothing is lost while the Wi-Fi is down. Search words with hasAllTokens(message, ''word another''), case-insensitive. Info and debug are kept 30 days, warnings and worse 180 days';
