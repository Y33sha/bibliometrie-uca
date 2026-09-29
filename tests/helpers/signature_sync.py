"""Réglages de synchronisation des signatures pour les tests : empreinte de production, sans resynchronisation forcée."""

from application.pipeline.normalize._authorships_batch import SignatureSyncSettings
from infrastructure.fingerprint import fingerprint

SYNC_SETTINGS = SignatureSyncSettings(fingerprint=fingerprint)
