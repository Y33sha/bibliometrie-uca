"""Configuration du projet.

Settings typés chargés depuis les variables d'environnement, le fichier `.env` à la racine du projet (gitignored) et le fichier de l'instance désignée par `BIBLIO_INSTANCE` (cf. `infrastructure/__init__.py`).

Les secrets sont typés `SecretStr` : ils s'affichent `**********`, dans un journal comme dans une trace d'erreur, et se lisent par `.get_secret_value()`.

Les paramètres d'exploitation (périmètres, collections HAL, années couvertes) sont dans la table `config`.
"""

from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from infrastructure import ENV_FILES


class Settings(BaseSettings):
    """Réglages lus dans les fichiers d'environnement et les variables d'environnement."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",  # Les variables d'environnement non déclarées (POSTGRES_*, FORWARDED_ALLOW_IPS…) sont ignorées.
        case_sensitive=False,
    )

    # ----- Authentification admin -----
    # `admin_hash` et `session_secret` sont exigés par l'API seulement, au démarrage (`interfaces.api.session.check_auth_config`). Commandes de génération dans `.env.example`.
    admin_user: str = "admin"
    admin_hash: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")

    # ----- Sécurité HTTP -----
    # Cookie de session réservé à HTTPS.
    cookie_secure: bool = True
    # Docs interactives (`/docs`, `/redoc`, `/openapi.json`).
    expose_api_docs: bool = False
    # Origines autorisées à appeler l'API depuis un navigateur, séparées par des virgules. Vide quand l'API sert le frontend.
    cors_origins: Annotated[list[str], NoDecode] = []

    # ----- Serveur de développement -----
    # Port de l'API lancée par `start.sh`. Le proxy de vite en déduit sa cible (cf. `interfaces/frontend/vite.config.ts`).
    api_port: int = 8000

    # ----- Base de données -----
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "bibliometrie"
    # Un rôle PostgreSQL par processus (cf. `infrastructure/db/roles.sql`). Une connexion dont le rôle est vide est refusée (`infrastructure.db.engine.db_url`).
    #
    # Propriétaire du schéma, pour les migrations seulement.
    db_owner_user: str = ""
    db_owner_password: SecretStr = SecretStr("")
    # API : lecture, et écriture sur les tables que ses routes d'administration modifient.
    db_app_user: str = ""
    db_app_password: SecretStr = SecretStr("")
    # Pipeline et scripts en ligne de commande : écriture sur les données, entretien des vues matérialisées et des statistiques, aucun droit sur le schéma.
    db_pipeline_user: str = ""
    db_pipeline_password: SecretStr = SecretStr("")
    # Mode SSL de libpq. Vide : `prefer`, chiffrement sans vérification du certificat. `verify-full` authentifie le serveur.
    db_sslmode: str = ""

    # Décalage maximal d'une lecture paginée : une page profonde fait trier à la base tout le résultat. La valeur dépasse le plus gros ensemble servi.
    max_pagination_offset: int = 500_000

    # Exports simultanés. Un export compose sa réponse en mémoire : 59 Mo sans filtre pour 61 877 publications (août 2026), soit environ 300 Mo pour cinq exports, sur les 2 Go du conteneur.
    max_concurrent_exports: int = 5

    # ----- Concurrence de l'API -----
    # Taille du threadpool d'anyio, qui exécute les routes synchrones ; fixée au démarrage de l'API. `db_pool_max` doit la couvrir.
    api_threadpool_size: int = 40
    # Durée maximale d'une requête SQL servant une lecture de l'API (GET), en secondes. L'export complet des publications prend une dizaine de secondes.
    api_read_statement_timeout_s: int = 30

    # ----- Pool de connexions -----
    # `db_pool_min` connexions toujours ouvertes ; les suivantes, jusqu'à `db_pool_max`, s'ouvrent à la demande. `db_pool_max` égale `api_threadpool_size` : chaque thread de l'API trouve une connexion.
    db_pool_min: int = 2
    db_pool_max: int = 40

    # ----- Identifiants d'accès aux sources externes -----
    # Une source sans identifiants est sautée au lancement du pipeline, avec un avertissement.
    openalex_api_key: SecretStr = SecretStr("")
    wos_api_key: SecretStr = SecretStr("")
    scanr_username: str = ""
    scanr_password: SecretStr = SecretStr("")
    # Adresse annoncée aux API à polite pool : exigée par Crossref, DataCite et Unpaywall ; pour OpenAlex, à défaut de clé d'API.
    polite_pool_email: str = ""

    # ----- Raw store (réponses brutes des sources) -----
    # Répertoire de l'archive, quand le pipeline tourne avec `--raw-store`. Vide : `data/raw_store` à la racine du dépôt.
    biblio_raw_store_dir: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        """Découpe la liste d'origines et refuse le joker au démarrage.

        Avec `*` et des requêtes à cookie, le middleware CORS renvoie l'`Origin` de l'appelant : tout site pourrait appeler l'API avec la session de ses visiteurs.
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


settings = Settings()
