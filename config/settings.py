"""
Configuration du projet bibliometrie-uca.

Settings typés chargés depuis les variables d'environnement ou un fichier
`.env` à la racine du projet (gitignored). En prod, les variables sont
injectées par l'orchestrateur (pm2, systemd, docker).

Usage :
    from config.settings import settings
    print(settings.db_host)

Les paramètres externalisés dynamiques (périmètres, clés API, credentials
ScanR, collections HAL, années pipeline) sont lus depuis la table `config`
en base via utils.app_config.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration de l'app — lit .env et les variables d'environnement."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",   # ignore les env vars non déclarées (POSTGRES_*, CORS_ORIGINS, etc.)
        case_sensitive=False,
    )

    # ----- Authentification admin -----
    # Hash bcrypt : python3 -c 'import bcrypt; print(bcrypt.hashpw(b"MOT_DE_PASSE", bcrypt.gensalt()).decode())'
    # Session secret : python3 -c "import secrets; print(secrets.token_hex(32))"
    admin_user: str = "admin"
    admin_hash: str
    session_secret: str

    # ----- Base de données -----
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "bibliometrie"
    db_user: str = "lalecoz"
    db_password: str

    # ----- Pool de connexions -----
    db_pool_min: int = 2
    db_pool_max: int = 10

    @property
    def db_args(self) -> dict:
        """Arguments pour psycopg2.connect() / ThreadedConnectionPool."""
        return {
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
            "host": self.db_host,
            "port": self.db_port,
        }


settings = Settings()
