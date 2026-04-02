"""
Configuration du projet bibliometrie-uca.
Copier ce fichier vers settings.py et adapter les valeurs.
"""

# ----- Authentification admin -----
# Pour changer le mot de passe :
#   python3 -c "import hashlib; s='VOTRE_SEL'; print(hashlib.sha256((s+'nouveau_mdp').encode()).hexdigest())"
ADMIN_USER = "admin"
ADMIN_SALT = "VOTRE_SEL_ICI"
ADMIN_HASH = "VOTRE_HASH_ICI"
SESSION_SECRET = "uca-biblio-session-key-change-me"  # clé de signature des cookies

# ----- Base de données -----
DB = {
    "dbname": "bibliometrie",
    "user": "postgres",       # à adapter
    "password": "",           # vide si auth peer/ident
    "host": "localhost",
    "port": 5432,
}

# ----- OpenAlex -----
OPENALEX = {
    # Email pour le "polite pool" (meilleur débit, pas de rate limit dur)
    # https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication
    "email": "votre.email@uca.fr",  # à adapter

    # ROR de l'UCA (conservé pour référence)
    "ror_id": "https://ror.org/01a8ajp46",

    # ID institution OpenAlex — utilisé avec le filtre lineage
    # pour capturer UCA + toutes ses composantes/labos
    "institution_id": "i198244214",

    # Années à extraire
    "years": [2022, 2023, 2024, 2025],

    # Nombre de résultats par page (max 200 pour OpenAlex)
    "per_page": 200,

    # Pause entre requêtes (secondes) — le polite pool tolère 10 req/s,
    # mais on reste courtois
    "request_delay": 0.2,
}

# ----- HAL -----
HAL = {
    # Portail global UCA
    "portal": "clermont-univ",

    # Collections HAL par labo (code: label)
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
    "per_page": 500,  # HAL autorise jusqu'à 10000
    "request_delay": 0.5,
}

# ----- WoS -----
WOS = {
    "api_key": "VOTRE_CLE_API_WOS",
    "base_url": "https://api.clarivate.com/api/wos",
    "years": [2022, 2023, 2024, 2025, 2026],
    # Noms OG (Organization-Enhanced) dans WoS
    "affiliations": [
        "Univ Clermont Auvergne",
        "CHU Clermont Ferrand",
        "Clermont Auvergne INP",
        "Sigma Clermont",
    ],
    "per_page": 100,        # max autorisé par l'API WoS
    "request_delay": 1.0,   # 1 req/s (marge de sécurité, WoS instable)
}
