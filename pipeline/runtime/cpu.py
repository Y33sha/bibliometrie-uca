"""Processeurs disponibles pour le pipeline."""

import math
import os
from pathlib import Path

# Quota de processeur du cgroup v2 : « quota période » en microsecondes, ou « max » sans quota.
CGROUP_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")


def available_cpus(cpu_max: Path = CGROUP_CPU_MAX) -> int:
    """Renvoie le nombre de processeurs du processus, plafonné par l'éventuel quota du conteneur (`cpus` de docker compose)."""
    cpus = os.process_cpu_count() or 1
    try:
        quota, period = cpu_max.read_text().split()
    except OSError, ValueError:
        return cpus
    if quota == "max":
        return cpus
    return max(1, min(cpus, math.ceil(int(quota) / int(period))))
