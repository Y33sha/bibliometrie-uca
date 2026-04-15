"""Configuration centralisée du logging."""

import io
import logging
import os
import sys


def setup_logger(name: str, log_dir: str) -> logging.Logger:
    """Configure un logger avec sortie console + fichier.

    Crée le répertoire de logs si nécessaire.
    Configure uniquement le logger nommé (pas le root logger).
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}.log")

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Éviter les doublons si le logger est configuré plusieurs fois
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # Force UTF-8 sur la console pour éviter les UnicodeEncodeError Windows (cp1252)
    # On wrape stdout.buffer sans en prendre ownership (line_buffering pour flush immédiat)
    utf8_stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    utf8_stream.close = lambda: None  # Empêcher la fermeture de stdout.buffer
    console = logging.StreamHandler(stream=utf8_stream)
    console.setFormatter(fmt)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger
