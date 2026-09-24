"""运行期配置。

配置按组件分节，每一节对应一个子系统的物理参数；所有数值都在这里集中，
生产代码里不再散落魔法数字。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


@dataclass(frozen=True)
class TankSpec:
    tag: str
    capacity_m3: float
    inlet_valve: str


@dataclass(frozen=True)
class PumpSpec:
    tag: str
    rated_flow_m3_per_tick: float
    settle_ticks: int
    reverse_settle_ticks: int
    outlet_valve: str


@dataclass(frozen=True)
class DoseSpec:
    tag: str
    target_ppm: float
    max_ppm: float
    min_flow_m3_per_tick: float
    verify_ticks: int
    inlet_valve: str


@dataclass(frozen=True)
class TreatSpec:
    tag: str
    uv_min_intensity: float
    uv_window_ticks: int
    uv_clear_ticks: int
    neutralizer_ppm: float
    neutralizer_hold_ticks: int
    bypass_settle_ticks: int
    inlet_valve: str
    sample_valve: str


@dataclass(frozen=True)
class LevelSpec:
    tag: str
    gain_m3_per_unit: float
    offset_limit_m3: float
    calibration_max_age_ticks: int
    sensor_tag: str


@dataclass(frozen=True)
class SensorSpec:
    tag: str
    flush_ticks: int
    dwell_ticks: int
    turbidity_limit_ntu: float
    organism_limit_per_m3: float
    batch_prefix: str


@dataclass(frozen=True)
class ComplianceSpec:
    permit_valid_ticks: int
    discharge_window_ticks: int
    max_open_windows: int


@dataclass(frozen=True)
class QuotaSpec:
    max_records_per_epoch: int
    warn_ratio: float


@dataclass(frozen=True)
class StoreSpec:
    root: str
    journal_name: str = "records.jsonl"
    watermark_name: str = "watermark.json"
    snapshot_name: str = "projection.json"


@dataclass(frozen=True)
class ConsoleSpec:
    host: str = "127.0.0.1"
    port: int = 8080
    page_size: int = 40


@dataclass(frozen=True)
class Settings:
    plant_tag: str
    tanks: tuple[TankSpec, ...]
    pump: PumpSpec
    dose: DoseSpec
    treat: TreatSpec
    level: LevelSpec
    sensor: SensorSpec
    compliance: ComplianceSpec
    quota: QuotaSpec
    store: StoreSpec
    console: ConsoleSpec = field(default_factory=ConsoleSpec)

    def tank(self, tag: str) -> TankSpec:
        for spec in self.tanks:
            if spec.tag == tag:
                return spec
        raise ConfigurationError(f"未知舱: {tag}")

    def tank_tags(self) -> tuple[str, ...]:
        return tuple(spec.tag for spec in self.tanks)

    def total_capacity_m3(self) -> float:
        return round(sum(spec.capacity_m3 for spec in self.tanks), 6)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_settings(root: str = "var/state") -> Settings:
    return Settings(
        plant_tag="BW-LINE-1",
        tanks=(
            TankSpec("TB-01", 420.0, "V-TB01-IN"),
            TankSpec("TB-02", 360.0, "V-TB02-IN"),
            TankSpec("TB-03", 300.0, "V-TB03-IN"),
        ),
        pump=PumpSpec("BP-01", 60.0, 2, 3, "V-BP01-OUT"),
        dose=DoseSpec("DU-01", 6.5, 12.0, 20.0, 2, "V-DU01-IN"),
        treat=TreatSpec("TU-01", 55.0, 4, 3, 3.0, 2, 1, "V-TU01-IN", "V-TU01-SMP"),
        level=LevelSpec("LG-01", 4.2, 12.0, 240, "LT-01"),
        sensor=SensorSpec("AN-01", 2, 1, 8.0, 10.0, "BATCH"),
        compliance=ComplianceSpec(6, 8, 2),
        quota=QuotaSpec(400, 0.85),
        store=StoreSpec(root),
        console=ConsoleSpec(),
    )


def _tank_specs(raw: list[dict[str, Any]]) -> tuple[TankSpec, ...]:
    specs = [
        TankSpec(
            tag=str(item["tag"]),
            capacity_m3=float(item["capacity_m3"]),
            inlet_valve=str(item["inlet_valve"]),
        )
        for item in raw
    ]
    if not specs:
        raise ConfigurationError("至少需要一个舱段配置")
    return tuple(specs)


def settings_from_dict(raw: dict[str, Any], base_root: str = "var/state") -> Settings:
    try:
        store_raw = dict(raw.get("store", {}))
        store = StoreSpec(
            root=str(store_raw.get("root", base_root)),
            journal_name=str(store_raw.get("journal_name", "records.jsonl")),
            watermark_name=str(store_raw.get("watermark_name", "watermark.json")),
            snapshot_name=str(store_raw.get("snapshot_name", "projection.json")),
        )
        console_raw = dict(raw.get("console", {}))
        return Settings(
            plant_tag=str(raw.get("plant_tag", "BW-LINE-1")),
            tanks=_tank_specs(list(raw["tanks"])),
            pump=PumpSpec(**raw["pump"]),
            dose=DoseSpec(**raw["dose"]),
            treat=TreatSpec(**raw["treat"]),
            level=LevelSpec(**raw["level"]),
            sensor=SensorSpec(**raw["sensor"]),
            compliance=ComplianceSpec(**raw["compliance"]),
            quota=QuotaSpec(**raw["quota"]),
            store=store,
            console=ConsoleSpec(
                host=str(console_raw.get("host", "127.0.0.1")),
                port=int(console_raw.get("port", 8080)),
                page_size=int(console_raw.get("page_size", 40)),
            ),
        )
    except KeyError as missing:
        raise ConfigurationError(f"配置缺少字段: {missing}") from missing
    except TypeError as bad:
        raise ConfigurationError(f"配置字段不匹配: {bad}") from bad


def load_settings(path: str | Path) -> Settings:
    target = Path(path)
    if not target.is_file():
        raise ConfigurationError(f"配置文件不存在: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    return settings_from_dict(payload, base_root=str(target.parent.parent / "state"))
