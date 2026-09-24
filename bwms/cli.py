"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys

from .app import Line, build_line
from .clock import TickClock
from .console import build_server
from .errors import ControlError
from .settings import default_settings, load_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bwms")
    parser.add_argument("--config", default="config/line.json")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动控制台服务")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    sub.add_parser("status", help="打印当前状态")
    sub.add_parser("health", help="打印健康检查结果")
    sub.add_parser("demo", help="跑一遍确定性的端到端流程")
    return parser


def _load(args) -> Line:
    try:
        settings = load_settings(args.config)
    except ControlError:
        settings = default_settings()
    return build_line(settings, TickClock())


def run_demo(line: Line) -> list[str]:
    """按装载链与排放链各走一遍，返回每一步的可读记录。"""

    steps: list[str] = []
    steps.append(f"起始 拍数 {line.clock.tick} 水位 {line.store.watermark()}")
    line.confirm_valve(line.settings.pump.outlet_valve)
    line.confirm_valve(line.settings.dose.inlet_valve)
    line.confirm_valve(line.settings.treat.inlet_valve)
    line.confirm_valve(line.settings.treat.sample_valve)
    for tank in line.settings.tanks:
        line.confirm_valve(tank.inlet_valve)
    steps.append(f"阀位确认 {line.header.open_tags()}")
    line.start_pump("intake")
    steps.append(f"泵已启动 {line.pump.status()['direction']}")
    line.settle_flow()
    steps.append(f"水流建立 流量 {line.flow.read()}")
    line.read_intensity(62.0)
    line.read_intensity(58.0)
    steps.append(f"UV 判定 {line.reactor.window_verdict()['pass']}")
    line.run_treatment(120.0)
    steps.append(f"处理状态 {line.treat.state()}")
    dose_sheet = line.confirm_parameters("dose", "chief-officer", 120)
    dose = line.inject_dose("BATCH-DEMO", 120.0, dose_sheet.sheet_id)
    steps.append(f"投加 {dose.ppm} ppm 药剂 {dose.agent_l} L")
    steps.append(f"投加自检 {line.verify_dose('BATCH-DEMO')}")
    plan = line.plan_load(300.0)
    steps.append(f"装载计划 {[item['tag'] for item in plan['allocations']]}")
    for allocation in plan["allocations"]:
        line.load_tank(allocation["tag"], allocation["volume_m3"])
    steps.append(f"舱容 {line.bay.totals()}")
    tank_tag = plan["allocations"][0]["tag"]
    line.start_purge()
    line.finish_purge()
    batch = line.take_sample(tank_tag)
    steps.append(f"取样批次 {batch['batch_id']}")
    analysis = line.analyze_sample(batch["batch_id"], 3.4, 2.0)
    steps.append(f"分析判定 达标 {analysis['compliant']}")
    compliance_sheet = line.confirm_parameters("compliance", "chief-officer", 120)
    line.neutralize(60.0, compliance_sheet.sheet_id)
    steps.append(f"中和状态 {line.treat.status()['state']}")
    permit = line.issue_permit(batch["batch_id"], compliance_sheet.sheet_id)
    steps.append(f"排放许可 {permit['permit_id']}")
    release = line.discharge(
        batch["batch_id"], tank_tag, 60.0, permit["permit_id"]
    )
    steps.append(f"排放 {release['volume_m3']} m3 窗口 {release['window_id']}")
    epoch = line.roll_epoch("voyage segment closed")
    steps.append(f"处理日志纪元 {epoch['opened_epoch']} 归属 {line.epoch.totals()}")
    steps.append(f"健康检查 {line.health()}")
    return steps


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    line = _load(args)
    if args.command == "serve":
        server = build_server(line, host=args.host, port=args.port)
        print(f"listening on {server.endpoint()}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("stopped")
        finally:
            server.server_close()
        return 0
    if args.command == "status":
        print(json.dumps(line.status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "health":
        print(json.dumps(line.health(), ensure_ascii=False, sort_keys=True))
        return 0
    for step in run_demo(line):
        print(step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
