# STATUS: oneshot (2026-06-19)
"""Ajoute des `place_name_forms` depuis les annotations entre crochets des adresses.

Beaucoup d'adresses portent une annotation de lieu entre crochets — fiable mais
absente de `place_name_forms`, donc inexploitée par la détection pays (phase
`countries`). Ex. « … [Genève] », « … [CHU Toulouse] », « … [Madrid] ».

On extrait le contenu des crochets, on garde les formes **absentes** de
`place_name_forms`, **fréquentes** (≥ `MIN_OCC`) et au **pays homogène** : le pays
est INFÉRÉ du consensus des adresses déjà résolues contenant la forme
(≥ `MIN_RESOLVED` adresses, part du pays majoritaire ≥ `MIN_CONSENSUS`).

Exclusions : bruit (dates, « en ligne », emails), **noms de pays** (relèvent de
`kind='country'`, matchés autrement), et `EXCLUDE` — formes ambiguës où le crochet
ne fixe pas le pays : « rome » (Rome NY ; École française de Rome = fr), « nice »
(adjectif anglais)…

`kind` posé par heuristique mot-clé (institution vs city) ; la détection est
insensible au `kind` tant qu'il est ≠ 'country'. À enchaîner avec un run de la
phase `countries` (les nouvelles formes ne résolvent que des adresses sans pays,
aucune résolution existante n'est invalidée — pas de nullage requis).

Usage :
    python -m interfaces.cli.oneshot.add_place_names_from_brackets              # applique
    python -m interfaces.cli.oneshot.add_place_names_from_brackets --dry-run    # liste seulement
"""

import argparse
import re
from collections import Counter, defaultdict

from sqlalchemy import select, text

from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.tables import addresses
from infrastructure.observability.log import setup_logger

logger = setup_logger("add_place_names_from_brackets", "processing/logs")

MIN_OCC = 5  # occurrences min de la forme dans les crochets
MIN_RESOLVED = 3  # adresses résolues min pour inférer le pays
MIN_CONSENSUS = 0.85  # part du pays majoritaire parmi les résolues

_BRACKET = re.compile(r"\[([^\]]+)\]")
_DATE = re.compile(r"\b\d{4}\b")

# Bruit non géographique fréquent dans les crochets.
NOISE = {"en ligne", "email protected", "at", "virtual", "online", "visio", "by zoom", "web"}

# Noms de pays : relèvent de kind='country' (détection en fin de segment), pas city/institution.
COUNTRY_WORDS = {
    "france",
    "spain",
    "espana",
    "brazil",
    "brasil",
    "bresil",
    "italy",
    "italia",
    "germany",
    "deutschland",
    "allemagne",
    "portugal",
    "japan",
    "japon",
    "china",
    "chine",
    "usa",
    "uk",
    "switzerland",
    "suisse",
    "belgium",
    "belgique",
    "canada",
    "norway",
    "norvege",
    "denmark",
    "danemark",
    "sweden",
    "suede",
    "netherlands",
    "pays bas",
    "morocco",
    "maroc",
    "tunisia",
    "tunisie",
    "algeria",
    "algerie",
}

# Formes ambiguës où le crochet ne fixe pas le pays de façon fiable (à compléter
# au vu du dry-run). `rome` : Rome NY + École française de Rome (fr) ; `nice` :
# adjectif anglais.
EXCLUDE = {"rome", "nice", "tours", "laval", "nancy", "columbia", "as", "io"}

# Au-delà, la « forme » est un fragment d'adresse entier (ex. « associated with
# … university … usa »), pas un nom de lieu — inutile et bruyant.
MAX_WORDS = 6

# Mots-clés indiquant une institution (sinon : city).
_INSTITUTION_KW = {
    "chu",
    "chru",
    "chr",
    "hopital",
    "hospital",
    "universite",
    "university",
    "institut",
    "institute",
    "ecole",
    "school",
    "centre",
    "center",
    "faculte",
    "faculty",
    "clinique",
    "clinic",
    "laboratoire",
    "college",
    "hcl",
    "hegp",
    "aphp",
    "ap hp",
}


def _kind(form: str) -> str:
    return "institution" if set(form.split()) & _INSTITUTION_KW else "city"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Liste sans insérer.")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        existing = {
            r.form_normalized
            for r in conn.execute(text("SELECT form_normalized FROM place_name_forms"))
        }
        rows = conn.execute(
            select(addresses.c.raw_text, addresses.c.countries).where(
                addresses.c.raw_text.op("~")(r"\[[^\]]+\]")
            )
        ).all()

        total: Counter[str] = Counter()
        per_country: dict[str, Counter[str]] = defaultdict(Counter)
        for r in rows:
            for raw in _BRACKET.findall(r.raw_text):
                form = normalize_text(raw)
                if (
                    not form
                    or len(form) < 3
                    or len(form.split()) > MAX_WORDS
                    or form.isdigit()
                    or _DATE.search(form)
                    or form in NOISE
                    or form in COUNTRY_WORDS
                    or form in EXCLUDE
                    or form in existing
                ):
                    continue
                total[form] += 1
                for iso in r.countries or ():
                    per_country[form][iso] += 1

        candidates: list[tuple[str, str, str]] = []  # (form, iso, kind)
        for form, occ in total.items():
            if occ < MIN_OCC:
                continue
            cc = per_country[form]
            n = sum(cc.values())
            if n < MIN_RESOLVED:
                continue
            iso, top = cc.most_common(1)[0]
            if top / n >= MIN_CONSENSUS:
                candidates.append((form, iso, _kind(form)))

        candidates.sort(key=lambda x: (x[1], x[0]))
        logger.info(
            "%d formes-crochets à ajouter (consensus pays ≥ %.0f%%)",
            len(candidates),
            MIN_CONSENSUS * 100,
        )
        for form, iso, kind in candidates:
            logger.info("  [%s] %-40s (%s, occ=%d)", iso, form, kind, total[form])

        if args.dry_run:
            logger.info("DRY-RUN — lancer sans --dry-run pour insérer.")
            return

        inserted = 0
        for form, iso, kind in candidates:
            inserted += conn.execute(
                text(
                    "INSERT INTO place_name_forms (form_normalized, iso_code, kind) "
                    "VALUES (:f, :i, :k) ON CONFLICT (form_normalized) DO NOTHING"
                ),
                {"f": form, "i": iso, "k": kind},
            ).rowcount
        conn.commit()
        logger.info("✓ %d formes insérées dans place_name_forms", inserted)
        logger.info("→ relancer la phase `countries` pour encaisser les nouvelles résolutions.")


if __name__ == "__main__":
    main()
