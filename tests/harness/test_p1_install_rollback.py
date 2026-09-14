"""§12.3 必须添加的反例测试（Batch 7: 安装、备份、移除和回滚）。"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from sopcontrol.bridge import (
    canonical_invocation,
    install_wrapper,
    remove_wrapper,
    run_bridge,
)
from sopcontrol.bridge_scaffold import install_scaffold


def test_install_new_target_and_remove(tmp_path):
    # 新目标安装后生成 wrapper，remove 时彻底删除无残留
    info = install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "hi"], name="demo-tool")
    launcher = Path(info["launcher"])
    assert launcher.is_file()
    assert os.access(launcher, os.X_OK)

    res = remove_wrapper(tmp_path, name="demo-tool")
    assert res["removed"] is True
    assert res["restored"] is False
    assert not launcher.exists()


def test_install_existing_file_backups_once(tmp_path):
    # 已有普通文件安装时必须先备份至 rollback 目录
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    orig_file = bin_dir / "my-tool"
    orig_file.write_text("ORIGINAL_CONTENT", encoding="utf-8")

    info = install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "wrapper"], name="my-tool")
    assert orig_file.read_text(encoding="utf-8") != "ORIGINAL_CONTENT"

    backup_file = tmp_path / ".sopcontrol-local" / "bridge-rollback" / "my-tool.prev"
    assert backup_file.is_file()
    assert backup_file.read_text(encoding="utf-8") == "ORIGINAL_CONTENT"


def test_install_preserves_original_mode(tmp_path):
    # 安装会记录原权限，remove 回滚时恢复原 mode
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    orig_file = bin_dir / "mode-tool"
    orig_file.write_text("MY_SCRIPT", encoding="utf-8")
    orig_file.chmod(0o640)

    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "1"], name="mode-tool")
    assert (orig_file.stat().st_mode & 0o777) == 0o755

    remove_wrapper(tmp_path, name="mode-tool")
    assert orig_file.is_file()
    assert (orig_file.stat().st_mode & 0o777) == 0o640
    assert orig_file.read_text(encoding="utf-8") == "MY_SCRIPT"


def test_install_rejects_symlink_target(tmp_path):
    # 目标为符号链接时，默认拒绝覆盖
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    real_file = tmp_path / "real_script.sh"
    real_file.write_text("REAL", encoding="utf-8")
    symlink_target = bin_dir / "sym-tool"
    try:
        symlink_target.symlink_to(real_file)
    except OSError:
        pytest.skip("平台不支持 symlink")

    with pytest.raises(ValueError, match="(符号链接|symlink)"):
        install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "test"], name="sym-tool")

    # 真实文件与符号链接都未被破坏
    assert symlink_target.is_symlink()
    assert real_file.read_text(encoding="utf-8") == "REAL"


def test_install_rejects_special_target(tmp_path):
    # 目标为特殊文件（如 FIFO）时，默认拒绝覆盖
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fifo_target = bin_dir / "fifo-tool"
    try:
        os.mkfifo(fifo_target)
    except (OSError, AttributeError):
        pytest.skip("平台不支持 fifo")

    with pytest.raises(ValueError, match="(特殊文件|special)"):
        install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "test"], name="fifo-tool")


def test_backup_failure_leaves_target_unchanged(tmp_path, monkeypatch):
    # 备份失败时，目标文件绝对不能被修改
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    orig_file = bin_dir / "fail-backup-tool"
    orig_file.write_text("IMPORTANT_BUSINESS_CODE", encoding="utf-8")

    # 模拟创建备份目录或写入失败
    def bad_write_bytes(self, data):
        raise OSError("Disk full / permission denied")

    monkeypatch.setattr(Path, "write_bytes", bad_write_bytes)

    with pytest.raises((RuntimeError, OSError)):
        install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "fail"], name="fail-backup-tool")

    assert orig_file.read_text(encoding="utf-8") == "IMPORTANT_BUSINESS_CODE"


def test_install_is_atomic_on_write_failure(tmp_path, monkeypatch):
    # 安装写入失败时，原有文件完好无损，且无残留临时文件
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    orig_file = bin_dir / "atomic-tool"
    orig_file.write_text("STABLE_CONTENT", encoding="utf-8")

    def bad_replace(src, dst):
        raise OSError("Replace failure")

    monkeypatch.setattr(os, "replace", bad_replace)

    with pytest.raises((RuntimeError, OSError)):
        install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "atom"], name="atomic-tool")

    assert orig_file.read_text(encoding="utf-8") == "STABLE_CONTENT"


def test_repeated_install_restores_original_file(tmp_path):
    # 连续重复安装多次，备份不能被中间 wrapper 覆盖，remove 后必须能恢复最初业务文件
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    orig_file = bin_dir / "repeated-tool"
    orig_file.write_text("PRISTINE_SOURCE_V1", encoding="utf-8")

    # 第一次安装
    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "wrap1"], name="repeated-tool")
    # 第二次安装
    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "wrap2"], name="repeated-tool")

    # remove 时应恢复最初的 PRISTINE_SOURCE_V1
    res = remove_wrapper(tmp_path, name="repeated-tool")
    assert res["restored"] is True
    assert orig_file.read_text(encoding="utf-8") == "PRISTINE_SOURCE_V1"


def test_remove_does_not_delete_unowned_file(tmp_path):
    # 针对未登记在 manifest 中的未受管文件，remove 必须无副作用返回，不能直接 unlink
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    unowned = bin_dir / "foreign-tool"
    unowned.write_text("FOREIGN_USER_TOOL", encoding="utf-8")

    res = remove_wrapper(tmp_path, name="foreign-tool")
    assert res["removed"] is False
    assert res["restored"] is False
    assert unowned.is_file()
    assert unowned.read_text(encoding="utf-8") == "FOREIGN_USER_TOOL"


def test_tampered_manifest_path_is_rejected(tmp_path):
    # 如果 manifest 中的 files 字段被篡改指向外部路径，remove 必须零副作用拒绝
    # （recovery_required=True，保留现场交人工），绝不删除/读取外部文件（§8.4）
    outside_file = tmp_path / "sensitive.txt"
    outside_file.write_text("SENSITIVE_DATA", encoding="utf-8")

    # 安装一个正常 wrapper
    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "normal"], name="tamper-test")

    # 篡改 manifest
    manifest_path = tmp_path / ".sopcontrol-local" / "bridge-rollback.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tamper-test"]["files"] = [str(outside_file)]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = remove_wrapper(tmp_path, name="tamper-test")
    assert result.get("recovery_required") is True
    assert result.get("removed") is False and result.get("restored") is False
    assert "受控 bin 目录" in result.get("why", "")

    # 外部文件原样保留；清单条目保留（可重试/人工修复）
    assert outside_file.is_file()
    assert outside_file.read_text(encoding="utf-8") == "SENSITIVE_DATA"
    manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "tamper-test" in manifest_after


def test_remove_preserves_third_party_hooks(tmp_path):
    # detach / remove 操作必须保留第三方 git hook
    from sopcontrol.attachment import apply_detachment

    git_hooks_dir = tmp_path / ".git" / "hooks"
    git_hooks_dir.mkdir(parents=True, exist_ok=True)
    custom_hook = git_hooks_dir / "pre-push"
    custom_hook.write_text("#!/bin/sh\n# custom enterprise linter hook\nexit 0\n", encoding="utf-8")
    custom_hook.chmod(0o755)

    res = apply_detachment(tmp_path, confirm=True)
    assert custom_hook.is_file()
    assert "enterprise linter" in custom_hook.read_text(encoding="utf-8")


def test_absent_harness_is_not_created_implicitly(tmp_path):
    # 没有显式安装 harness 时，调用 canonical_invocation 或其它只读解析绝不隐式在本地写入文件
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"

    resolved = canonical_invocation(tmp_path, "absent.cli", ["my-tool", "arg1"])
    assert resolved == ["my-tool", "arg1"]
    if bin_dir.exists():
        assert list(bin_dir.iterdir()) == []


def test_tampered_prev_backup_external_sentinel_never_touched(tmp_path):
    # §8.2（R-02）：prev_backup 被篡改为仓库外 sentinel → 零副作用拒绝，
    # sentinel 永不被读取/删除，清单条目保留可人工修复
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("DO-NOT-DELETE", encoding="utf-8")

    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "v1"], name="bk-test")

    manifest_path = tmp_path / ".sopcontrol-local" / "bridge-rollback.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bk-test"]["prev_backup"] = str(sentinel)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = remove_wrapper(tmp_path, name="bk-test")
    assert result.get("recovery_required") is True
    assert result.get("restored") is False and result.get("removed") is False
    assert sentinel.is_file()
    assert sentinel.read_text(encoding="utf-8") == "DO-NOT-DELETE"
    assert "bk-test" in json.loads(manifest_path.read_text(encoding="utf-8"))


def test_prev_backup_symlink_rejected(tmp_path):
    # §8.2：prev_backup 是 symlink（即使指向回滚目录内）→ 拒绝，目标不被消费。
    # 预置原目标再安装才会产生 backup（覆盖不等于拥有）。
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "bk-link").write_text("#!/bin/sh\necho old\n", encoding="utf-8")
    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "v1"], name="bk-link")
    backup = tmp_path / ".sopcontrol-local" / "bridge-rollback" / "bk-link.prev"
    assert backup.is_file()
    decoy = tmp_path / ".sopcontrol-local" / "bridge-rollback" / "decoy.txt"
    decoy.write_text("decoy", encoding="utf-8")
    backup.unlink()
    backup.symlink_to(decoy)

    result = remove_wrapper(tmp_path, name="bk-link")
    assert result.get("recovery_required") is True
    assert decoy.is_file()


def test_missing_prev_backup_removes_wrapper_without_fake_restore(tmp_path):
    # backup 缺失：不得伪造恢复；wrapper 删除、清单移除
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "bk-missing").write_text("#!/bin/sh\necho old\n", encoding="utf-8")
    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "v1"], name="bk-missing")
    backup = tmp_path / ".sopcontrol-local" / "bridge-rollback" / "bk-missing.prev"
    assert backup.is_file()
    backup.unlink()
    result = remove_wrapper(tmp_path, name="bk-missing")
    assert result["removed"] is True and result["restored"] is False
    assert not (tmp_path / ".sopcontrol-local" / "bin" / "bk-missing").exists()
    manifest_path = tmp_path / ".sopcontrol-local" / "bridge-rollback.json"
    assert "bk-missing" not in json.loads(manifest_path.read_text(encoding="utf-8"))


def test_remove_restores_original_content_from_valid_backup(tmp_path):
    # 正向：合法 backup 恢复原文件内容与权限
    bin_dir = tmp_path / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    pre = bin_dir / "bk-valid"
    pre.write_text("#!/bin/sh\necho ORIGINAL\n", encoding="utf-8")
    pre.chmod(0o755)

    install_wrapper(tmp_path, integration_id="demo.cli", command=["echo", "v2"], name="bk-valid")
    assert "bridge" in pre.read_text(encoding="utf-8")

    result = remove_wrapper(tmp_path, name="bk-valid")
    assert result["restored"] is True
    assert "ORIGINAL" in pre.read_text(encoding="utf-8")
    assert pre.stat().st_mode & 0o777 == 0o755
