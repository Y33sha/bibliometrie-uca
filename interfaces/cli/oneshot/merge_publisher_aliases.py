# STATUS: oneshot (2026-10-25)
"""Fusionne les autres noms d'éditeurs que la fusion automatique ne reconnaît pas (`merge_duplicate_publishers`).

Chaque paire nomme un autre nom et l'éditeur qui l'absorbe : renommage, faute de frappe, nom traduit, ou variante que la comparaison des noms ne rapproche pas. Les marques et les éditeurs rachetés restent distincts. Un nom absent de la base est ignoré. La fusion est celle de l'administration : elle refuse deux membres Crossref distincts et deux revues homonymes aux ISSN différents. Chaque fusion est commitée seule. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.merge_publisher_aliases [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, text

from domain.errors import ConflictError
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from interfaces.api.deps import publisher_service

log = setup_logger("merge_publisher_aliases", os.path.dirname(__file__))

# (autre nom, éditeur qui l'absorbe)
ALIASES: tuple[tuple[str, str], ...] = (
    ("Taylor & Francis", "Informa UK Limited"),
    ("Taylor and Francis", "Informa UK Limited"),
    ("Taylord & Francis", "Informa UK Limited"),
    ("Philadelphia PA: Taylor & Francis", "Informa UK Limited"),
    ("Taylor & Francis: STM, Behavioural Science and Public Health Titles", "Informa UK Limited"),
    ("OpenEdition Journals", "OpenEdition"),
    ("Revues.org", "OpenEdition"),
    ("Cellule MathDoc/CEDRAM", "MathDoc/Centre Mersenne"),
    ("De Gruyter Brill", "Walter de Gruyter"),
    ("American Institute of Physics", "AIP Publishing"),
    ("IEEE-INST ELECTRICAL ELECTRONICS ENGINEERS INC", "Institute of Electrical and Electronics Engineers Inc."),
    ("Thieme Medical Publishers", "Georg Thieme Verlag"),
    ("SPIE Society of Photo-Optical Instrumentation Engineers", "SPIE-Intl Soc Optical Eng"),
    ("SPIE-INT SOC OPTICAL ENGINEERING", "SPIE-Intl Soc Optical Eng"),
    ("NRC Research Press", "Canadian Science Publishing"),
    ("Natl Acad Sciences", "Proceedings of the National Academy of Sciences"),
    ("Faculty of 1000", "F1000 Research Ltd"),
    ("Optical Society of America", "Optica Publishing Group"),
    ("Optical Society of America - OSA Publishing", "Optica Publishing Group"),
    ("OSA", "Optica Publishing Group"),
    ("EUROPEAN MATHEMATICAL SOC-EMS", "European Mathematical Society - EMS - Publishing House GmbH"),
    ("EMS Press", "European Mathematical Society - EMS - Publishing House GmbH"),
    ("European Assoication of Geochemistry", "European Association of Geochemistry"),
    ("Asce-Amer Soc Civil Engineers", "American Society of Civil Engineers"),
    ("American Society of Mechanical Engineers", "ASME International"),
    ("INST MATHEMATICAL STATISTICS-IMS", "Institute of Mathematical Statistics"),
    ("INFORMS", "Institute for Operations Research and the Management Sciences"),
    ("European Association of Geoscientists & Engineers", "EAGE Publications"),
    ("Eksa Editions", "Eska Editions"),
    ("Amer Inst Mathematical Sciences-Aims", "American Institute of Mathematical Sciences"),
    ("Imprensa da Universidade de Coimbra", "Coimbra University Press"),
    ("Polskie Towarzystwo Informatyczne", "Polish Information Processing Society PTI"),
    ("National Institute of Geophysics and Volcanology", "Instituto Nazionale di Geofisica e Vulcanologia, INGV"),
    ("Ist Nazionale Di Geofisica E Vulcanologia", "Instituto Nazionale di Geofisica e Vulcanologia, INGV"),
    ("Begellhouse", "Begell house"),
    ("University of Zaragoza", "Universidad de Zaragoza."),
    ("University of Alicante", "Universidad de Alicante Servicio de Publicaciones"),
    ("University of Valencia", "Universitat de Valencia"),
    ("University of Lodz Press", "Uniwersytet Łódzki"),
    ("Wydawnictwo Uniwersytetu Łódzkiego", "Uniwersytet Łódzki"),
    ("John Paul II Catholic University of Lublin", "Katolicki Uniwersytet Lubelski Jana Pawla II"),
    ("National University of Distance Education", "UNED - Universidad Nacional de Educacion a Distancia"),
    ("Instytut Matematyczny PAN", "Institute of Mathematics, Polish Academy of Sciences"),
    ("Royal Soc London", "The Royal Society"),
    ("MAIK Nauka/Interperiodica", "Pleiades Publishing"),
    ("Eur Centre Dis Prevention & Control", "European Centre for Disease Control and Prevention"),
    ("Edizione Minerva Medica", "Edizioni Minerva Medica"),
    ("Beilstein Institute for the Advancement of Chemical Sciences", "Beilstein Institut"),
    ("SciPost Foundation", "Stichting SciPost"),
    ("SciPost.org", "Stichting SciPost"),
    ("Université de Bourgogne", "Université Bourgogne Europe"),
    ("University of Limoges", "Université de Limoges"),
    ("Europa Edition", "Europa Digital & Publishing"),
    ("Société météorologique de France (Météo France)", "Meteo et Climat, Societe Francaise de la Meteorologie et du Climat"),
    ("Association Française pour la Production Fourragère", "Association Francophone pour les Prairies et les Fourrages"),
    ("Centre de recherche interuniversitaire sur la formation et la profession enseignante", "CRIFPE"),
    ("Q15088586", "Magnolia Press"),
)  # fmt: skip


def publisher_ids(conn: Connection, name: str) -> list[int]:
    """Éditeurs dont le nom est exactement `name`."""
    return list(
        conn.execute(
            text("SELECT id FROM publishers WHERE name = :name ORDER BY id"), {"name": name}
        ).scalars()
    )


def merge_aliases(conn: Connection, *, apply: bool) -> Counter[str]:
    """Fusionne chaque autre nom dans son éditeur, commite chaque fusion si `apply`, et renvoie le décompte des issues."""
    outcomes: Counter[str] = Counter()
    for alias, target_name in ALIASES:
        targets, sources = publisher_ids(conn, target_name), publisher_ids(conn, alias)
        if len(targets) != 1 or not sources:
            outcomes["nom absent ou ambigu"] += 1
            log.info("« %s » → « %s » : nom absent ou ambigu", alias, target_name)
            continue
        for source_id in sources:
            if not apply:
                outcomes["à fusionner"] += 1
                log.info("« %s » (%d) → « %s » (%d)", alias, source_id, target_name, targets[0])
                continue
            try:
                publisher_service(conn).merge_publishers(targets[0], source_id)
            except ConflictError as e:
                conn.rollback()
                outcomes["refusées"] += 1
                log.warning("« %s » → « %s » : %s", alias, target_name, e)
                continue
            conn.commit()
            outcomes["fusionnées"] += 1
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="liste les fusions sans les faire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        outcomes = merge_aliases(conn, apply=not args.dry_run)
    log.info("%s", ", ".join(f"{n} {issue}" for issue, n in sorted(outcomes.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
