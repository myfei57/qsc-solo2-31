"""测试夹具：每个用例都从干净的存储目录和可推进的逻辑时钟起步。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bwms.app import Line, build_line  # noqa: E402
from bwms.clock import TickClock  # noqa: E402
from bwms.settings import Settings, default_settings  # noqa: E402


@pytest.fixture()
def clock() -> TickClock:
    return TickClock()


@pytest.fixture()
def state_root(tmp_path) -> str:
    return str(tmp_path / "state")


@pytest.fixture()
def settings(state_root) -> Settings:
    return default_settings(state_root)


@pytest.fixture()
def line(settings, clock) -> Line:
    return build_line(settings, clock)


@pytest.fixture()
def intake_line(line) -> Line:
    """泵已启动且水流已经建立的活动机组。"""

    line.confirm_valve(line.settings.pump.outlet_valve)
    line.confirm_valve(line.settings.dose.inlet_valve)
    line.confirm_valve(line.settings.treat.inlet_valve)
    line.start_pump("intake")
    line.settle_flow()
    return line


@pytest.fixture()
def treated_line(intake_line) -> Line:
    """已经投加药剂并装载完一舱水的机组。"""

    intake_line.read_intensity(62.0)
    intake_line.read_intensity(58.0)
    intake_line.run_treatment(120.0)
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 240)
    intake_line.inject_dose("BATCH-FIXTURE", 120.0, sheet.sheet_id)
    return intake_line


@pytest.fixture()
def chain(line, intake_line):
    """按装载 → 取样 → 判定 → 中和 → 许可的顺序推进，可以指定停在哪一步。"""

    def _run(
        tank_tag: str = "TB-01",
        volume_m3: float = 120.0,
        turbidity_ntu: float = 3.0,
        organisms_per_m3: float = 2.0,
        stop_after: str = "permit",
    ) -> dict:
        line.confirm_valve(line.settings.treat.sample_valve)
        line.confirm_valve(line.settings.tank(tank_tag).inlet_valve)
        line.read_intensity(62.0)
        line.read_intensity(58.0)
        line.run_treatment(volume_m3)
        dose_sheet = line.confirm_parameters("dose", "chief-officer", 240)
        line.inject_dose(f"BATCH-{tank_tag}", volume_m3, dose_sheet.sheet_id)
        line.load_tank(tank_tag, volume_m3)
        line.start_purge()
        line.finish_purge()
        batch = line.take_sample(tank_tag)
        if stop_after == "sample":
            return {"batch": batch, "tank_tag": tank_tag, "volume_m3": volume_m3}
        analysis = line.analyze_sample(batch["batch_id"], turbidity_ntu, organisms_per_m3)
        if stop_after == "analysis":
            return {
                "batch": batch,
                "analysis": analysis,
                "tank_tag": tank_tag,
                "volume_m3": volume_m3,
            }
        sheet = line.confirm_parameters("compliance", "chief-officer", 240)
        line.neutralize(volume_m3, sheet.sheet_id)
        if stop_after == "neutralize":
            return {
                "batch": batch,
                "analysis": analysis,
                "sheet": sheet,
                "tank_tag": tank_tag,
                "volume_m3": volume_m3,
            }
        permit = line.issue_permit(batch["batch_id"], sheet.sheet_id)
        return {
            "batch": batch,
            "analysis": analysis,
            "permit": permit,
            "sheet": sheet,
            "tank_tag": tank_tag,
            "volume_m3": volume_m3,
        }

    return _run
