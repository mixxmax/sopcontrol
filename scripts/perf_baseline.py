"""WP-G 性能基线实测（手册 §11）：只测真实路径，不用“纯函数很快”代替。

方法：time.perf_counter()，warm-up 与有效样本分离；在进程内基准取
warm-up 20 + 有效样本 100；进程级基准（冷/热启动、宿主开销）取小样本并如实标注。
LLM 调用：本仓库快路径全本地，基准中无任何模型调用（计数恒 0）。
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENV_PY = REPO / ".venv" / "bin" / "python"
SOPCTL = REPO / ".venv" / "bin" / "sopctl"

WARMUP = 20
SAMPLES = 100


def stats(name: str, samples: list[float], **extra) -> dict:
    s = sorted(samples)
    n = len(s)
    p50 = s[n // 2]
    p95 = s[min(n - 1, int(n * 0.95))]
    return {"name": name, "n": n, "min_ms": s[0] * 1000, "p50_ms": p50 * 1000,
            "p95_ms": p95 * 1000, "max_ms": s[-1] * 1000, **extra}


def bench_mem_select() -> dict:
    from sopcontrol.dynamic_sop import select_rules
    from sopcontrol.model import ActivationSelector, Modality, Rule, RuleStatus, SourceRef
    rules = [Rule(rule_id=f"DR-{i:03d}", statement=f"规则{i}先台账后评分",
                  modality=Modality.MUST, status=RuleStatus.compiled,
                  rule_class="dynamic_sop",
                  source=SourceRef(type="user_conversation", ref="s"),
                  activation=ActivationSelector(actions=["act.a"], phases=["audit"]))
             for i in range(50)]
    ctx = {"action": "act.a", "phase": "audit", "product": "p"}
    for _ in range(WARMUP):
        select_rules(rules, ctx)
    t = []
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        select_rules(rules, ctx)
        t.append(time.perf_counter() - t0)
    return stats("mem_select_admission_50rules", t, llm_calls=0, tickets=0)


def bench_local_registry_action() -> dict:
    from sopcontrol.dynamic_sop import select_rules
    from sopcontrol.registry import Registry
    reg_path = REPO / ".sopcontrol" / "rules" / "registry.yaml"
    ctx = {"action": "act.a", "phase": "audit", "product": "p"}
    for _ in range(WARMUP):
        rules = Registry(reg_path).load()
        select_rules(rules, ctx)
    t = []
    files = 0
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        rules = Registry(reg_path).load()
        files += 1  # registry 文件读
        select_rules(rules, ctx)
        t.append(time.perf_counter() - t0)
    return stats("local_registry_load_select", t, llm_calls=0, tickets=0,
                 file_reads=files)


def bench_phase_grant() -> dict:
    """同一 phase 连续 3 动作只签发 1 次 grant（§11.4），后续为 admission 检查。"""
    from sopcontrol.tickets import (
        issue_phase_grant, phase_grant_fingerprint, verify_ticket_for_admission,
    )
    fp = phase_grant_fingerprint(phase="audit", allowed_side_effects=["read"],
                                 task_id="T", operation="op")
    t = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for _ in range(WARMUP):
            g = issue_phase_grant(root, phase="audit", task_id="T",
                                  allowed_side_effects=["read"], operation="op")
            verify_ticket_for_admission(root, ticket_id=g.ticket_id, secret=g.secret,
                                        action="phase:audit", input_fingerprint=fp,
                                        side_effect="read", expected_phase="audit")
        grants = 0
        for _ in range(SAMPLES):
            t0 = time.perf_counter()
            g = issue_phase_grant(root, phase="audit", task_id="T",
                                  allowed_side_effects=["read"], operation="op")
            grants += 1
            for _ in range(3):
                verify_ticket_for_admission(root, ticket_id=g.ticket_id,
                                            secret=g.secret, action="phase:audit",
                                            input_fingerprint=fp, side_effect="read",
                                            expected_phase="audit")
            t.append(time.perf_counter() - t0)
    return stats("phase_grant_3steps_1grant", t, llm_calls=0, grants=grants)


def bench_high_impact_ticket() -> dict:
    """高影响票据全周期：签发→校验→兑换（n=20 小样本，如实标注）。"""
    from sopcontrol.tickets import (
        issue_ticket, redeem_ticket, verify_ticket_for_admission,
    )
    t = []
    receipts = 0
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for _ in range(5):
            tk = issue_ticket(root, action="deploy.prod", input_fingerprint="fp",
                              allowed_side_effects=["external_write"])
            verify_ticket_for_admission(root, ticket_id=tk.ticket_id, secret=tk.secret,
                                        action="deploy.prod", input_fingerprint="fp",
                                        side_effect="external_write")
        for _ in range(20):
            t0 = time.perf_counter()
            tk = issue_ticket(root, action="deploy.prod", input_fingerprint="fp",
                              allowed_side_effects=["external_write"])
            verify_ticket_for_admission(root, ticket_id=tk.ticket_id, secret=tk.secret,
                                        action="deploy.prod", input_fingerprint="fp",
                                        side_effect="external_write")
            redeem_ticket(root, ticket_id=tk.ticket_id, secret=tk.secret,
                          action="deploy.prod", input_fingerprint="fp",
                          side_effect="external_write")
            receipts += 1
            t.append(time.perf_counter() - t0)
    return stats("high_impact_ticket_full_cycle", t, n_note=20, llm_calls=0,
                 tickets=receipts)


def bench_process() -> dict:
    """冷/热启动（n=5，如实小样本）+ attach/status + 增量扫描。"""
    out: dict = {}
    cold, warm = [], []
    for i in range(5):
        t0 = time.perf_counter()
        subprocess.run([str(SOPCTL), "project", "check", "."], capture_output=True,
                       cwd=str(REPO))
        dt = time.perf_counter() - t0
        (cold if i == 0 else warm).append(dt)
    out["cold_start_project_check_s"] = cold[0]
    out["warm_start_project_check_s"] = statistics.median(warm)
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([str(SOPCTL), "init", td], capture_output=True, check=True)
        t0 = time.perf_counter()
        subprocess.run([str(SOPCTL), "attach-status", td], capture_output=True)
        out["attach_status_s"] = time.perf_counter() - t0
    # 增量扫描：同一项目连续两次 audit（n=3 取中位；全量约 2.4s 级）
    from sopcontrol.audit import run_audit
    from plugins import DETECTORS, SENSORS
    scans = []
    counts = []
    for _ in range(3):
        t0 = time.perf_counter()
        rep = run_audit(REPO, SENSORS, DETECTORS, persist=False)
        scans.append(time.perf_counter() - t0)
        counts.append(len(rep.evidence))
    out["incremental_audit_median_s"] = statistics.median(scans)
    out["audit_evidence_objects"] = counts[-1]
    return out


def bench_host_overhead() -> dict:
    """宿主开销：bridge run 'true' vs 直接跑（n=20，中位比）。"""
    import shutil
    if shutil.which("true") is None:
        return {"skipped": "no true(1)"}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run([str(SOPCTL), "init", td], capture_output=True, check=True)
        from sopcontrol.bridge import run_bridge
        direct, via = [], []
        for i in range(5 + 20):
            t0 = time.perf_counter()
            subprocess.run(["true"], capture_output=True)
            if i >= 5:
                direct.append(time.perf_counter() - t0)
        for _ in range(3):
            run_bridge(root, argv=["true"], integration_id="perf",
                       action="status")
        for _ in range(20):
            t0 = time.perf_counter()
            run_bridge(root, argv=["true"], integration_id="perf",
                       action="status")
            via.append(time.perf_counter() - t0)
    d_med = statistics.median(direct)
    v_med = statistics.median(via)
    return {"direct_median_ms": d_med * 1000, "bridge_median_ms": v_med * 1000,
            "overhead_ratio": (v_med - d_med) / d_med if d_med else None, "n": 20}


def main() -> int:
    res = {
        "machine": "darwin-arm64",
        "python": "3.12.13",
        "method": f"perf_counter, warmup={WARMUP}, in_process_n={SAMPLES}",
        "benches": [bench_mem_select(), bench_local_registry_action(),
                    bench_phase_grant(), bench_high_impact_ticket()],
        "process": bench_process(),
        "host": bench_host_overhead(),
    }
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
