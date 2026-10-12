import os
import errno
import pytest
from unittest.mock import patch, MagicMock
from utils.fsops import safe_remove, safe_remove_async
import asyncio

@pytest.mark.asyncio
async def test_safe_remove_retries_and_succeeds():
    """Verify that safe_remove retries on EPERM/EACCES and eventually succeeds."""
    test_file = "test_retry_success.wav"
    with open(test_file, "w") as f:
        f.write("test content")

    try:
        # Simulate: Fail twice with EPERM, then succeed
        with patch("os.remove") as mock_remove:
            mock_remove.side_effect = [
                OSError(errno.EPERM, "Operation not permitted"),
                OSError(errno.EACCES, "Permission denied"),
                None,
            ]

            result = safe_remove(test_file)

            assert result is True
            assert mock_remove.call_count == 3
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

@pytest.mark.asyncio
async def test_safe_remove_fails_after_max_retries():
    """Verify that safe_remove returns False after exhausting all retries."""
    test_file = "test_retry_fail.wav"
    with open(test_file, "w") as f:
        f.write("test content")

    try:
        with patch("os.remove") as mock_remove:
            # Always fail with EPERM
            mock_remove.side_effect = OSError(errno.EPERM, "Operation not permitted")

            result = safe_remove(test_file)

            assert result is False
            assert mock_remove.call_count == 5 # retries = 5 in fsops.py
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

@pytest.mark.asyncio
async def test_safe_remove_async_retries_and_succeeds():
    """Verify that safe_remove_async retries and eventually succeeds."""
    test_file = "test_async_success.wav"
    with open(test_file, "w") as f:
        f.write("test content")

    try:
        with patch("os.remove") as mock_remove:
            mock_remove.side_effect = [
                OSError(errno.EPERM, "Operation not permitted"),
                None,
            ]

            result = await safe_remove_async(test_file)

            assert result is True
            assert mock_remove.call_count == 2
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

@pytest.mark.asyncio
async def test_safe_remove_handles_missing_file():
    """Verify that both sync and async remove return True if file is missing."""
    test_file = "non_existent_file.wav"
    if os.path.exists(test_file):
        os.remove(test_file)

    assert safe_remove(test_file) is True
    assert await safe_remove_async(test_file) is True

if __name__ == "__main__":
    import pytest
    import sys
    # Run tests if executed directly
    pytest.main([__file__])
