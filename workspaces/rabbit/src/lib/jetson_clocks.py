from pathlib import Path

OC_HWMON_NAME = "soctherm_oc"
OC_LEVELS = (1, 2, 3)


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def to_mhz(value: int | None, per_mhz: int) -> int | None:
    return None if value is None else round(value / per_mhz)


class JetsonClocks:
    """Reads the clocks the Jetson actually runs at, their floors and the soctherm over-current counters from sysfs."""

    def __init__(self, sys_root: str = "/sys"):
        root = Path(sys_root)
        self.cpus = sorted(
            (path for path in (root / "devices/system/cpu").glob("cpu[0-9]*") if (path / "cpufreq").is_dir()),
            key=lambda path: int(path.name[3:]),
        )
        self.gpu = next(iter(sorted((root / "class/devfreq").glob("*gpu*"))), None)
        self.oc = next(
            (
                path
                for path in sorted((root / "class/hwmon").glob("hwmon*"))
                if (path / "name").is_file() and (path / "name").read_text().strip() == OC_HWMON_NAME
            ),
            None,
        )
        self.oc_time = root / "kernel/debug/bpmp/debug/soctherm/oc2/event_time"

    def _per_cpu(self, name: str) -> list[int]:
        values = [to_mhz(read_int(cpu / "cpufreq" / name), 1000) for cpu in self.cpus]
        return [] if any(value is None for value in values) else values

    def read(self) -> dict:
        return {
            "cpu_cur_mhz": self._per_cpu("cpuinfo_cur_freq"),
            "cpu_min_mhz": self._per_cpu("scaling_min_freq"),
            "gpu_min_mhz": None if self.gpu is None else to_mhz(read_int(self.gpu / "min_freq"), 1_000_000),
            "gpu_max_mhz": None if self.gpu is None else to_mhz(read_int(self.gpu / "max_freq"), 1_000_000),
            "oc_events": None
            if self.oc is None
            else [read_int(self.oc / f"oc{level}_event_cnt") for level in OC_LEVELS],
            "oc_throttle_ticks": read_int(self.oc_time),
        }
