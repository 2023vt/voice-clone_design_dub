"""Stale dub preview uploads are swept instead of accumulating forever."""
import os
import time

from core.file_cleanup import sweep_stale_files


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_removes_only_old_regular_files(tmp_path):
    old = tmp_path / "old.mp4"
    new = tmp_path / "new.mp4"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    _age(old, 3 * 3600)
    sub = tmp_path / "sub"
    sub.mkdir()
    _age(sub, 3 * 3600)

    assert sweep_stale_files(tmp_path, 3600) == 1
    assert not old.exists()
    assert new.exists()
    assert sub.is_dir()


def test_missing_directory_is_a_noop(tmp_path):
    assert sweep_stale_files(tmp_path / "nope", 1) == 0


def test_symlink_is_not_followed(tmp_path):
    target = tmp_path / "keep.bin"
    target.write_bytes(b"x")
    _age(target, 10_000)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    link = scratch / "link.mp4"
    try:
        link.symlink_to(target)
    except OSError:
        return
    assert sweep_stale_files(scratch, 1) == 0
    assert target.exists()
