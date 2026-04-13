"""Configuration centralisée du logging."""

import io
import logging
import os
import sys


def setup_logger(name: str, log_dir: str) -> logging.Logger:
    """Configure un logger avec sortie console + fichier.

    Crée le répertoire de logs si nécessaire.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}.log")

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # Force UTF-8 sur la console pour éviter les UnicodeEncodeError Windows (cp1252)
    console = logging.StreamHandler(
        stream=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    )
    console.setFormatter(fmt)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[console, file_handler],
    )
    return logging.getLogger(name)
