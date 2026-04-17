"""
Configuration du projet bibliometrie-uca.

Toutes les valeurs sont lues depuis les variables d'environnement.
python-dotenv charge automatiquement un fichier `.env` à la racine du projet
(gitignored) au démarrage. En prod, les variables sont injectées par
l'orchestrateur (pm2, systemd, docker).

Les paramètres externalisés dynamiques (périmètres, clés API, credentials
ScanR, collections HAL, années pipeline) sont lus depuis la table `config`
en base via utils.app_config.
"""

import os as _os
from pathlib import Path as _Path

from dotenv import load_dotenv as _load_dotenv

# Charge .env à la racine du projet (sans écraser les env vars déjà définies)
_load_dotenv(_Path(__file__).resolve().parent.parent / ".env")

# ----- Authentification admin -----
# Hash généré avec : python3 -c 'import bcrypt; print(bcrypt.hashpw(b"MOT_DE_PASSE", bcrypt.gensalt()).decode())'
# Session secret : python3 -c "import secrets; print(secrets.token_hex(32))"
ADMIN_USER = _os.environ.get("ADMIN_USER", "admin")
ADMIN_HASH = _os.environ.get("ADMIN_HASH", "")
SESSION_SECRET = _os.environ.get("SESSION_SECRET", "")

# ----- Base de données -----
DB = {
    "dbname":   _os.environ.get("DB_NAME", "bibliometrie"),
    "user":     _os.environ.get("DB_USER", "lalecoz"),
    "password": _os.environ.get("DB_PASSWORD", ""),
    "host":     _os.environ.get("DB_HOST", "localhost"),
    "port":     int(_os.environ.get("DB_PORT", "5432")),
}

DB_POOL_MIN = int(_os.environ.get("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(_os.environ.get("DB_POOL_MAX", "10"))
