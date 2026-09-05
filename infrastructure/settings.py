"""Configuration du projet bibliometrie-uca.

Settings typés chargés depuis les variables d'environnement ou un fichier `.env` à la racine du projet (gitignored). En prod, les variables sont injectées par l'orchestrateur (pm2, systemd, docker).

Usage :
    from infrastructure.settings import settings
    print(settings.db_host)

Les valeurs secrètes sont typées `SecretStr` : leur représentation et leur sérialisation rendent `**********`, et la valeur se lit par `.get_secret_value()`. Un relevé de la configuration, une trace d'erreur ou un journal qui traverserait l'objet ne les expose donc pas.

Les paramètres d'exploitation externalisés (périmètres, collections HAL, années couvertes) sont lus depuis la table `config` en base. Les identifiants d'accès aux sources, eux, sont des secrets : ils viennent de l'environnement comme les autres.
"""

from typing import Annotated

from pydantic import SecretStr, field_validator
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
    # Exigés du processus qui sert l'API, et de lui seul : le pipeline et les scripts de
    # maintenance partagent cette configuration sans jamais ouvrir de session. Le contrôle vit
    # donc au démarrage de l'API (`interfaces.api.session.check_auth_config`).
    admin_user: str = "admin"
    admin_hash: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")

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
    # Trois identités de connexion, une par processus (cf. `infrastructure/db/roles.sql`).
    # Chacune est exigée de la connexion qui la demande : vide, cette connexion est refusée
    # (cf. `infrastructure.db.engine.db_url`) plutôt que repliée en silence sur une autre.
    #
    # Propriétaire du schéma. Les migrations s'en servent, et elles seules : elles sont seules
    # à modifier la structure. Aucun processus qui tourne n'a à la porter.
    db_owner_user: str = ""
    db_owner_password: SecretStr = SecretStr("")
    # Identité de l'API : lecture, et écriture sur les seules tables que ses points d'entrée
    # d'administration modifient.
    db_app_user: str = ""
    db_app_password: SecretStr = SecretStr("")
    # Identité du pipeline et des scripts en ligne de commande : écriture sur les données,
    # entretien des vues matérialisées et des statistiques, aucun droit sur le schéma.
    db_pipeline_user: str = ""
    db_pipeline_password: SecretStr = SecretStr("")
    # Mode SSL de la connexion (valeurs libpq : disable/prefer/require/verify-ca/verify-full).
    # Vide → défaut du driver, soit `prefer` : chiffré si le serveur le propose, certificat non
    # vérifié. `require` impose le chiffrement sans authentifier le serveur pour autant. Poser
    # `verify-full` dès que la base est déportée : c'est la seule valeur qui écarte une
    # interception, en vérifiant la chaîne du certificat et le nom d'hôte.
    db_sslmode: str = ""

    # Plafond du décalage qu'une lecture paginée peut demander. Le coût d'une page profonde
    # tient au produit du rang par la taille de page : sans borne, un rang arbitrairement grand
    # fait trier à la base l'ensemble du résultat pour n'en rendre aucune ligne. La valeur passe
    # au-delà du plus gros ensemble servi ; la relever est le geste à faire le jour où un
    # ensemble la dépasse, la marche à suivre restant de filtrer pour rapprocher les lignes
    # visées du début du résultat.
    max_pagination_offset: int = 500_000

    # Nombre d'exports menés de front. Un export compose sa réponse en mémoire avant de l'envoyer :
    # ce plafond borne ce que le processus porte à un instant donné, là où le plafond de lignes
    # borne le coût d'un export et celui de fréquence le coût d'une rafale venue d'un même client.
    #
    # La valeur se dimensionne sur le coût mesuré d'un export sans filtre — 59 Mo pour les 61 877
    # publications d'août 2026 — rapporté à la mémoire du conteneur. À ce compte, cinq exports
    # simultanés occupent de l'ordre de 300 Mo sur les deux gigaoctets qu'il porte. Une croissance
    # du corpus déplace ce calcul : le plafond de lignes en donne la borne haute, et l'atteindre
    # multiplierait par huit le coût d'un export.
    max_concurrent_exports: int = 5

    # ----- Concurrence de l'API -----
    # Les routes sont synchrones : FastAPI les exécute dans le threadpool d'anyio, dont le
    # lifespan de l'API fixe la taille à cette valeur. `db_pool_max` doit la couvrir, faute de
    # quoi des threads attendent une connexion.
    api_threadpool_size: int = 40

    # ----- Pool de connexions -----
    # Ratio max/min recommandé : ~1:15. Monter db_pool_max à 50+ si l'API admin charge plusieurs facettes en parallèle et qu'on observe des TimeoutError côté pool. Cf. `.env.example` pour la note opérationnelle.
    db_pool_min: int = 2
    db_pool_max: int = 30

    # ----- Identifiants d'accès aux sources externes -----
    # Une source dont les identifiants manquent est sautée au lancement du pipeline, avec un
    # avertissement, sans interrompre le run.
    openalex_api_key: SecretStr = SecretStr("")
    wos_api_key: SecretStr = SecretStr("")
    scanr_username: str = ""
    scanr_password: SecretStr = SecretStr("")
    # Adresse annoncée aux API qui pratiquent le polite pool. Requise par Crossref, DataCite et
    # Unpaywall ; facultative pour OpenAlex, dont une clé d'API ouvre aussi le polite pool.
    polite_pool_email: str = ""

    # ----- Raw store (payloads bruts hors BDD) -----
    # Répertoire où le pipeline archive les réponses des sources. Vide → `data/raw_store` à la
    # racine du dépôt. Le pipeline de production s'exécute sans archivage (`--no-raw-store`).
    biblio_raw_store_dir: str = ""

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


# pydantic-settings lit les champs required depuis l'environnement / .env ; mypy ne le voit pas et les exige comme kwargs explicites.
settings = Settings()  # type: ignore[call-arg]
