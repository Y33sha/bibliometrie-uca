"""
Configuration Docker — lit toutes les valeurs depuis les variables d'environnement.
Copié automatiquement en config/settings.py à l'intérieur du conteneur.
"""

import os

# ----- Authentification admin -----
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_SALT = os.environ.get("ADMIN_SALT", "changeme")
ADMIN_HASH = os.environ.get("ADMIN_HASH", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "uca-biblio-session-key-change-me")

# ----- Base de données -----
DB = {
    "dbname": os.environ.get("DB_NAME", "bibliometrie"),
    "user":   os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host":   os.environ.get("DB_HOST", "db"),
    "port":   int(os.environ.get("DB_PORT", "5432")),
}

# ----- OpenAlex -----
OPENALEX = {
    "email": os.environ.get("OPENALEX_EMAIL", "votre.email@uca.fr"),
    "ror_id": "https://ror.org/01a8ajp46",
    "institution_id": "i198244214",
    "years": [2022, 2023, 2024, 2025],
    "per_page": 200,
    "request_delay": 0.2,
}

# ----- HAL -----
HAL = {
    "portal": "clermont-univ",
    "collections": {
        "ACCEPPT": "ACCePPT",
        "ACTE": "ACTé",
        "AME2P": "AME2P",
        "CELIS": "CELIS",
        "CERDI": "CERDI",
        "CHEC": "CHEC",
        "CHELTER": "CHELTER",
        "CLERMA": "CleRMa",
        "CMH": "CMH",
        "LABCS": "ComSocs",
        "CROC": "CROC",
        "GDEC": "GDEC",
        "GEOLAB": "GEOLAB",
        "GRED": "iGReD",
        "ICC": "ICCF",
        "CERHAC": "IHRIM",
        "IMOST": "IMoST",
        "INSTITUT_PASCAL": "IP",
        "LAMP": "LaMP",
        "LAPSCO": "LAPSCO",
        "LESCORES": "LESCORES",
        "LIMOS": "LIMOS",
        "UMR6620": "LMBP",
        "LMGE": "LMGE",
        "LMV": "LMV",
        "LPC-CLERMONT": "LPCA",
        "LRL": "LRL",
        "M2ISH": "M2iSH",
        "MEDIS": "MEDIS",
        "MSHC": "MSH",
        "ND": "NEURO-DOL",
        "OPGC": "OPGC",
        "PHIER": "PHIER",
        "PIAF": "PIAF",
        "RESSOURCES": "Ressources",
        "TERRITOIRES": "Territoires",
        "UMRF": "UMRF",
        "UNH": "UNH",
    },
    "years": [2022, 2023, 2024, 2025],
    "per_page": 500,
    "request_delay": 0.5,
}

# ----- WoS -----
WOS = {
    "api_key": os.environ.get("WOS_API_KEY", ""),
    "base_url": "https://api.clarivate.com/api/wos",
    "years": [2022, 2023, 2024, 2025, 2026],
    "affiliations": [
        "Univ Clermont Auvergne",
        "CHU Clermont Ferrand",
        "Clermont Auvergne INP",
        "Sigma Clermont",
    ],
    "per_page": 100,
    "request_delay": 1.0,
}
