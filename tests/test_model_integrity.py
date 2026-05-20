"""Checksum-verification tests for model downloads.

These don't hit the network — they exercise the verify path against synthetic
files so CI stays offline and fast.
"""

from __future__ import annotations

import json

import pytest

from snapgrade import models


def test_bundled_manifest_loads_and_is_nonempty():
    digests = models._expected_digests()
    assert digests, "models_manifest.json should pin at least one model"
    # Every pinned name must be a real registry entry.
    for name in digests:
        assert name in models._REGISTRY, f"manifest pins unknown model '{name}'"


def test_verify_passes_on_matching_digest(tmp_path, monkeypatch):
    artifact = tmp_path / "u2netp.onnx"
    artifact.write_bytes(b"hello world")
    digest = models._sha256(artifact)
    monkeypatch.setattr(models, "_expected_digests", lambda: {"u2netp": digest})
    models._verify("u2netp", artifact)  # must not raise
    assert artifact.exists()


def test_verify_rejects_and_deletes_on_mismatch(tmp_path, monkeypatch):
    artifact = tmp_path / "u2netp.onnx"
    artifact.write_bytes(b"tampered payload")
    monkeypatch.setattr(models, "_expected_digests", lambda: {"u2netp": "0" * 64})
    with pytest.raises(models.ChecksumError):
        models._verify("u2netp", artifact)
    assert not artifact.exists(), "a tampered artifact must be removed"


def test_unpinned_model_skips_verification(tmp_path, monkeypatch):
    artifact = tmp_path / "mystery.onnx"
    artifact.write_bytes(b"whatever")
    monkeypatch.setattr(models, "_expected_digests", lambda: {})
    models._verify("mystery", artifact)  # no entry → no-op
    assert artifact.exists()


def test_skip_env_bypasses_verification(tmp_path, monkeypatch):
    artifact = tmp_path / "u2netp.onnx"
    artifact.write_bytes(b"tampered")
    monkeypatch.setattr(models, "_expected_digests", lambda: {"u2netp": "0" * 64})
    monkeypatch.setenv("SNAPGRADE_SKIP_CHECKSUM", "1")
    models._verify("u2netp", artifact)  # bypassed → no raise
    assert artifact.exists()


def test_client_and_host_manifests_agree():
    """The in-repo client manifest must match the sister-repo host manifest."""
    from pathlib import Path

    host = Path("/Users/oindrila/Projects/macos-computer-vision-models/models/manifest.json")
    if not host.exists():
        pytest.skip("sister repo manifest not present")
    host_models = json.loads(host.read_text())["models"]
    client_models = models._expected_digests()
    shared = set(host_models) & set(client_models)
    assert shared, "no overlapping model names between client and host manifests"
    for name in shared:
        assert host_models[name] == client_models[name], f"digest drift for '{name}'"
