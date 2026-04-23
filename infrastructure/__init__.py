from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Charge `.env` dans os.environ pour que les variables non déclarées dans
# `Settings` (LOG_TO_FILE, LOG_FORMAT, CORS_ORIGINS, ...) soient visibles
# via `os.environ.get(...)`. `override=False` (défaut) : les vars injectées
# par l'orchestrateur en prod (pm2, systemd, docker) restent prioritaires.
load_dotenv(PROJECT_ROOT / ".env")
