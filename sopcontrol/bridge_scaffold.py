"""Bridge P2：三语言入口模板（python/node/sh adapter scaffold）。

Level 2/3 轻连接：生成的脚本只做一件事——运行时解析 sopctl，
把原命令经 `sopctl bridge run` 透传（Ticket/回执由 Bridge 负责）。
不改业务源码、不含 secret、退出码直传；安装位置只在
.sopcontrol-local/bin，回滚走 bridge-rollback.json（bridge.remove_wrapper）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bridge import _load_manifest, _save_manifest

LANGS = ("sh", "python", "node")

_EXT = {"sh": "", "python": ".py", "node": ".js"}


def bridge_run_args(
    *, integration_id: str, action: str, command: list[str],
    side_effect: str = "", task_id: str = "",
) -> list[str]:
    """待透传的 bridge run 参数（不含二进制，由模板运行时解析）。"""
    args = ["bridge", "run", "--action", action,
            "--integration-id", integration_id]
    if side_effect:
        args += ["--side-effect", side_effect]
    if task_id:
        args += ["--task-id", task_id]
    args += ["--", *[str(c) for c in command]]
    return args


_SH_RESOLVER = """\
# resolver：SOPCTL_BIN → 仓库 .venv → PATH → python -m（不依赖激活态 shell）
BIN=""
if [ -n "${SOPCTL_BIN:-}" ] && [ -x "$SOPCTL_BIN" ]; then BIN="$SOPCTL_BIN"; fi
if [ -z "$BIN" ]; then
  ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
  if [ -x "$ROOT/.venv/bin/sopctl" ]; then BIN="$ROOT/.venv/bin/sopctl"; fi
fi
if [ -z "$BIN" ] && command -v sopctl >/dev/null 2>&1; then BIN="sopctl"; fi
if [ -z "$BIN" ]; then
  ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
  if [ -x "$ROOT/.venv/bin/python" ]; then BIN="$ROOT/.venv/bin/python -m sopcontrol.cli"; fi
fi
if [ -z "$BIN" ]; then echo "sopctl not found (SOPCTL_BIN/.venv/PATH)" >&2; exit 127; fi
"""


def render_scaffold(*, lang: str, bridge_args: list[str]) -> str:
    """渲染单文件 scaffold（无 secret、无网络、无业务逻辑）。"""
    if lang not in LANGS:
        raise ValueError(f"unsupported lang {lang!r} (want one of {LANGS})")
    argv_json = json.dumps(list(bridge_args), ensure_ascii=False)
    if lang == "sh":
        return (
            "#!/bin/sh\n"
            "# sopcontrol bridge scaffold — remove via sopctl bridge remove\n"
            f"{_SH_RESOLVER}"
            f"exec $BIN { ' '.join(json.dumps(p) for p in bridge_args) } \"$@\"\n"
        )
    if lang == "python":
        return (
            "#!/usr/bin/env python3\n"
            '"""sopcontrol bridge scaffold — remove via sopctl bridge remove."""\n'
            "import os\nimport shutil\nimport subprocess\nimport sys\n"
            "from pathlib import Path\n\n"
            f"BRIDGE_ARGS = {argv_json}\n\n"
            "def _resolve():\n"
            '    explicit = os.environ.get("SOPCTL_BIN", "").strip()\n'
            "    if explicit and os.access(explicit, os.X_OK):\n"
            "        return [explicit]\n"
            "    root = Path(__file__).resolve().parents[2]\n"
            "    venv_bin = root / '.venv' / 'bin' / 'sopctl'\n"
            "    if venv_bin.is_file() and os.access(venv_bin, os.X_OK):\n"
            "        return [str(venv_bin)]\n"
            "    which = shutil.which('sopctl')\n"
            "    if which:\n"
            "        return [which]\n"
            "    venv_py = root / '.venv' / 'bin' / 'python'\n"
            "    if venv_py.is_file():\n"
            "        return [str(venv_py), '-m', 'sopcontrol.cli']\n"
            "    return [sys.executable, '-m', 'sopcontrol.cli']\n\n"
            "if __name__ == '__main__':\n"
            "    proc = subprocess.run(_resolve() + BRIDGE_ARGS + sys.argv[1:])\n"
            "    sys.exit(proc.returncode)\n"
        )
    return (
        "#!/usr/bin/env node\n"
        "// sopcontrol bridge scaffold — remove via sopctl bridge remove.\n"
        "import { spawnSync } from 'node:child_process';\n"
        "import { existsSync } from 'node:fs';\n"
        "import path from 'node:path';\n"
        f"const BRIDGE_ARGS = {argv_json};\n"
        "function resolve() {\n"
        "  const bin = (process.env.SOPCTL_BIN || '').trim();\n"
        "  if (bin && existsSync(bin)) return [bin];\n"
        "  const root = path.resolve(path.dirname(process.argv[1]), '..', '..');\n"
        "  const venvBin = path.join(root, '.venv', 'bin', 'sopctl');\n"
        "  if (existsSync(venvBin)) return [venvBin];\n"
        "  return ['sopctl'];\n"
        "}\n"
        "const argv = resolve().concat(BRIDGE_ARGS, process.argv.slice(2));\n"
        "const r = spawnSync(argv[0], argv.slice(1), { stdio: 'inherit' });\n"
        "process.exit(r.status ?? 1);\n"
    )


def install_scaffold(
    root: Path, *, name: str, lang: str, integration_id: str, action: str,
    command: list[str], side_effect: str = "", task_id: str = "",
) -> dict[str, Any]:
    """写入 scaffold 文件并登记回滚清单；返回 {name, file, rollback}。"""
    root = Path(root)
    if lang not in LANGS:
        raise ValueError(f"unsupported lang {lang!r} (want one of {LANGS})")
    name = name or (integration_id.replace(".", "-") + "-bridge")
    bin_dir = root / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / (name + _EXT[lang])
    existed = target.exists()
    args = bridge_run_args(
        integration_id=integration_id, action=action, command=command,
        side_effect=side_effect, task_id=task_id,
    )
    target.write_text(render_scaffold(lang=lang, bridge_args=args), encoding="utf-8")
    target.chmod(0o755)
    manifest = _load_manifest(root)
    manifest[name] = {
        "integration_id": integration_id,
        "action": action,
        "lang": lang,
        "command": list(command),
        "files": [str(target)],
        "existed_before": existed,
    }
    rollback = _save_manifest(root, manifest)
    return {"name": name, "file": str(target), "rollback": str(rollback)}
