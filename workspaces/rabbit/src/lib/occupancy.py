import numpy as np


COSTMAP_UNKNOWN = 0
COSTMAP_TRAVERSABLE = 1
COSTMAP_CAUTION = 2
COSTMAP_BLOCKED = 3


class OccupancyGrid:
    """2D log-odds occupancy grid with vectorized raycasting and inflation."""

    CELL_SIZE = 0.05  # meters per cell
    GRID_SIZE = 200  # cells per side (200x200 = 10m x 10m)

    # Height filter (Y-up)
    FLOOR_MIN = 0.03
    ROBOT_HEIGHT = 0.40

    # Log-odds
    L_OCC = 0.85
    L_FREE = -0.4
    L_MIN = -2.0
    L_MAX = 3.5
    OCC_THRESHOLD = 0.0

    # Inflation
    ROBOT_RADIUS = 0.20  # meters
    CAUTION_RADIUS = 0.30

    # Range limit
    MAX_RANGE_M = 5.0

    # Max rays per update (cap for performance)
    MAX_RAYS = 500

    def __init__(self):
        self.grid = np.zeros((self.GRID_SIZE, self.GRID_SIZE), dtype=np.float32)
        self.origin_x = 0.0  # world X of grid cell (0,0)
        self.origin_z = 0.0  # world Z of grid cell (0,0)
        self._inflation_kernel = self._make_disk_kernel(self.ROBOT_RADIUS)
        self._caution_kernel = self._make_disk_kernel(self.CAUTION_RADIUS)

    def _make_disk_kernel(self, radius_m: float) -> np.ndarray:
        r_cells = int(np.ceil(radius_m / self.CELL_SIZE))
        y, x = np.ogrid[-r_cells : r_cells + 1, -r_cells : r_cells + 1]
        return ((x * x + y * y) <= r_cells * r_cells).astype(np.uint8)

    def world_to_cell(self, wx: float, wz: float) -> tuple[int, int]:
        cx = int((wx - self.origin_x) / self.CELL_SIZE)
        cz = int((wz - self.origin_z) / self.CELL_SIZE)
        return cx, cz

    def recenter(self, robot_x: float, robot_z: float):
        """Shift grid so robot is near center. Preserves overlapping data."""
        half = self.GRID_SIZE * self.CELL_SIZE * 0.5
        new_origin_x = robot_x - half
        new_origin_z = robot_z - half

        shift_x = int(round((self.origin_x - new_origin_x) / self.CELL_SIZE))
        shift_z = int(round((self.origin_z - new_origin_z) / self.CELL_SIZE))

        if shift_x == 0 and shift_z == 0:
            return

        new_grid = np.zeros_like(self.grid)

        src_x0 = max(0, -shift_x)
        src_x1 = min(self.GRID_SIZE, self.GRID_SIZE - shift_x)
        src_z0 = max(0, -shift_z)
        src_z1 = min(self.GRID_SIZE, self.GRID_SIZE - shift_z)

        dst_x0 = max(0, shift_x)
        dst_x1 = dst_x0 + (src_x1 - src_x0)
        dst_z0 = max(0, shift_z)
        dst_z1 = dst_z0 + (src_z1 - src_z0)

        if src_x1 > src_x0 and src_z1 > src_z0:
            new_grid[dst_z0:dst_z1, dst_x0:dst_x1] = self.grid[
                src_z0:src_z1, src_x0:src_x1
            ]

        self.grid = new_grid
        self.origin_x = new_origin_x
        self.origin_z = new_origin_z

    def update(
        self,
        robot_x: float,
        robot_z: float,
        points_xyz: np.ndarray,
    ):
        if len(points_xyz) == 0:
            return

        # Height filter
        y = points_xyz[:, 1]
        mask = (y > self.FLOOR_MIN) & (y < self.ROBOT_HEIGHT)
        pts = points_xyz[mask]
        if len(pts) == 0:
            return

        # Recenter if needed
        cx, cz = self.world_to_cell(robot_x, robot_z)
        margin = self.GRID_SIZE // 4
        if (
            cx < margin
            or cx >= self.GRID_SIZE - margin
            or cz < margin
            or cz >= self.GRID_SIZE - margin
        ):
            self.recenter(robot_x, robot_z)

        robot_cx, robot_cz = self.world_to_cell(robot_x, robot_z)

        # Convert to cell coordinates
        obs_cx = ((pts[:, 0] - self.origin_x) / self.CELL_SIZE).astype(np.int32)
        obs_cz = ((pts[:, 2] - self.origin_z) / self.CELL_SIZE).astype(np.int32)

        # Filter in-bounds and within range
        max_range_cells = int(self.MAX_RANGE_M / self.CELL_SIZE)
        dx = obs_cx - robot_cx
        dz = obs_cz - robot_cz
        dist_sq = dx * dx + dz * dz
        valid = (
            (obs_cx >= 0)
            & (obs_cx < self.GRID_SIZE)
            & (obs_cz >= 0)
            & (obs_cz < self.GRID_SIZE)
            & (dist_sq <= max_range_cells * max_range_cells)
        )
        obs_cx = obs_cx[valid]
        obs_cz = obs_cz[valid]

        if len(obs_cx) == 0:
            return

        # Deduplicate obstacle cells
        unique_cells = np.unique(np.stack([obs_cx, obs_cz], axis=1), axis=0)
        obs_cx = unique_cells[:, 0]
        obs_cz = unique_cells[:, 1]

        # Subsample rays if too many
        if len(obs_cx) > self.MAX_RAYS:
            idx = np.random.choice(len(obs_cx), self.MAX_RAYS, replace=False)
            obs_cx = obs_cx[idx]
            obs_cz = obs_cz[idx]

        # Mark obstacle cells as occupied
        np.add.at(self.grid, (obs_cz, obs_cx), self.L_OCC)

        # Vectorized raycasting for free space
        self._mark_free_vectorized(robot_cx, robot_cz, obs_cx, obs_cz)

        # Clamp
        np.clip(self.grid, self.L_MIN, self.L_MAX, out=self.grid)

    def _mark_free_vectorized(
        self,
        rx: int,
        rz: int,
        obs_cx: np.ndarray,
        obs_cz: np.ndarray,
    ):
        """Mark free cells along rays using vectorized sampling."""
        n_rays = len(obs_cx)
        if n_rays == 0:
            return

        gs = self.GRID_SIZE
        l_free = self.L_FREE

        # For each ray, sample cells along it (excluding endpoint)
        # Use parametric line: p(t) = robot + t * (obs - robot), t in [0, 1)
        dx = obs_cx - rx  # (n_rays,)
        dz = obs_cz - rz
        max_steps = np.maximum(np.abs(dx), np.abs(dz))  # (n_rays,)

        # Cap steps for performance
        max_steps = np.minimum(max_steps, 100)

        # Process all rays at once by iterating over step index
        max_step = int(max_steps.max()) if n_rays > 0 else 0

        for step in range(max_step):
            # Which rays are still active at this step (not yet at endpoint)
            active = max_steps > step
            if not np.any(active):
                break

            # Parametric t for this step
            t = np.zeros(n_rays, dtype=np.float32)
            nonzero = max_steps > 0
            t[nonzero] = step / max_steps[nonzero].astype(np.float32)

            cx = (rx + t * dx).astype(np.int32)
            cz = (rz + t * dz).astype(np.int32)

            # Filter: active, in-bounds, not at endpoint
            valid = (
                active
                & (cx >= 0)
                & (cx < gs)
                & (cz >= 0)
                & (cz < gs)
                & ~((cx == obs_cx) & (cz == obs_cz))
            )

            if np.any(valid):
                np.add.at(self.grid, (cz[valid], cx[valid]), l_free)

    def get_costmap(self) -> np.ndarray:
        """Threshold log-odds grid into costmap with inflation."""
        occupied = self.grid > self.OCC_THRESHOLD
        free = self.grid < self.OCC_THRESHOLD

        # Inflate occupied cells
        blocked = self._dilate(occupied, self._inflation_kernel)
        caution_zone = self._dilate(occupied, self._caution_kernel) & ~blocked

        costmap = np.full(
            (self.GRID_SIZE, self.GRID_SIZE), COSTMAP_UNKNOWN, dtype=np.uint8
        )
        costmap[free & ~blocked & ~caution_zone] = COSTMAP_TRAVERSABLE
        costmap[caution_zone & free] = COSTMAP_CAUTION
        costmap[blocked] = COSTMAP_BLOCKED

        return costmap

    def _dilate(self, mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """Binary dilation via convolution."""
        from numpy.lib.stride_tricks import as_strided

        kh, kw = kernel.shape
        ph, pw = kh // 2, kw // 2

        padded = np.pad(mask.astype(np.uint8), ((ph, ph), (pw, pw)), mode="constant")
        h, w = mask.shape
        strides = padded.strides
        windows = as_strided(
            padded,
            shape=(h, w, kh, kw),
            strides=(strides[0], strides[1], strides[0], strides[1]),
        )
        return np.any(windows & kernel[np.newaxis, np.newaxis, :, :], axis=(2, 3))
