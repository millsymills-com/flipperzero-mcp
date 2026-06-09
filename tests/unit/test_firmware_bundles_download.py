"""Unit tests for verified bundle downloads."""

import hashlib
import io
import json
import tarfile

import pytest

from flipperzero_mcp.firmware.bundles import BundleError, download_bundle
from flipperzero_mcp.firmware.flavor import FirmwareFlavor


def _tgz_bytes():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in {"upd/update.fuf": b"manifest", "upd/firmware.dfu": b"DFU"}.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_official_download_verifies_sha256(httpx_mock):
    tgz = _tgz_bytes()
    sha = hashlib.sha256(tgz).hexdigest()
    directory = {
        "channels": [
            {
                "id": "release",
                "versions": [
                    {
                        "version": "1.4.3",
                        "files": [
                            {
                                "url": "https://up.example/flipper-z-f7-update-1.4.3.tgz",
                                "target": "f7",
                                "type": "update_tgz",
                                "sha256": sha,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text=json.dumps(directory)
    )
    httpx_mock.add_response(url="https://up.example/flipper-z-f7-update-1.4.3.tgz", content=tgz)
    bundle = await download_bundle(
        FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
    )
    assert bundle.target == "f7"


@pytest.mark.asyncio
async def test_official_download_aborts_on_sha256_mismatch(httpx_mock):
    tgz = _tgz_bytes()
    directory = {
        "channels": [
            {
                "id": "release",
                "versions": [
                    {
                        "version": "1.4.3",
                        "files": [
                            {
                                "url": "https://up.example/x.tgz",
                                "target": "f7",
                                "type": "update_tgz",
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text=json.dumps(directory)
    )
    httpx_mock.add_response(url="https://up.example/x.tgz", content=tgz)
    with pytest.raises(BundleError, match="sha256"):
        await download_bundle(
            FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
        )


@pytest.mark.asyncio
async def test_momentum_download_verifies_digest(httpx_mock):
    tgz = _tgz_bytes()
    sha = hashlib.sha256(tgz).hexdigest()
    releases = [
        {
            "tag_name": "mntm-012",
            "assets": [
                {
                    "name": "flipper-z-f7-update-mntm-012.tgz",
                    "digest": f"sha256:{sha}",
                    "browser_download_url": "https://gh.example/f7-update.tgz",
                }
            ],
        }
    ]
    httpx_mock.add_response(
        url="https://api.github.com/repos/Next-Flip/Momentum-Firmware/releases",
        text=json.dumps(releases),
    )
    httpx_mock.add_response(url="https://gh.example/f7-update.tgz", content=tgz)
    bundle = await download_bundle(
        FirmwareFlavor.MOMENTUM, channel="release", version="latest", target="f7"
    )
    assert bundle.target == "f7"


@pytest.mark.asyncio
async def test_official_download_wraps_http_error_as_bundle_error(httpx_mock):
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", status_code=503
    )
    with pytest.raises(BundleError, match="failed to fetch"):
        await download_bundle(
            FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
        )


@pytest.mark.asyncio
async def test_official_download_wraps_malformed_json_as_bundle_error(httpx_mock):
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text="<html>not json"
    )
    with pytest.raises(BundleError, match="malformed JSON"):
        await download_bundle(
            FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
        )


@pytest.mark.asyncio
async def test_official_download_wraps_missing_url_key_as_bundle_error(httpx_mock):
    directory = {
        "channels": [
            {
                "id": "release",
                "versions": [
                    {
                        "version": "1.4.3",
                        "files": [{"target": "f7", "type": "update_tgz", "sha256": "0" * 64}],
                    }
                ],
            }
        ]
    }
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text=json.dumps(directory)
    )
    with pytest.raises(BundleError, match="malformed official bundle entry"):
        await download_bundle(
            FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
        )


@pytest.mark.asyncio
async def test_momentum_download_aborts_without_digest(httpx_mock):
    tgz = _tgz_bytes()
    releases = [
        {
            "tag_name": "mntm-012",
            "assets": [
                {
                    "name": "flipper-z-f7-update-mntm-012.tgz",
                    "browser_download_url": "https://gh.example/f7-update.tgz",
                }
            ],
        }
    ]
    httpx_mock.add_response(
        url="https://api.github.com/repos/Next-Flip/Momentum-Firmware/releases",
        text=json.dumps(releases),
    )
    httpx_mock.add_response(url="https://gh.example/f7-update.tgz", content=tgz)
    with pytest.raises(BundleError, match="digest"):
        await download_bundle(
            FirmwareFlavor.MOMENTUM, channel="release", version="latest", target="f7"
        )
