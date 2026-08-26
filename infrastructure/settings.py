"""Configuration du projet bibliometrie-uca.

Settings typés chargés depuis les variables d'environnement ou un fichier `.env` à la racine du projet (gitignored). En prod, les variables sont injectées par l'orchestrateur (pm2, systemd, docker).

Usage :
    from infrastructure.settings import settings
    print(settings.db_host)

Les paramètres externalisés dynamiques (périmètres, clés API, credentials ScanR, collections HAL, années pipeline) sont lus depuis la table `config` en base.
"""

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from infrastructure import PROJECT_ROOT


class Settings(BaseSettings):
    """Configuration de l'app — lit .env et les variables d'environnement."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore les env vars non déclarées (POSTGRES_*, FORWARDED_ALLOW_IPS, etc.)
        case_sensitive=False,
    )

    # ----- Authentification admin -----
    # Hash bcrypt : python -c 'import bcrypt; print(bcrypt.hashpw(b"MOT_DE_PASSE", bcrypt.gensalt()).decode())'
    # Session secret : python -c "import secrets; print(secrets.token_hex(32))"
    admin_user: str = "admin"
    admin_hash: str
    session_secret: str

    # ----- Sécurité HTTP -----
    # Cookie de session marqué `Secure` (transmis uniquement sur HTTPS). Vrai par défaut ;
    # passer à false pour un développement local servi en HTTP clair.
    cookie_secure: bool = True
    # Exposition des docs interactives (`/docs`, `/redoc`, `/openapi.json`), qui cartographient
    # toute la surface d'API. Faux par défaut ; activer en développement.
    expose_api_docs: bool = False
    # Origines autorisées à appeler l'API depuis un navigateur, énumérées et séparées par des
    # virgules. Vide → aucune origine tierce, ce qui suffit quand le frontend est servi par
    # l'API elle-même (même origine).
    cors_origins: Annotated[list[str], NoDecode] = []

    # ----- Base de données -----
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "bibliometrie"
    db_user: str
    db_password: str
    # Identité restreinte dont l'API se sert pour se connecter, quand elle est configurée :
    # un rôle limité à la lecture et à l'écriture des données, sans droit sur le schéma.
    # Vide → l'API se connecte comme le reste (migrations, pipeline, scripts), avec
    # l'identité principale.
    db_app_user: str = ""
    db_app_password: str = ""
    # Mode SSL de la connexion (valeurs libpq : disable/prefer/require/verify-ca/verify-full).
    # Vide → défaut du driver. Poser `require` ou `verify-full` dès que la base est déportée
    # (le mot de passe et les données personnelles circulent sinon en clair sur le réseau).
    db_sslmode: str = ""

    # ----- Pool de connexions -----
    # Ratio max/min recommandé : ~1:15. Monter db_pool_max à 50+ si l'API admin charge plusieurs facettes en parallèle et qu'on observe des TimeoutError côté pool. Cf. `.env.example` pour la note opérationnelle.
    db_pool_min: int = 2
    db_pool_max: int = 30

    # ----- Identifiants d'accès aux sources externes -----
    # Une source dont les identifiants manquent est sautée au lancement du pipeline, avec un
    # avertissement, sans interrompre le run.
    openalex_api_key: str = ""
    wos_api_key: str = ""
    scanr_username: str = ""
    scanr_password: str = ""
    # Adresse annoncée aux API qui pratiquent le polite pool. Requise par Crossref, DataCite et
    # Unpaywall ; facultative pour OpenAlex, dont une clé d'API ouvre aussi le polite pool.
    polite_pool_email: str = ""

    # ----- Raw store (payloads bruts hors BDD) -----
    # Vide → store local par défaut (`data/raw_store`). Sinon un `file:///chemin` absolu.
    biblio_raw_store_url: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        """Découpe la liste d'origines et refuse le joker.

        `*` est inconciliable avec les requêtes portant un cookie : le middleware CORS répond alors en renvoyant l'`Origin` de l'appelant, si bien que n'importe quel site autorise ses visiteurs à appeler l'API avec leur session. Le refus tombe au démarrage plutôt qu'à la première requête, où il passerait inaperçu.
        """
        if not isinstance(value, str):
            return value
        origins = [o.strip() for o in value.split(",") if o.strip()]
        if "*" in origins:
            raise ValueError(
                "CORS_ORIGINS n'accepte pas `*` : les appels portent un cookie de session, "
                "et toute origine serait autorisée à s'en servir. Énumérer les origines."
            )
        return origins

    @property
    def db_args(self) -> dict[str, str | int]:
        """Arguments pour psycopg.connect()."""
        return {
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
            "host": self.db_host,
            "port": self.db_port,
        }


# pydantic-settings lit les champs required depuis l'environnement / .env ; mypy ne le voit pas et les exige comme kwargs explicites.
settings = Settings()  # type: ignore[call-arg]
