"""Réglages de synchronisation des signatures pour les tests : empreinte de production, sans resynchronisation forcée."""

from pipeline.sources.fingerprint import fingerprint
from pipeline.sources.signatures import SignatureSyncSettings

SYNC_SETTINGS = SignatureSyncSettings(fingerprint=fingerprint)
