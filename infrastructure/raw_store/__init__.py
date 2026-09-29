"""Store de payloads bruts hors BDD (cf. `base.RawStore`)."""

from infrastructure.raw_store.base import RawStore, UnreadablePayloadError
from infrastructure.raw_store.factory import get_raw_store
from infrastructure.raw_store.local import LocalFileRawStore
from infrastructure.raw_store.null import NullRawStore

__all__ = [
    "LocalFileRawStore",
    "NullRawStore",
    "RawStore",
    "UnreadablePayloadError",
    "get_raw_store",
]
