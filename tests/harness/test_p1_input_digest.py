"""§11.3 必须添加的反例测试（Batch 6: 输入摘要和路径规范化）。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from sopcontrol.task import submit_input_digest_for


def test_absolute_input_path_is_rejected(tmp_path):
    # 绝对路径必须被明确拒绝，不得直接当作相对路径或系统绝对路径处理
    (tmp_path / "file.txt").write_text("data", encoding="utf-8")
    abs_path = str((tmp_path / "file.txt").resolve())

    with pytest.raises(ValueError, match="(绝对路径|absolute)"):
        submit_input_digest_for(tmp_path, [abs_path])

    with pytest.raises(ValueError, match="(绝对路径|absolute)"):
        submit_input_digest_for(tmp_path, ["/etc/passwd"])


def test_parent_segment_is_rejected(tmp_path):
    # 包含 .. 的路径即使最终被 resolves_inside 解析在 root 内，也必须在规范化阶段拒绝
    d = tmp_path / "sub"
    d.mkdir()
    (tmp_path / "file.txt").write_text("data", encoding="utf-8")

    with pytest.raises(ValueError, match="(\\.\\.|parent)"):
        submit_input_digest_for(tmp_path, ["sub/../file.txt"])

    with pytest.raises(ValueError, match="(\\.\\.|parent)"):
        submit_input_digest_for(tmp_path, ["../escaped"])


def test_duplicate_normalized_paths_are_not_ambiguous(tmp_path):
    # 规范化后重复的路径必须去重，不能产生两套不同身份或重复计算
    (tmp_path / "file.txt").write_text("data", encoding="utf-8")

    d1 = submit_input_digest_for(tmp_path, ["file.txt"])
    d2 = submit_input_digest_for(tmp_path, ["./file.txt", "file.txt", "file.txt/"])
    assert d1 == d2


def test_directory_file_content_changes_digest(tmp_path):
    # 目录内任意文件内容发生修改，目录摘要必须随之改变
    d = tmp_path / "docs"
    d.mkdir()
    f = d / "doc.txt"
    f.write_text("version 1", encoding="utf-8")
    orig_digest = submit_input_digest_for(tmp_path, ["docs"])

    f.write_text("version 2", encoding="utf-8")
    new_digest = submit_input_digest_for(tmp_path, ["docs"])
    assert new_digest != orig_digest


def test_directory_add_delete_rename_changes_digest(tmp_path):
    # 目录内增、删、改名文件，摘要必须不同
    d = tmp_path / "assets"
    d.mkdir()
    (d / "a.png").write_bytes(b"PNG1")
    base = submit_input_digest_for(tmp_path, ["assets"])

    # 增加文件
    (d / "b.png").write_bytes(b"PNG2")
    added = submit_input_digest_for(tmp_path, ["assets"])
    assert added != base

    # 删除文件
    (d / "b.png").unlink()
    assert submit_input_digest_for(tmp_path, ["assets"]) == base

    # 重命名文件
    (d / "a.png").rename(d / "c.png")
    renamed = submit_input_digest_for(tmp_path, ["assets"])
    assert renamed != base


def test_directory_order_does_not_change_digest(tmp_path):
    # 不同文件系统遍历顺序或创建顺序不同，目录摘要必须稳定一致
    d1 = tmp_path / "dir1"
    d1.mkdir()
    (d1 / "z.txt").write_text("Z", encoding="utf-8")
    (d1 / "a.txt").write_text("A", encoding="utf-8")
    (d1 / "m.txt").write_text("M", encoding="utf-8")

    digest1 = submit_input_digest_for(tmp_path, ["dir1"])

    d2 = tmp_path / "dir2"
    d2.mkdir()
    (d2 / "a.txt").write_text("A", encoding="utf-8")
    (d2 / "m.txt").write_text("M", encoding="utf-8")
    (d2 / "z.txt").write_text("Z", encoding="utf-8")

    # 规范化相对条目内容一致时摘要必须相同
    shutil.rmtree(d1)
    d1.mkdir()
    (d1 / "a.txt").write_text("A", encoding="utf-8")
    (d1 / "m.txt").write_text("M", encoding="utf-8")
    (d1 / "z.txt").write_text("Z", encoding="utf-8")
    assert submit_input_digest_for(tmp_path, ["dir1"]) == digest1


def test_empty_directory_differs_from_missing_path(tmp_path):
    # 空目录与不存在路径必须产生不同的摘要
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    d_empty = submit_input_digest_for(tmp_path, ["empty_dir"])
    d_missing = submit_input_digest_for(tmp_path, ["non_existent_dir"])
    assert d_empty != d_missing


def test_symlink_escape_is_rejected(tmp_path):
    # 指向 root 外的软链接必须被明确拒绝
    outside = tmp_path.parent / "outside_file.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link_outside"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("平台不支持 symlink")

    with pytest.raises(ValueError, match="(逃逸|outside)"):
        submit_input_digest_for(tmp_path, ["link_outside"])


def test_symlink_loop_is_rejected(tmp_path):
    # 软链接死循环必须被明确拒绝（fail-closed），不能只记录标记后继续
    loop_link = tmp_path / "loop_link"
    try:
        loop_link.symlink_to(loop_link)
    except OSError:
        pytest.skip("平台不支持 symlink")

    with pytest.raises(ValueError, match="(循环|cycle|loop)"):
        submit_input_digest_for(tmp_path, ["loop_link"])


def test_special_file_is_rejected(tmp_path):
    # FIFO、socket 等特殊文件必须被拒绝
    fifo = tmp_path / "test_fifo"
    try:
        os.mkfifo(fifo)
    except (OSError, AttributeError):
        pytest.skip("平台不支持 fifo")

    with pytest.raises(ValueError, match="(特殊文件|special)"):
        submit_input_digest_for(tmp_path, ["test_fifo"])


def test_unreadable_input_fails_closed(tmp_path):
    # 无法读取的输入文件或目录必须 fail-closed 抛出异常，不能只记录 unreadable 标记继续放行
    unreadable = tmp_path / "unreadable.txt"
    unreadable.write_text("secret", encoding="utf-8")
    try:
        unreadable.chmod(0o000)
    except OSError:
        pytest.skip("平台不支持 chmod 000")

    try:
        with pytest.raises((ValueError, OSError, PermissionError)):
            submit_input_digest_for(tmp_path, ["unreadable.txt"])
    finally:
        try:
            unreadable.chmod(0o644)
        except OSError:
            pass


def test_large_file_is_stream_hashed(tmp_path):
    # 大文件必须流式分块哈希，且内容完全确定
    large = tmp_path / "large.bin"
    with open(large, "wb") as f:
        for _ in range(20):
            f.write(b"K" * (256 * 1024))

    d1 = submit_input_digest_for(tmp_path, ["large.bin"])
    d2 = submit_input_digest_for(tmp_path, ["large.bin"])
    assert d1 == d2
    assert d1.startswith("in-")


def test_same_size_content_change_changes_digest(tmp_path):
    # 保持字节大小完全不变，仅修改 1 字节内容，摘要必须改变
    f = tmp_path / "fixed_size.txt"
    f.write_bytes(b"A" * 1024)
    d1 = submit_input_digest_for(tmp_path, ["fixed_size.txt"])

    f.write_bytes(b"A" * 1023 + b"B")
    d2 = submit_input_digest_for(tmp_path, ["fixed_size.txt"])
    assert d1 != d2
