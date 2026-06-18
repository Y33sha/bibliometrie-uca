"""Implémentation `RawStore` sur le système de fichiers local (dev).

Layout : `{root}/{source}/{source_id_url_encoded}.json.gz`. Le `source_id` est
URL-encodé (`quote(safe="")`) pour neutraliser les caractères non sûrs en
système de fichiers (`/` des ids ScanR, `:` des ids WoS). Payload gzippé à
l'écriture, décompressé à la lecture — transparent pour l'appelant (`put`/`get`
manipulent des bytes JSON bruts).
"""

from __future__ import annotations

import gzip
import urllib.parse
from collections.abc import Iterator
from pathlib import Path

_SUFFIX = ".json.gz"


class LocalFileRawStore:
    """`RawStore` sur disque local, sous `root_dir`."""

    def __init__(self, root_dir: Path) -> None:
        self._root = Path(root_dir)

    def _path(self, source: str, source_id: str) -> Path:
        safe_id = urllib.parse.quote(source_id, safe="")
        return self._root / source / f"{safe_id}{_SUFFIX}"

    def put(self, source: str, source_id: str, payload: bytes) -> None:
        path = self._path(source, source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wb") as f:
            f.write(payload)

    def get(self, source: str, source_id: str) -> bytes:
        try:
            with gzip.open(self._path(source, source_id), "rb") as f:
                return f.read()
        except FileNotFoundError as e:
            raise KeyError(f"{source}/{source_id}") from e

    def exists(self, source: str, source_id: str) -> bool:
        return self._path(source, source_id).is_file()

    def delete(self, source: str, source_id: str) -> bool:
        path = self._path(source, source_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def iter_keys(self, source: str) -> Iterator[str]:
        source_dir = self._root / source
        if not source_dir.is_dir():
            return
        for path in source_dir.glob(f"*{_SUFFIX}"):
            yield urllib.parse.unquote(path.name[: -len(_SUFFIX)])
