"""
Configuration du projet bibliometrie-uca.
Copier ce fichier vers settings.py et adapter les valeurs.

Les paramètres externalisés (périmètres, clés API, credentials ScanR,
collections HAL, années pipeline, etc.) sont stockés dans la table `config`
en base, gérée via l'interface d'admin.
"""

import os as _os

# ----- Authentification admin -----
# Pour générer un hash bcrypt :
#   python3 -c 'import bcrypt; print(bcrypt.hashpw(b"nouveau_mdp", bcrypt.gensalt()).decode())'
# Pour générer un session secret :
#   python3 -c "import secrets; print(secrets.token_hex(32))"
ADMIN_USER = _os.environ.get("ADMIN_USER", "admin")
ADMIN_HASH = _os.environ.get("ADMIN_HASH", "VOTRE_HASH_BCRYPT_ICI")
SESSION_SECRET = _os.environ.get("SESSION_SECRET", "change-me-with-secrets-token-hex-32")

# ----- Base de données -----
DB = {
    "dbname": "bibliometrie",
    "user": "postgres",                               # à adapter
    "password": _os.environ.get("DB_PASSWORD", ""),   # vide si auth peer/ident
    "host": "localhost",
    "port": 5432,
}
DB_POOL_MIN = 1
DB_POOL_MAX = 5
