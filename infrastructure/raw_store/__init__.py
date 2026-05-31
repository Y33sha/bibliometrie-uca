"""Store de payloads bruts hors BDD (cf. `base.RawStore`)."""

from infrastructure.raw_store.base import RawStore
from infrastructure.raw_store.factory import get_raw_store
from infrastructure.raw_store.local import LocalFileRawStore

__all__ = ["LocalFileRawStore", "RawStore", "get_raw_store"]
