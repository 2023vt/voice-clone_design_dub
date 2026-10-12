"""Reliable file deletion for user-visible destructive operations."""
from __future__ import annotations
import os

from omnivoice.utils.fsops import safe_remove


class FileCleanupError(OSError):
    """A requested file exists but could not be removed."""


def unlink_if_present(path: str | os.PathLike[str]) -> bool:
    """Delete *path*, returning whether it existed.

    Missing files make delete operations idempotent. Other failures must reach
    the caller so it cannot discard the only record from which cleanup can be
    retried.
    """
    if not safe_remove(path):
        # Check if it actually exists; if safe_remove returns False and file is there, it's a lock.
        if os.path.exists(path):
            raise FileCleanupError(f"Failed to remove locked file: {path}")
    return True
