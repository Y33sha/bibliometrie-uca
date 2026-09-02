"""Sélection de l'implémentation `RawStore` selon `BIBLIO_RAW_STORE_DIR`.

Vide, le réglage laisse le stockage sous `data/raw_store` à la racine du dépôt ; renseigné, il porte le répertoire à employer.
"""

from __future__ import annotations

from pathlib import Path

from infrastructure import PROJECT_ROOT
from infrastructure.raw_store.base import RawStore
from infrastructure.raw_store.local import LocalFileRawStore
from infrastructure.settings import settings

_DEFAULT_LOCAL_DIR = PROJECT_ROOT / "data" / "raw_store"


def get_raw_store(directory: str | Path | None = None) -> RawStore:
    """Retourne le `RawStore` configuré : le répertoire reçu, celui du réglage, ou celui par défaut."""
    racine = directory if directory is not None else settings.biblio_raw_store_dir
    return LocalFileRawStore(Path(racine) if racine else _DEFAULT_LOCAL_DIR)
