import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.jetson_clocks import JetsonClocks


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_reads_actual_clocks_floors_and_over_current_counters(tmp_path: Path):
    for cpu, actual in ((0, "864000\n"), (4, "1728000\n")):
        write(tmp_path / f"devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_cur_freq", actual)
        write(tmp_path / f"devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq", "1728000\n")
        write(tmp_path / f"devices/system/cpu/cpu{cpu}/cpufreq/scaling_min_freq", "1728000\n")
    write(tmp_path / "devices/system/cpu/cpufreq/policy0/scaling_min_freq", "729600\n")
    write(tmp_path / "class/devfreq/17000000.gpu/min_freq", "1020000000\n")
    write(tmp_path / "class/devfreq/17000000.gpu/max_freq", "1020000000\n")
    write(tmp_path / "class/hwmon/hwmon1/name", "ina3221\n")
    write(tmp_path / "class/hwmon/hwmon3/name", "soctherm_oc\n")
    for level, count in ((1, "0"), (2, "0"), (3, "27390")):
        write(tmp_path / f"class/hwmon/hwmon3/oc{level}_event_cnt", count)

    assert JetsonClocks(str(tmp_path)).read() == {
        "cpu_cur_mhz": [864, 1728],
        "cpu_min_mhz": [1728, 1728],
        "gpu_min_mhz": 1020,
        "gpu_max_mhz": 1020,
        "oc_events": [0, 0, 27390],
        "oc_throttle_ticks": None,
    }


def test_reports_nothing_rather_than_a_partial_core_list(tmp_path: Path):
    write(tmp_path / "devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq", "1728000\n")
    (tmp_path / "devices/system/cpu/cpu1/cpufreq").mkdir(parents=True)

    clocks = JetsonClocks(str(tmp_path)).read()

    assert clocks["cpu_cur_mhz"] == []
    assert clocks["gpu_min_mhz"] is None
    assert clocks["oc_events"] is None
