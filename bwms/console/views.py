"""控制台文本页面。

页面只做一件事：把当前状态摊平成给人看的行，不改任何状态。
"""

from __future__ import annotations


def render_status_lines(line) -> tuple[str, ...]:
    health = line.health()
    tanks = line.bay.snapshot()
    lines = [
        f"{health['plant']} 状态 {health['status']} 拍数 {health['tick']} "
        f"水位 {health['watermark']}",
        f"闩锁 {list(health['latched'])} 待提交 {health['pending']} "
        f"快照一致 {health['consistent']}",
    ]
    for tag, tank in tanks.items():
        lines.append(
            f"{tag} {tank['state']} {tank['volume_m3']}/{tank['capacity_m3']} m3"
        )
    lines.append(
        f"泵 {line.pump.status()['running']} 流量 {line.flow.status()['flow_m3_per_tick']}"
    )
    lines.append(
        f"处理 {line.treat.status()['state']} 许可 {line.permits.status()['issued']} "
        f"排放 {line.releaser.status()['releases']}"
    )
    return tuple(lines)


def render_index(line) -> str:
    rows = "".join(f"<li>{text}</li>" for text in render_status_lines(line))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>line control console</title></head><body>"
        f"<h1>{line.settings.plant_tag}</h1><ul>{rows}</ul>"
        "</body></html>"
    )
