# STATUS: recurring (dev)
"""Outils en ligne de commande de PostgreSQL, lancés sous le propriétaire du schéma."""

import glob
import os
import shutil

from infrastructure.settings import settings


def resolve_pg_tool(name: str) -> str:
    """Localise l'exécutable PostgreSQL `name` (`pg_dump`, `psql`…).

    Ordre : variable d'environnement portant le nom en majuscules (`PG_DUMP`, `PSQL` : chemin complet), puis le `PATH`, puis les dossiers d'installation PostgreSQL usuels sous Windows, où les binaires sont posés hors `PATH`.
    """
    variable = name.upper()
    env = os.environ.get(variable)
    if env:
        return env
    found = shutil.which(name)
    if found:
        return found
    candidates = sorted(glob.glob(rf"C:\Program Files\PostgreSQL\*\bin\{name}.exe"), reverse=True)
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        f"{name} introuvable : ajoutez le dossier bin de PostgreSQL au PATH, "
        f"ou définissez la variable d'environnement {variable} (chemin complet de {name}.exe)."
    )


def owner_connection_args() -> list[str]:
    """Arguments de connexion au serveur sous le propriétaire du schéma, sans la base visée."""
    return ["-U", settings.db_owner_user, "-h", settings.db_host, "-p", str(settings.db_port)]


def owner_env() -> dict[str, str]:
    """Environnement du processus, complété du mot de passe du propriétaire et du mode SSL."""
    env = {**os.environ, "PGPASSWORD": settings.db_owner_password.get_secret_value()}
    if settings.db_sslmode:
        env["PGSSLMODE"] = settings.db_sslmode
    return env
