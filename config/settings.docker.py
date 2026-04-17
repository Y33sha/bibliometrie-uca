"""
Configuration Docker — lit toutes les valeurs depuis les variables d'environnement.
Copié automatiquement en config/settings.py à l'intérieur du conteneur.

Les paramètres externalisés (périmètres, clés API, credentials ScanR,
collections HAL, années pipeline, etc.) sont lus depuis la table `config`
en base via utils.app_config.
"""

import os

# ----- Authentification admin -----
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_HASH = os.environ.get("ADMIN_HASH", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "uca-biblio-session-key-change-me")

# ----- Base de données -----
DB = {
    "dbname":   os.environ.get("DB_NAME", "bibliometrie"),
    "user":     os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host":     os.environ.get("DB_HOST", "db"),
    "port":     int(os.environ.get("DB_PORT", "5432")),
}
DB_POOL_MIN = 1
DB_POOL_MAX = 5
