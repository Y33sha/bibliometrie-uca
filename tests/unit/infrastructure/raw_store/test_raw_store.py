"""Tests `RawStore` — implémentation locale + factory."""

import gzip

import pytest

from infrastructure.raw_store.factory import get_raw_store
from infrastructure.raw_store.local import LocalFileRawStore


class TestLocalFileRawStore:
    def test_put_get_roundtrip(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        payload = b'{"title": "Etude", "n": 1}'
        store.put("hal", "hal-04123", payload)
        assert store.get("hal", "hal-04123") == payload

    def test_payload_is_gzipped_on_disk(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        store.put("hal", "hal-1", b'{"x": 1}')
        target = tmp_path / "hal" / "hal-1.json.gz"
        assert target.is_file()
        # En-tête gzip (magic 0x1f 0x8b) → le fichier est bien compressé.
        assert target.read_bytes()[:2] == b"\x1f\x8b"
        with gzip.open(target, "rb") as f:
            assert f.read() == b'{"x": 1}'

    def test_overwrite(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        store.put("hal", "hal-1", b"v1")
        store.put("hal", "hal-1", b"v2")
        assert store.get("hal", "hal-1") == b"v2"

    def test_exists(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        assert store.exists("hal", "hal-1") is False
        store.put("hal", "hal-1", b"{}")
        assert store.exists("hal", "hal-1") is True

    def test_get_missing_raises_keyerror(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        with pytest.raises(KeyError):
            store.get("hal", "absent")

    def test_unsafe_source_ids_roundtrip(self, tmp_path):
        """Les `/` (ScanR) et `:` (WoS) sont URL-encodés puis décodés."""
        store = LocalFileRawStore(tmp_path)
        for source, sid in (("scanr", "doi10.1002/abc"), ("wos", "WOS:000123456")):
            store.put(source, sid, b"{}")
            assert store.exists(source, sid) is True
            assert store.get(source, sid) == b"{}"

    def test_iter_keys_returns_decoded_ids(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        store.put("scanr", "doi10.1002/abc", b"{}")
        store.put("scanr", "plain-id", b"{}")
        store.put("hal", "hal-1", b"{}")  # autre source : exclue
        assert set(store.iter_keys("scanr")) == {"doi10.1002/abc", "plain-id"}

    def test_iter_keys_empty_when_source_absent(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        assert list(store.iter_keys("hal")) == []

    def test_delete_removes_payload(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        store.put("hal", "hal-1", b"{}")
        assert store.delete("hal", "hal-1") is True
        assert store.exists("hal", "hal-1") is False

    def test_delete_absent_is_idempotent(self, tmp_path):
        store = LocalFileRawStore(tmp_path)
        assert store.delete("hal", "absent") is False

    def test_delete_unsafe_source_id(self, tmp_path):
        """La suppression décode la même clé que `put` (ids ScanR avec `/`)."""
        store = LocalFileRawStore(tmp_path)
        store.put("scanr", "doi10.1002/abc", b"{}")
        assert store.delete("scanr", "doi10.1002/abc") is True
        assert store.exists("scanr", "doi10.1002/abc") is False


class TestFactory:
    def test_file_url_builds_local_store(self, tmp_path):
        store = get_raw_store(url=tmp_path.as_uri())
        assert isinstance(store, LocalFileRawStore)
        store.put("hal", "hal-1", b"ok")
        assert (tmp_path / "hal" / "hal-1.json.gz").is_file()

    def test_empty_url_uses_default_local_store(self):
        assert isinstance(get_raw_store(url=""), LocalFileRawStore)

    def test_unknown_scheme_raises(self):
        with pytest.raises(ValueError, match="non supporté"):
            get_raw_store(url="ftp://host/path")
