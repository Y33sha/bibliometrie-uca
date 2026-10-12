"""Réglages de synchronisation des signatures pour les tests : empreinte de production, sans resynchronisation forcée."""

from pipeline.ingestion.common.fingerprint import fingerprint
from pipeline.ingestion.common.signatures import SignatureSyncSettings

SYNC_SETTINGS = SignatureSyncSettings(fingerprint=fingerprint)
