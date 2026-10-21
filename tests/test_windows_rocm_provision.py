"""Installer integrity and ABI boundaries; no installed native packages needed."""
import hashlib
import importlib
import json
import zipfile

import pytest


def module(name):
    return importlib.import_module(f"core.windows_rocm.{name}")


def test_shared_installer_exists_without_importing_native_packages():
    import sys

    before = set(sys.modules)
    assert importlib.util.find_spec("core.windows_rocm") is not None
    module("install")
    assert not ({"torch", "torchaudio", "torchvision", "ctranslate2"} & (set(sys.modules) - before))


@pytest.mark.parametrize("platform,version,architecture", [
    ("linux", (3, 12), "win-amd64"),
    ("win32", (3, 11), "win-amd64"),
    ("win32", (3, 12), "win-arm64"),
    ("win32", (3, 12), "win32"),
])
def test_wrong_target_refused_before_install(platform, version, architecture):
    with pytest.raises(RuntimeError, match="x64 Python 3.12"):
        module("recipe").validate_target(platform, version, architecture)


def test_recipe_identity_invalidates_on_any_byte_change(tmp_path):
    recipe = module("recipe")
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe.load_recipe()))
    initial = recipe.recipe_identity(path)
    path.write_text(path.read_text() + "\n")
    assert recipe.recipe_identity(path) != initial
    recipe.validate_target("win32", (3, 12), "win-amd64")


def archive_fixture(tmp_path, entries=None):
    member = "nested/ctranslate2-4.8.2-cp312-cp312-win_amd64.whl"
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in entries or [(member, b"wheel")]:
            bundle.writestr(name, data)
    config = {
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "wheel_member": member,
        "wheel_sha256": hashlib.sha256(b"wheel").hexdigest(),
    }
    return archive, config


def test_only_named_checked_wheel_is_written(tmp_path):
    archive, config = archive_fixture(tmp_path, [
        ("../../outside", b"evil"),
        ("nested/ctranslate2-4.8.2-cp312-cp312-win_amd64.whl", b"wheel"),
    ])
    destination = tmp_path / "output"
    destination.mkdir()
    wheel = module("artifacts").checked_wheel(archive, destination, config)
    assert wheel.read_bytes() == b"wheel"
    assert list(destination.iterdir()) == [wheel]


@pytest.mark.parametrize("field", ["archive_sha256", "wheel_sha256"])
def test_tampered_artifacts_never_return_installable_wheel(tmp_path, field):
    archive, config = archive_fixture(tmp_path)
    config[field] = "0" * 64
    with pytest.raises(RuntimeError, match="SHA-256"):
        module("artifacts").checked_wheel(archive, tmp_path, config)


def test_duplicate_member_refused(tmp_path):
    member = "nested/ctranslate2-4.8.2-cp312-cp312-win_amd64.whl"
    with pytest.warns(UserWarning):
        archive, config = archive_fixture(tmp_path, [(member, b"wheel"), (member, b"wheel")])
    with pytest.raises(RuntimeError, match="exactly one"):
        module("artifacts").checked_wheel(archive, tmp_path, config)
