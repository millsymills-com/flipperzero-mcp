"""Unit tests for local bundle extraction."""

import io
import tarfile

import pytest

from flipperzero_mcp.firmware.bundles import BundleError, load_local_bundle


def _make_tgz(tmp_path, files):
    path = tmp_path / "flipper-z-f7-update-test.tgz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_load_local_bundle_reads_files_and_target(tmp_path):
    tgz = _make_tgz(tmp_path, {"upd/update.fuf": b"manifest", "upd/firmware.dfu": b"DFU"})
    bundle = load_local_bundle(str(tgz))
    assert bundle.manifest_name == "update.fuf"
    assert bundle.target == "f7"
    names = {rel for rel, _ in bundle.files}
    assert names == {"update.fuf", "firmware.dfu"}


def test_load_local_bundle_rejects_missing_manifest(tmp_path):
    tgz = _make_tgz(tmp_path, {"upd/firmware.dfu": b"DFU"})
    with pytest.raises(BundleError, match=r"update\.fuf"):
        load_local_bundle(str(tgz))


def test_load_local_bundle_rejects_empty_archive(tmp_path):
    path = tmp_path / "flipper-z-f7-update-empty.tgz"
    with tarfile.open(path, "w:gz"):
        pass
    with pytest.raises(BundleError, match="empty"):
        load_local_bundle(str(path))
