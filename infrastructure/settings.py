"""
Configuration du projet bibliometrie-uca.

Settings typés chargés depuis les variables d'environnement ou un fichier
`.env` à la racine du projet (gitignored). En prod, les variables sont
injectées par l'orchestrateur (pm2, systemd, docker).

Usage :
    from infrastructure.settings import settings
    print(settings.db_host)

Les paramètres externalisés dynamiques (périmètres, clés API, credentials
ScanR, collections HAL, années pipeline) sont lus depuis la table `config`
en base via utils.app_config.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from infrastructure import PROJECT_ROOT


class Settings(BaseSettings):
    """Configuration de l'app — lit .env et les variables d'environnement."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore les env vars non déclarées (POSTGRES_*, CORS_ORIGINS, etc.)
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
    db_user: str
    db_password: str

    # ----- Pool de connexions -----
    # Ratio max/min recommandé : ~1:15. Bumper db_pool_max à 50+ si l'API
    # admin charge plusieurs facettes en parallèle et qu'on observe des
    # TimeoutError côté pool. Cf. `.env.example` pour la note opérationnelle.
    db_pool_min: int = 2
    db_pool_max: int = 30

    @property
    def db_args(self) -> dict[str, str | int]:
        """Arguments pour psycopg.connect() / psycopg_pool.ConnectionPool."""
        return {
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
            "host": self.db_host,
            "port": self.db_port,
        }


# pydantic-settings lit les champs required depuis l'environnement / .env ;
# mypy ne le voit pas et les exige comme kwargs explicites.
settings = Settings()  # type: ignore[call-arg]
