"""Sélection de l'implémentation `RawStore` selon `BIBLIO_RAW_STORE_URL`.

- non défini → store local par défaut (`{PROJECT_ROOT}/data/raw_store`) ;
- `file:///chemin/absolu` → `LocalFileRawStore` (chemin résolu cross-platform) ;
- tout autre schéma → `ValueError`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from infrastructure import PROJECT_ROOT
from infrastructure.raw_store.base import RawStore
from infrastructure.raw_store.local import LocalFileRawStore
from infrastructure.settings import settings

_DEFAULT_LOCAL_DIR = PROJECT_ROOT / "data" / "raw_store"


def get_raw_store(url: str | None = None) -> RawStore:
    """Retourne le `RawStore` configuré (`url` explicite, sinon settings/env)."""
    raw_url = settings.biblio_raw_store_url if url is None else url
    if not raw_url:
        return LocalFileRawStore(_DEFAULT_LOCAL_DIR)

    parsed = urlparse(raw_url)
    if parsed.scheme == "file":
        # url2pathname gère le `/C:/...` de Windows comme le `/home/...` Unix.
        return LocalFileRawStore(Path(url2pathname(parsed.path)))
    raise ValueError(f"BIBLIO_RAW_STORE_URL : schéma non supporté ({raw_url!r})")
