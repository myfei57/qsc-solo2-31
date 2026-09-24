"""控制层统一异常。

每个异常都带稳定的 ``code``，控制台按 code 归类返回，测试断言 code 而不是
比对文案。``InterlockError`` 还要带上未满足的前置项，便于定位是哪一个门控
把动作挡住了。
"""

from __future__ import annotations

from typing import Iterable


class ControlError(Exception):
    """本服务所有可预期错误的基类。"""

    code = "control_error"

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


class ConfigurationError(ControlError):
    code = "configuration_error"


class UnknownDeviceError(ControlError):
    code = "unknown_device"


class UnknownSubjectError(ControlError):
    code = "unknown_subject"


class InterlockError(ControlError):
    """前置门控不满足，动作被拒绝。"""

    code = "interlock_denied"

    def __init__(self, action: str, unmet: Iterable[str]):
        self.action = action
        self.unmet = tuple(unmet)
        super().__init__(f"{action} 前置未满足: {', '.join(self.unmet) or '未登记前置'}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload["action"] = self.action
        payload["unmet"] = list(self.unmet)
        return payload


class LatchError(ControlError):
    """闩锁已置位，动作在解除前一律被挡住。"""

    code = "latch_tripped"

    def __init__(self, action: str, latches: Iterable[str]):
        self.action = action
        self.latches = tuple(latches)
        super().__init__(f"{action} 被闩锁挡住: {', '.join(self.latches)}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload["action"] = self.action
        payload["latches"] = list(self.latches)
        return payload


class SequenceError(ControlError):
    """阶段推进本身不成立，例如顺序已经走完还继续推进。"""

    code = "sequence_error"


class StageOrderError(ControlError):
    """阶段推进顺序错位。"""

    code = "stage_order"

    def __init__(self, device: str, expected: str, got: str):
        self.device = device
        self.expected = expected
        self.got = got
        super().__init__(f"{device} 期望阶段 {expected}，收到 {got}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload.update(
            {"device": self.device, "expected": self.expected, "got": self.got}
        )
        return payload


class StreamError(ControlError):
    code = "stream_error"


class UncommittedRecordError(StreamError):
    """记录尚未提交到水位的写读请求。"""

    code = "record_not_committed"

    def __init__(self, seq: int, watermark: int):
        self.seq = seq
        self.watermark = watermark
        super().__init__(f"记录 {seq} 未提交，当前水位 {watermark}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload.update({"seq": self.seq, "watermark": self.watermark})
        return payload


class UnknownRecordError(StreamError):
    code = "unknown_record"


class VersionError(ControlError):
    code = "version_error"


class StaleGenerationError(VersionError):
    """引用的代际号已经不是当前代际。"""

    code = "stale_generation"

    def __init__(self, key: str, used: int, current: int):
        self.key = key
        self.used = used
        self.current = current
        super().__init__(f"{key} 代际 {used} 已过期，当前代际 {current}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload.update({"key": self.key, "used": self.used, "current": self.current})
        return payload


class ExpiredConfirmationError(VersionError):
    code = "confirmation_expired"

    def __init__(self, sheet_id: str, valid_until: int, tick: int):
        self.sheet_id = sheet_id
        self.valid_until = valid_until
        self.tick = tick
        super().__init__(f"确认单 {sheet_id} 在 {valid_until} 到期，当前 {tick}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload.update(
            {"sheet_id": self.sheet_id, "valid_until": self.valid_until, "tick": self.tick}
        )
        return payload


class ExpiredBaselineError(VersionError):
    code = "baseline_expired"

    def __init__(self, baseline_id: str, expires_at: int, tick: int):
        self.baseline_id = baseline_id
        self.expires_at = expires_at
        self.tick = tick
        super().__init__(f"基线 {baseline_id} 在 {expires_at} 失效，当前 {tick}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload.update(
            {"baseline_id": self.baseline_id, "expires_at": self.expires_at, "tick": self.tick}
        )
        return payload


class DuplicateBatchError(ControlError):
    code = "duplicate_batch"

    def __init__(self, batch_id: str):
        self.batch_id = batch_id
        super().__init__(f"批次 {batch_id} 已存在")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload["batch_id"] = self.batch_id
        return payload


class ThresholdError(ControlError):
    """比较越限：门限或窗口判定不通过。"""

    code = "threshold_exceeded"

    def __init__(self, subject: str, field: str, value: float, limit: float):
        self.subject = subject
        self.field = field
        self.value = value
        self.limit = limit
        super().__init__(f"{subject} 的 {field}={value} 越限 {limit}")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload.update(
            {
                "subject": self.subject,
                "field": self.field,
                "value": self.value,
                "limit": self.limit,
            }
        )
        return payload


class ThresholdNotMetError(ControlError):
    """门限未达到，动作被拒绝。"""

    code = "threshold_not_met"


class QuotaExceededError(ControlError):
    code = "quota_exceeded"

    def __init__(self, epoch: int, used: int, limit: int):
        self.epoch = epoch
        self.used = used
        self.limit = limit
        super().__init__(f"纪元 {epoch} 记录配额 {used}/{limit} 已满")

    def as_dict(self) -> dict:
        payload = super().as_dict()
        payload.update({"epoch": self.epoch, "used": self.used, "limit": self.limit})
        return payload


class CalibrationError(ControlError):
    code = "calibration_stale"


class PermitError(ControlError):
    code = "permit_invalid"
