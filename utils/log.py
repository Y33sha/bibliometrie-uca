"""Configuration centralisée du logging."""

import logging
import os


def setup_logger(name: str, log_dir: str) -> logging.Logger:
    """Configure un logger avec sortie console + fichier.

    Crée le répertoire de logs si nécessaire.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ],
    )
    return logging.getLogger(name)
