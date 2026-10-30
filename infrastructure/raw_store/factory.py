"""Construction du `RawStore` configuré par `BIBLIO_RAW_STORE_DIR`.

Le réglage désigne le répertoire de stockage. Vide, il laisse le répertoire par défaut : `data/raw_store` à la racine du dépôt.
"""

from __future__ import annotations

from pathlib import Path

from infrastructure import PROJECT_ROOT
from infrastructure.raw_store.base import RawStore
from infrastructure.raw_store.local import LocalFileRawStore
from infrastructure.settings import settings

_DEFAULT_LOCAL_DIR = PROJECT_ROOT / "data" / "raw_store"


def get_raw_store(directory: str | Path | None = None) -> RawStore:
    """Renvoie le `RawStore` sur le répertoire reçu, à défaut celui du réglage, à défaut celui par défaut."""
    racine = directory if directory is not None else settings.biblio_raw_store_dir
    return LocalFileRawStore(Path(racine) if racine else _DEFAULT_LOCAL_DIR)
