"""整线装配与跨组件动作。

``Line`` 是唯一把各子系统串起来的地方：每个动作先过阶段顺序、闩锁与联锁三关，
再调用真正拥有状态的那个组件，最后把这次动作落进记录流。组件之间不互相调用，
跨组件的依赖只在联锁矩阵里出现。
"""

from __future__ import annotations

import math

from .audit import AuditTrail, ComplianceReport
from .clock import TickClock
from .compliance import DischargeController, PermitBook, WindowBook
from .dose import DoseInjector, DoseSchedule
from .errors import InterlockError, ThresholdError
from .events import EventBus
from .interlocks import Gate, InterlockMatrix
from .level import CalibrationBook, LevelGauge
from .ns import DeviceRegistry, PipeHeader, Topology
from .pump import BallastPump, DirectionController, FlowMeter
from .pump.machine import DISCHARGE, INTAKE
from .quota import QuotaLedger, QuotaPolicy
from .sensor import BatchBook, IntensitySensor, PurgeController, SampleAnalyzer
from .seq import LatchBank, SequenceDefinition, SequenceEngine, StageDefinition
from .settings import Settings, default_settings
from .store import (
    BaselineRegistry,
    ConfirmationBook,
    GenerationRegister,
    RecordFilter,
    RecordStream,
)
from .store.records import (
    KIND_ACTION,
    KIND_ANALYSIS,
    KIND_CALIBRATION,
    KIND_DISCHARGE,
    KIND_MEASUREMENT,
    KIND_PERMIT,
    KIND_SAMPLE,
)
from .tank import CapacityBook, LoadPlanner, TankInventory
from .tank.inventory import EMPTY, FILLING
from .treat import (
    BypassValve,
    Neutralizer,
    SamplingLine,
    TreatmentLogEpoch,
    UvReactor,
)

PERMIT_DEVICE = "PM-01"


class Line:
    def __init__(self, settings: Settings, clock: TickClock) -> None:
        self.settings = settings
        self.clock = clock
        self.bus = EventBus()
        self.registry = DeviceRegistry()
        self.topology = Topology(self.registry)
        self.header = PipeHeader(self.registry)
        self.store = RecordStream(settings.store, clock, self.bus)
        self.audit = AuditTrail(self.bus, clock).attach()
        self.epoch = TreatmentLogEpoch(clock, self.bus, self.store)
        self.generations = GenerationRegister(self.store, self.epoch.current)
        self.confirmations = ConfirmationBook(self.store, self.generations, clock)
        self.baselines = BaselineRegistry(self.store, self.generations, clock)

        self._register_devices()
        self._build_header()

        self.capacities = CapacityBook(settings, clock)
        self.bay = TankInventory(self.capacities, clock, self.bus, settings.tank_tags())
        self.planner = LoadPlanner(self.bay, self.capacities, clock, self.bus)

        self.pump = BallastPump(settings.pump, clock, self.bus, self.header)
        self.flow = FlowMeter(settings.pump, clock, self.bus)
        self.direction = DirectionController(settings.pump, clock, self.bus, self.pump)

        self.latches = LatchBank()
        self.interlocks = InterlockMatrix()
        self.engine = SequenceEngine(self.interlocks, self.latches, clock, self.bus)
        self._declare_latches()
        self._define_sequences()

        self.dose_schedule = DoseSchedule(settings.dose, clock)
        self.dose = DoseInjector(
            settings.dose, clock, self.bus, self.flow, self.dose_schedule
        )
        self.bypass = BypassValve(settings.treat, clock, self.bus)
        self.reactor = UvReactor(settings.treat, clock, self.bus, self.latches)
        self.treat = Neutralizer(settings.treat, clock, self.bus)
        self.line = SamplingLine(settings.treat, clock, self.bus)
        self.purge = PurgeController(settings.sensor, clock, self.bus, self.line)
        self.intensity = IntensitySensor(settings.sensor, clock, self.bus, self.reactor)
        self.analyzer = SampleAnalyzer(settings.sensor, clock, self.bus)
        self.batches = BatchBook(settings.sensor, clock, self.bus)
        self.permits = PermitBook(settings.compliance, clock, self.bus)
        self.windows = WindowBook(settings.compliance, clock, self.bus)
        self.releaser = DischargeController(
            settings.compliance, clock, self.bus, self.bay, self.permits, self.windows
        )
        self.calibrations = CalibrationBook(settings.level, clock, self.bus)
        self.gauge = LevelGauge(settings.level, clock, self.bus, self.calibrations)
        self.quota = QuotaLedger(
            QuotaPolicy(settings.quota.max_records_per_epoch, settings.quota.warn_ratio),
            self.store,
            clock,
            self.bus,
            self.epoch.current,
        )
        self.report = ComplianceReport(
            self.store, self.permits, self.windows, self.analyzer, self.quota, self.epoch
        )

        self._register_gates()
        self.publish_parameters(
            "dose",
            {
                "target_ppm": settings.dose.target_ppm,
                "max_ppm": settings.dose.max_ppm,
                "min_flow_m3_per_tick": settings.dose.min_flow_m3_per_tick,
            },
        )
        self.publish_parameters(
            "compliance",
            {
                "permit_valid_ticks": settings.compliance.permit_valid_ticks,
                "discharge_window_ticks": settings.compliance.discharge_window_ticks,
            },
        )

    # ------------------------------------------------------------------ 装配

    def _register_devices(self) -> None:
        spec = self.settings
        self.registry.register(spec.pump.tag, "pump", "engine-room")
        self.registry.register(spec.dose.tag, "dosing", "engine-room")
        self.registry.register(spec.treat.tag, "treatment", "engine-room")
        self.registry.register(spec.sensor.tag, "analyzer", "sampling")
        self.registry.register(spec.level.tag, "level", "tanks")
        self.registry.register(PERMIT_DEVICE, "permit", "control")
        for tank in spec.tanks:
            self.registry.register(tank.tag, "tank", "tanks")
        self.topology.connect(spec.pump.tag, spec.dose.tag, "sea water")
        self.topology.connect(spec.dose.tag, spec.treat.tag, "dosed water")
        for tank in spec.tanks:
            self.topology.connect(spec.treat.tag, tank.tag, "treated water")
        self.topology.connect(spec.treat.tag, spec.sensor.tag, "sample")

    def _build_header(self) -> None:
        spec = self.settings
        self.header.add(spec.pump.outlet_valve, "sea water")
        self.header.add(spec.dose.inlet_valve, "agent")
        self.header.add(spec.treat.inlet_valve, "dosed water")
        self.header.add(spec.treat.sample_valve, "sample")
        for tank in spec.tanks:
            self.header.add(tank.inlet_valve, "treated water")

    def _declare_latches(self) -> None:
        self.latches.declare("uv_low", self.settings.treat.tag)
        self.latches.declare("flow_lost", self.settings.pump.tag)
        self.latches.declare("level_offset", self.settings.level.tag)
        self.latches.declare("sampling_dirty", self.settings.sensor.tag)

    def _define_sequences(self) -> None:
        self.engine.define(
            SequenceDefinition(
                device=self.settings.pump.tag,
                stages=(
                    StageDefinition("pump.arm", 0),
                    StageDefinition("pump.flow", 1),
                    StageDefinition("pump.ready", 2),
                ),
            )
        )
        self.engine.define(
            SequenceDefinition(
                device=self.settings.dose.tag,
                stages=(
                    StageDefinition("dose.arm", 0),
                    StageDefinition("dose.inject", 1, ("flow_lost",)),
                    StageDefinition("dose.verify", 2),
                ),
            )
        )
        self.engine.define(
            SequenceDefinition(
                device=self.settings.treat.tag,
                stages=(
                    StageDefinition("treat.prepare", 0),
                    StageDefinition("treat.uv", 1, ("uv_low",)),
                    StageDefinition("treat.neutralize", 2, ("uv_low",)),
                    StageDefinition("treat.ready", 3),
                ),
            )
        )
        self.engine.define(
            SequenceDefinition(
                device=self.settings.sensor.tag,
                stages=(
                    StageDefinition("sensor.purge", 0),
                    StageDefinition("sensor.sample", 1, ("sampling_dirty",)),
                    StageDefinition("sensor.analyze", 2),
                    StageDefinition("sensor.verdict", 3),
                ),
            )
        )
        self.engine.define(
            SequenceDefinition(
                device=PERMIT_DEVICE,
                stages=(
                    StageDefinition("compliance.permit", 0),
                    StageDefinition("compliance.window", 1),
                    StageDefinition("compliance.discharge", 2),
                ),
            )
        )
        for tank in self.settings.tanks:
            self.engine.define(
                SequenceDefinition(
                    device=tank.tag,
                    stages=(
                        StageDefinition(f"{tank.tag}.seat", 0),
                        StageDefinition(f"{tank.tag}.load", 1, ("level_offset",)),
                        StageDefinition(f"{tank.tag}.settle", 2),
                    ),
                )
            )

    def _register_gates(self) -> None:
        spec = self.settings
        matrix = self.interlocks
        matrix.register(
            "pump.arm", Gate("outlet_open", spec.pump.tag, self.pump.outlet_open)
        )
        matrix.register("pump.flow", Gate("flow_settled", spec.pump.tag, self.flow.ready))
        matrix.register(
            "pump.ready",
            Gate("flow_within_rating", spec.pump.tag, self.flow.within_rating),
        )
        matrix.register(
            "dose.arm",
            Gate(
                "dose_valve_open",
                spec.dose.tag,
                lambda: self.header.is_open(spec.dose.inlet_valve),
            ),
        )
        matrix.register(
            "dose.inject", Gate("flow_established", spec.pump.tag, self.dose.flow_ok)
        )
        matrix.register(
            "dose.verify",
            Gate("dose_window_elapsed", spec.dose.tag, self.dose.verify_ready),
        )
        matrix.register(
            "treat.prepare",
            Gate(
                "inlet_open",
                spec.treat.tag,
                lambda: self.header.is_open(spec.treat.inlet_valve),
            ),
        )
        matrix.register(
            "treat.uv", Gate("uv_intensity_ok", spec.treat.tag, self.reactor.intensity_ok)
        )
        matrix.register(
            "treat.neutralize",
            Gate(
                "uv_treated",
                spec.treat.tag,
                lambda: self.engine.reached(spec.treat.tag, "treat.uv"),
            ),
        )
        matrix.register(
            "treat.ready",
            Gate("neutralizer_hold_done", spec.treat.tag, self.treat.ready),
        )
        matrix.register(
            "sensor.purge",
            Gate(
                "sample_valve_open",
                spec.sensor.tag,
                lambda: self.header.is_open(spec.treat.sample_valve),
            ),
        )
        matrix.register(
            "sensor.sample", Gate("line_purged", spec.sensor.tag, self.purge.clean)
        )
        matrix.register(
            "sensor.analyze",
            Gate(
                "sample_drawn",
                spec.sensor.tag,
                lambda: self.store.count(KIND_SAMPLE) > 0,
            ),
        )
        matrix.register(
            "sensor.verdict",
            Gate(
                "analysis_done",
                spec.sensor.tag,
                lambda: len(self.analyzer.results()) > 0,
            ),
        )
        matrix.register(
            "compliance.permit",
            Gate(
                "analysis_verdict_ready",
                spec.sensor.tag,
                lambda: self.engine.reached(spec.sensor.tag, "sensor.verdict"),
            ),
        )
        matrix.register(
            "compliance.window",
            Gate(
                "permit_issued",
                "permit",
                lambda: self.permits.status()["issued"] > 0,
            ),
        )
        matrix.register(
            "compliance.discharge",
            Gate("neutralized_ready", spec.treat.tag, self.treat.ready),
        )
        matrix.register(
            "compliance.discharge",
            Gate(
                "bypass_clear",
                spec.treat.tag,
                lambda: not self.bypass.engaged(),
            ),
        )
        matrix.register(
            "compliance.discharge",
            Gate(
                "window_open",
                "window",
                lambda: self.windows.assign(self.clock.tick) is not None,
            ),
        )
        for tank in spec.tanks:
            matrix.register(
                f"{tank.tag}.seat",
                Gate(
                    f"{tank.tag}.inlet_seated",
                    tank.tag,
                    lambda tag=tank.tag: self.header.is_seated(
                        self.settings.tank(tag).inlet_valve
                    ),
                ),
            )
            matrix.register(
                f"{tank.tag}.load",
                Gate(
                    f"{tank.tag}.room_available",
                    tank.tag,
                    lambda tag=tank.tag: self.bay.remaining(tag) > 0
                    and self.bay.state(tag) in (EMPTY, FILLING),
                ),
            )
            matrix.register(
                f"{tank.tag}.load",
                Gate(f"{tank.tag}.flow_ready", spec.pump.tag, self.flow.ready),
            )

    # ------------------------------------------------------------------ 通用

    def tick(self, steps: int = 1) -> int:
        return self.clock.advance(steps)

    def records(self, criteria: RecordFilter | None = None) -> tuple:
        return self.store.visible(criteria)

    def rollback(self, seq: int, reason: str):
        return self.store.tombstone(seq, reason, epoch=self.epoch.current())

    def health(self) -> dict:
        return {
            "status": "ok",
            "plant": self.settings.plant_tag,
            "tick": self.clock.tick,
            "watermark": self.store.watermark(),
            "latched": list(self.latches.active()),
            "pending": len(self.store.pending()),
            "buffered": self.store.buffered(),
            "consistent": self.store.verify()["consistent"],
        }

    def load_paths(self) -> dict:
        return {
            tank.tag: self.topology.route(self.settings.pump.tag, tank.tag)
            for tank in self.settings.tanks
        }

    def status(self) -> dict:
        return {
            "plant": self.settings.plant_tag,
            "tick": self.clock.tick,
            "watermark": self.store.watermark(),
            "digest": self.store.digest(),
            "registry": self.registry.summary(),
            "paths": self.load_paths(),
            "valves": [device.tag for device in self.registry.by_kind("valve")],
            "open_valves": list(self.header.open_tags()),
            "pipes": self.header.snapshot(),
            "tanks": self.bay.snapshot(),
            "totals": self.bay.totals(),
            "load_snapshot": self.planner.last_snapshot(),
            "pump": self.pump.status(),
            "flow": self.flow.status(),
            "direction": self.direction.status(),
            "dose": self.dose.status(),
            "treatment": self.treat.status(),
            "uv": self.reactor.status(),
            "bypass": self.bypass.status(),
            "level": self.gauge.status(),
            "sampling_line": self.line.status(),
            "purge": self.purge.status(),
            "analyzer": self.analyzer.status(),
            "permits": self.permits.status(),
            "windows": self.windows.status(),
            "discharge": self.releaser.status(),
            "quota": self.quota.status(),
            "epoch": self.epoch.status(),
            "latches": self.latches.snapshot(),
            "interlocks": self.interlocks.snapshot(),
            "sequences": self.engine.snapshot(),
            "audit": self.audit.status(),
            "parameters": self.generations.snapshot(),
            "confirmations": self.confirmations.snapshot(),
            "baselines": self.baselines.snapshot(),
        }

    # ------------------------------------------------------------ 版本与参数

    def publish_parameters(self, key: str, values: dict):
        return self.generations.publish(key, values)

    def confirm_parameters(self, key: str, operator: str, validity_ticks: int, note: str = ""):
        return self.confirmations.confirm(key, operator, validity_ticks, note=note)

    def capture_baseline(self, key: str, label: str, valid_ticks: int):
        return self.baselines.capture(key, self.store.digest(), valid_ticks, label=label)

    def resolve_baseline(self, baseline_id: str):
        return self.baselines.resolve(baseline_id)

    # ---------------------------------------------------------------- 装载链

    def confirm_valve(self, tag: str) -> dict:
        """操作员确认阀芯落位；确认之前相关动作一律不满足前置。"""

        segment = self.header.confirm_seated(tag, self.clock.tick)
        self.store.write(
            KIND_ACTION,
            tag,
            {"action": "seat_confirm", "medium": segment.medium},
            epoch=self.epoch.current(),
        )
        return segment.to_dict()

    def start_pump(self, direction: str = INTAKE) -> dict:
        spec = self.settings
        self.engine.arm(spec.pump.tag)
        arm = self.engine.step(spec.pump.tag, "pump.arm")
        started = self.pump.start(direction)
        established = self.flow.establish()
        self.store.write(
            KIND_ACTION,
            spec.pump.tag,
            {"action": "start", "direction": direction, "arm": arm["stage"]},
            epoch=self.epoch.current(),
        )
        return {"started": started, "established": established}

    def settle_flow(self) -> dict:
        spec = self.settings
        pump_tag = spec.pump.tag
        if self.engine.next_stage(pump_tag) == "pump.arm":
            self.engine.step(pump_tag, "pump.arm")
        if not self.flow.established():
            self.flow.establish()
        self.tick(self.flow.settle_remaining())
        self.latches.clear("flow_lost", self.clock.tick)
        flow_step = self.engine.step(pump_tag, "pump.flow")
        ready_step = self.engine.step(pump_tag, "pump.ready")
        self.store.write(
            KIND_MEASUREMENT,
            spec.pump.tag,
            {"action": "flow_ready", "flow": self.flow.read()},
            epoch=self.epoch.current(),
        )
        return {"flow": flow_step, "ready": ready_step, "reading": self.flow.status()}

    def drop_flow(self, reason: str) -> dict:
        spec = self.settings
        dropped = self.flow.drop(reason)
        self.engine.arm(spec.pump.tag)
        self.latches.trip("flow_lost", reason, self.clock.tick)
        self.store.write(
            KIND_ACTION,
            spec.pump.tag,
            {"action": "flow_drop", "reason": reason},
            epoch=self.epoch.current(),
        )
        return dropped

    def read_intensity(self, value: float) -> dict:
        return self.intensity.sample(value)

    def run_treatment(self, volume_m3: float) -> dict:
        spec = self.settings
        self.engine.arm(spec.treat.tag)
        self.engine.step(spec.treat.tag, "treat.prepare")
        self.engine.step(spec.treat.tag, "treat.uv")
        treated = self.treat.start_treatment(volume_m3)
        self.store.write(
            KIND_MEASUREMENT,
            spec.treat.tag,
            {"action": "treat", "volume_m3": float(volume_m3)},
            epoch=self.epoch.current(),
        )
        return {"treated": treated, "uv": self.reactor.window_verdict()}

    def inject_dose(self, batch_key: str, volume_m3: float, sheet_id: str) -> dict:
        spec = self.settings
        sheet = self.confirmations.require(sheet_id)
        parameters = self.generations.require_current("dose", sheet.generation)
        self.confirmations.verify(sheet_id, "dose", sheet.generation)
        self.engine.arm(spec.dose.tag)
        self.engine.step(spec.dose.tag, "dose.arm")
        self.engine.step(spec.dose.tag, "dose.inject")
        ppm = float(parameters.value("target_ppm", spec.dose.target_ppm))
        self.quota.require_room()
        result = self.dose.inject(batch_key, volume_m3, ppm, sheet.generation, sheet_id)
        self.store.write(
            KIND_MEASUREMENT,
            spec.dose.tag,
            {"action": "dose", **result.to_dict()},
            generation=sheet.generation,
            epoch=self.epoch.current(),
        )
        self.tick(result.ticks)
        remaining = self.dose.verify_window_remaining()
        if remaining:
            self.tick(remaining)
        self.engine.step(spec.dose.tag, "dose.verify")
        self.store.write(
            KIND_MEASUREMENT,
            spec.dose.tag,
            {"action": "dose_verify", **self.dose.verify(batch_key)},
            generation=sheet.generation,
            epoch=self.epoch.current(),
        )
        return result

    def verify_dose(self, batch_key: str) -> dict:
        return self.dose.verify(batch_key)

    def plan_load(self, volume_m3: float) -> dict:
        report = self.planner.plan(volume_m3)
        report["line_capacity_m3"] = self.settings.total_capacity_m3()
        return report

    def resize_tank(self, tag: str, capacity_m3: float, note: str = "") -> dict:
        revision = self.capacities.set_capacity(tag, capacity_m3, note=note)
        self.bay.apply_capacity_change(tag)
        self.store.write(
            KIND_ACTION,
            tag,
            {"action": "resize", **revision.to_dict()},
            epoch=self.epoch.current(),
        )
        return revision.to_dict()

    def load_tank(self, tag: str, volume_m3: float) -> dict:
        self.settings.tank(tag)
        self.engine.arm(tag)
        self.engine.step(tag, f"{tag}.seat")
        self.engine.step(tag, f"{tag}.load")
        if self.flow.read() <= 0:
            raise ThresholdError(tag, "flow_m3_per_tick", self.flow.read(), 0.0)
        self.quota.require_room()
        loaded = self.bay.load(tag, volume_m3)
        self.store.write(
            KIND_MEASUREMENT,
            tag,
            {"action": "load", "volume_m3": float(volume_m3)},
            epoch=self.epoch.current(),
        )
        self.tick(max(1, math.ceil(float(volume_m3) / max(self.flow.read(), 1e-9))))
        self.engine.step(tag, f"{tag}.settle")
        return loaded

    # ---------------------------------------------------------------- 排放链

    def read_level(self, raw_units: float) -> dict:
        reading = self.gauge.read(raw_units)
        if not self.calibrations.within_limit():
            self.latches.trip(
                "level_offset",
                f"零点偏移 {self.calibrations.offset_m3()} 超过限值",
                self.clock.tick,
            )
        self.store.write(
            KIND_MEASUREMENT,
            self.settings.level.tag,
            reading.to_dict(),
            epoch=self.epoch.current(),
        )
        return reading.to_dict()

    def recalibrate_level(self, offset_m3: float, note: str = "") -> dict:
        record = self.calibrations.recalibrate(offset_m3, note=note)
        if self.calibrations.within_limit():
            self.latches.clear("level_offset", self.clock.tick)
        self.store.write(
            KIND_CALIBRATION,
            self.settings.level.tag,
            record.to_dict(),
            epoch=self.epoch.current(),
        )
        return record.to_dict()

    def start_purge(self) -> dict:
        self.engine.arm(self.settings.sensor.tag)
        self.engine.step(self.settings.sensor.tag, "sensor.purge")
        started = self.purge.start()
        self.store.write(
            KIND_ACTION,
            self.settings.sensor.tag,
            {"action": "purge_start"},
            epoch=self.epoch.current(),
        )
        return started

    def finish_purge(self) -> dict:
        self.tick(self.settings.sensor.flush_ticks)
        self.purge.advance()
        self.tick(self.settings.sensor.dwell_ticks)
        self.purge.advance()
        if self.purge.clean():
            self.latches.clear("sampling_dirty", self.clock.tick)
        self.store.write(
            KIND_ACTION,
            self.settings.sensor.tag,
            {"action": "purge_done", "steps": list(self.purge.steps_done())},
            epoch=self.epoch.current(),
        )
        return self.purge.status()

    def take_sample(self, tank_tag: str) -> dict:
        self.engine.step(self.settings.sensor.tag, "sensor.sample")
        self.quota.require_room()
        batch = self.batches.open(tank_tag)
        self.store.write(
            KIND_SAMPLE,
            batch.batch_id,
            batch.to_dict(),
            epoch=self.epoch.current(),
        )
        return batch.to_dict()

    def analyze_sample(
        self, batch_id: str, turbidity_ntu: float, organisms_per_m3: float
    ) -> dict:
        self.batches.require(batch_id)
        self.engine.step(self.settings.sensor.tag, "sensor.analyze")
        self.quota.require_room()
        result = self.analyzer.analyze(batch_id, turbidity_ntu, organisms_per_m3)
        self.store.write(
            KIND_ANALYSIS,
            batch_id,
            result.to_dict(),
            epoch=self.epoch.current(),
        )
        self.engine.step(self.settings.sensor.tag, "sensor.verdict")
        if not result.compliant:
            self.latches.trip(
                "sampling_dirty", "; ".join(result.reasons), self.clock.tick
            )
        return result.to_dict()

    def neutralize(self, volume_m3: float, sheet_id: str) -> dict:
        spec = self.settings
        sheet = self.confirmations.require(sheet_id)
        parameters = self.generations.require_current("compliance", sheet.generation)
        self.confirmations.verify(sheet_id, "compliance", sheet.generation)
        self.engine.step(spec.treat.tag, "treat.neutralize")
        ppm = float(parameters.value("neutralizer_ppm", spec.treat.neutralizer_ppm))
        self.quota.require_room()
        record = self.treat.neutralize(volume_m3, ppm)
        self.store.write(
            KIND_MEASUREMENT,
            spec.treat.tag,
            {"action": "neutralize", **record},
            generation=sheet.generation,
            epoch=self.epoch.current(),
        )
        self.tick(spec.treat.neutralizer_hold_ticks)
        self.engine.step(spec.treat.tag, "treat.ready")
        return record

    def issue_permit(self, batch_id: str, sheet_id: str) -> dict:
        self.engine.arm(PERMIT_DEVICE)
        self.engine.step(PERMIT_DEVICE, "compliance.permit")
        sheet = self.confirmations.require(sheet_id)
        parameters = self.generations.require_current("compliance", sheet.generation)
        self.confirmations.verify(sheet_id, "compliance", sheet.generation)
        self.quota.require_room()
        permit = self.permits.issue(
            batch_id,
            self.analyzer.compliant(batch_id),
            sheet.generation,
            sheet.sheet_id,
            valid_ticks=int(
                parameters.value(
                    "permit_valid_ticks", self.settings.compliance.permit_valid_ticks
                )
            ),
        )
        self.store.write(
            KIND_PERMIT,
            permit.permit_id,
            permit.to_dict(),
            generation=sheet.generation,
            epoch=self.epoch.current(),
        )
        return permit.to_dict()

    def discharge(self, batch_id: str, tank_tag: str, volume_m3: float, permit_id: str) -> dict:
        self.engine.step(PERMIT_DEVICE, "compliance.window")
        self.quota.require_room()
        window = self.windows.open(batch_id)
        self.store.write(
            KIND_ACTION,
            "window",
            {"action": "open", **window.to_dict()},
            epoch=self.epoch.current(),
        )
        self.engine.step(PERMIT_DEVICE, "compliance.discharge")
        release = self.releaser.release(
            batch_id, tank_tag, volume_m3, permit_id, self.treat.ready()
        )
        self.store.write(
            KIND_DISCHARGE,
            tank_tag,
            release,
            epoch=self.epoch.current(),
        )
        self.windows.close(window.window_id)
        return release

    def reverse_pump(self, direction: str = DISCHARGE) -> dict:
        command = self.direction.command(direction)
        engaged = self.bypass.engage(f"pump reversal to {direction}")
        self.tick(self.settings.pump.reverse_settle_ticks)
        self.header.close(self.settings.treat.inlet_valve)
        self.store.write(
            KIND_ACTION,
            self.settings.pump.tag,
            {"action": "reverse", "direction": direction, "bypass": engaged},
            epoch=self.epoch.current(),
        )
        return {
            "command": command,
            "bypass": engaged,
            "settled": self.direction.settled(),
            "bypass_settled": self.bypass.settled(),
        }

    def resume_intake(self) -> dict:
        self.bypass.release()
        self.confirm_valve(self.settings.treat.inlet_valve)
        self.direction.command(INTAKE)
        self.tick(self.settings.pump.reverse_settle_ticks)
        self.flow.establish()
        self.tick(self.settings.pump.settle_ticks)
        self.store.write(
            KIND_ACTION,
            self.settings.pump.tag,
            {"action": "resume", "settled": self.direction.settled()},
            epoch=self.epoch.current(),
        )
        return {"direction": self.direction.status(), "bypass": self.bypass.status()}

    def roll_epoch(self, reason: str) -> dict:
        return self.epoch.roll(reason)

    def mark_sampling_dirty(self, reason: str) -> dict:
        self.latches.trip("sampling_dirty", reason, self.clock.tick)
        self.store.write(
            KIND_ACTION,
            self.settings.sensor.tag,
            {"action": "dirty", "reason": reason},
            epoch=self.epoch.current(),
        )
        return self.latches.detail("sampling_dirty")

    def deny(self, action: str) -> dict:
        """把一次被拒的动作写进审计，供控制台回看。"""

        try:
            self.interlocks.require(action)
        except InterlockError as error:
            payload = error.as_dict()
        else:
            payload = {"code": "ok", "message": f"{action} 前置满足"}
        self.bus.publish("interlock", {**payload, "action": "deny", "target": action})
        return payload


def build_line(settings: Settings | None = None, clock: TickClock | None = None) -> Line:
    return Line(settings or default_settings(), clock or TickClock())
