import os
import time
import errno
import logging
import asyncio
import shutil

logger = logging.getLogger("omnivoice.utils")

def safe_replace(src: str, dst: str) -> None:
    """os.replace with a cross-device fallback."""
    try:
        os.replace(src, dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    # Cross-device fallback: copy to temp file on destination device, then rename
    tmp = f"{dst}.xdev-tmp-{os.getpid()}"
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass

    try:
        os.remove(src)
    except OSError:
        pass

def safe_remove(path: str | os.PathLike[str]) -> bool:
    """Delete a file with exponential backoff to handle transient Windows locks (OneDrive)."""
    retries = 5
    backoff = 0.1
    for i in range(retries):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM) and i < retries - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            # Redact absolute path for privacy
            filename = os.path.basename(path) if isinstance(path, (str, os.PathLike)) else "unknown"
            logger.warning("Permanent lock or permission error removing %s: %s", filename, exc)
            return False
    return False

async def safe_remove_async(path: str | os.PathLike[str]) -> bool:
    """Async version of safe_remove to avoid blocking the event loop."""
    retries = 5
    backoff = 0.1
    for i in range(retries):
        try:
            # os.remove is blocking; run in thread
            await asyncio.to_thread(os.remove, path)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM) and i < retries - 1:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            filename = os.path.basename(path) if isinstance(path, (str, os.PathLike)) else "unknown"
            logger.warning("Permanent lock or permission error removing %s: %s", filename, exc)
            return False
    return False
