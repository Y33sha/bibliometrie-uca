# STATUS: oneshot (2026-05-29)
"""Cleanup des sujets OpenAlex aberrants par vote d'arbitres haut niveau.

Bootstrap transitoire pour nettoyer le bruit grossier des topics OpenAlex
avant l'introduction de la couche sémantique Specter2 — cf. fiche chantier
`docs/chantiers/METIER_sujets-qualite.md`.

Mécanisme : pour chaque publication avec ≥2 domains OpenAlex (level 0)
attestés, on calcule le "support arbitre" de chaque domain via :

- les sujets des autres `source_publications` (HAL `hal_domain`, WoS
  `wos_subject`, theses `theses_discipline`) mappés via `_ARBITRE_MAPPING`
  ci-dessous (multi-affectation autorisée pour les labels ambigus, ex.
  `Neurosciences` → {health, life}) ;
- le journal DOAJ : `journals.doaj_payload->>'Subjects'` (premier niveau
  LCC, ex. `Medicine`, `Science: Biology`), mappé via les patterns
  `_DOAJ_PATTERN_SQL` ci-dessous.

Un domain est rejeté sur une publi si son support arbitre vaut 0 ET
qu'au moins un autre domain de la publi a un support > 0. Le rejet
entraîne en cascade le rejet de tous les descendants OpenAlex de la
branche (field/subfield/topic) sur cette publication, via la chaîne
`parent` portée par `subjects.ontologies.openalex_topic.parent`.

À chaque run, les rejets précédents sont d'abord remis à FALSE (le
script est l'unique source de rejets pour le moment ; quand une curation
manuelle sera ajoutée côté admin, ce reset devra être affiné).

Usage :
    python -m interfaces.cli.oneshot.cleanup_oa_subjects [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("cleanup_oa_subjects", os.path.dirname(__file__))


# (ontology_key, source_label, oa_domain_code)
# Multi-affectation : un label peut peser pour plusieurs domains OA quand
# l'ambiguïté est inhérente (ex. `Neurosciences` → health + life).
_ARBITRE_MAPPING: list[tuple[str, str, str]] = [
    # hal_domain
    ("hal_domain", "Sciences de l'Homme et Société", "social"),
    ("hal_domain", "Sciences du Vivant", "life"),
    ("hal_domain", "Médecine humaine et pathologie", "health"),
    ("hal_domain", "Informatique", "physical"),
    ("hal_domain", "Physique", "physical"),
    ("hal_domain", "Littératures", "social"),
    ("hal_domain", "Chimie", "physical"),
    ("hal_domain", "Sciences de l'ingénieur", "physical"),
    ("hal_domain", "Sciences de l'environnement", "life"),
    ("hal_domain", "Sciences de l'environnement", "physical"),
    ("hal_domain", "Education", "social"),
    ("hal_domain", "Physique des Hautes Energies - Expérience", "physical"),
    ("hal_domain", "Planète et Univers", "physical"),
    ("hal_domain", "Economies et finances", "social"),
    ("hal_domain", "Neurosciences", "health"),
    ("hal_domain", "Neurosciences", "life"),
    ("hal_domain", "Sciences de la Terre", "physical"),
    ("hal_domain", "Sciences cognitives", "social"),
    ("hal_domain", "Sciences cognitives", "health"),
    ("hal_domain", "Biologie végétale", "life"),
    ("hal_domain", "Géographie", "social"),
    ("hal_domain", "Géographie", "physical"),
    ("hal_domain", "Santé publique et épidémiologie", "health"),
    ("hal_domain", "Alimentation et Nutrition", "life"),
    ("hal_domain", "Alimentation et Nutrition", "health"),
    ("hal_domain", "Sciences agricoles", "life"),
    ("hal_domain", "Musique, musicologie et arts de la scène", "social"),
    ("hal_domain", "Sciences pharmaceutiques", "health"),
    ("hal_domain", "Microbiologie et Parasitologie", "life"),
    ("hal_domain", "Biochimie, Biologie Moléculaire", "life"),
    ("hal_domain", "Gestion et management", "social"),
    ("hal_domain", "Archéologie et Préhistoire", "social"),
    ("hal_domain", "Physique Nucléaire Expérimentale", "physical"),
    ("hal_domain", "Machine Learning", "physical"),
    ("hal_domain", "Ecologie, Environnement", "life"),
    ("hal_domain", "Cancer", "health"),
    ("hal_domain", "Santé", "health"),
    ("hal_domain", "Imagerie médicale", "health"),
    ("hal_domain", "Imagerie médicale", "physical"),
    ("hal_domain", "Médicaments", "health"),
    ("hal_domain", "Pharmacie galénique", "health"),
    ("hal_domain", "Sport", "health"),
    ("hal_domain", "Biomatériaux", "health"),
    ("hal_domain", "Biomatériaux", "physical"),
    ("hal_domain", "Ingénierie biomédicale", "health"),
    ("hal_domain", "Ingénierie biomédicale", "physical"),
    ("hal_domain", "Bio-informatique", "life"),
    ("hal_domain", "Bio-informatique", "physical"),
    # wos_subject : fourre-tout `Multidisciplinary Sciences` et
    # `Science & Technology - Other Topics` exclus (non informatifs).
    ("wos_subject", "Engineering", "physical"),
    ("wos_subject", "Computer science", "physical"),
    ("wos_subject", "Psychology", "social"),
    ("wos_subject", "Psychology", "health"),
    ("wos_subject", "Materials science", "physical"),
    ("wos_subject", "Physics", "physical"),
    ("wos_subject", "Chemistry", "physical"),
    ("wos_subject", "Mathematics", "physical"),
    ("wos_subject", "Anthropology", "social"),
    ("wos_subject", "Physiology", "life"),
    ("wos_subject", "Physiology", "health"),
    ("wos_subject", "SURGERY", "health"),
    ("wos_subject", "Oncology", "health"),
    ("wos_subject", "Ecology", "life"),
    ("wos_subject", "Philosophy", "social"),
    ("wos_subject", "Physics, Particles & Fields", "physical"),
    ("wos_subject", "History", "social"),
    ("wos_subject", "Geology", "physical"),
    ("wos_subject", "Environmental Sciences & Ecology", "life"),
    ("wos_subject", "Environmental Sciences & Ecology", "physical"),
    ("wos_subject", "Cultural Studies", "social"),
    ("wos_subject", "Cell biology", "life"),
    ("wos_subject", "Environmental Sciences", "life"),
    ("wos_subject", "Environmental Sciences", "physical"),
    ("wos_subject", "Neurosciences & Neurology", "health"),
    ("wos_subject", "Infectious diseases", "health"),
    ("wos_subject", "Immunology", "life"),
    ("wos_subject", "Immunology", "health"),
    ("wos_subject", "Geosciences, Multidisciplinary", "physical"),
    ("wos_subject", "Astronomy & Astrophysics", "physical"),
    ("wos_subject", "Business & Economics", "social"),
    ("wos_subject", "Urban studies", "social"),
    ("wos_subject", "RHEUMATOLOGY", "health"),
    ("wos_subject", "Gastroenterology & Hepatology", "health"),
    ("wos_subject", "Hematology", "health"),
    ("wos_subject", "Cardiac & Cardiovascular Systems", "health"),
    ("wos_subject", "Cardiovascular System & Cardiology", "health"),
    ("wos_subject", "Radiology, Nuclear Medicine & Medical Imaging", "health"),
    ("wos_subject", "Radiology, Nuclear Medicine & Medical Imaging", "physical"),
    ("wos_subject", "Engineering, Biomedical", "health"),
    ("wos_subject", "Engineering, Biomedical", "physical"),
    ("wos_subject", "Clinical neurology", "health"),
    ("wos_subject", "Public, Environmental & Occupational Health", "health"),
    ("wos_subject", "General & Internal Medicine", "health"),
    ("wos_subject", "Medicine, General & Internal", "health"),
    ("wos_subject", "Psychiatry", "health"),
    ("wos_subject", "Medicine, Research & Experimental", "health"),
    ("wos_subject", "Sport Sciences", "health"),
    ("wos_subject", "Sport Sciences", "life"),
    ("wos_subject", "Microbiology", "life"),
    ("wos_subject", "Cancer", "health"),
    ("wos_subject", "Food Science & Technology", "life"),
    ("wos_subject", "Nursing", "health"),
    ("wos_subject", "Biochemistry & Molecular Biology", "life"),
    ("wos_subject", "Nutrition & dietetics", "health"),
    ("wos_subject", "Nutrition & dietetics", "life"),
    ("wos_subject", "Pharmacology & Pharmacy", "health"),
    ("wos_subject", "Rehabilitation", "health"),
    ("wos_subject", "Emergency medicine", "health"),
    ("wos_subject", "Dermatology", "health"),
    ("wos_subject", "Endocrinology & Metabolism", "health"),
    ("wos_subject", "Obstetrics & Gynecology", "health"),
    ("wos_subject", "Ophthalmology", "health"),
    ("wos_subject", "Health Care Sciences & Services", "health"),
    ("wos_subject", "Research & Experimental Medicine", "health"),
    ("wos_subject", "Veterinary Sciences", "life"),
    ("wos_subject", "Genetics & Heredity", "life"),
    ("wos_subject", "Parasitology", "life"),
    ("wos_subject", "Biotechnology & Applied Microbiology", "life"),
    ("wos_subject", "Plant Sciences", "life"),
    ("wos_subject", "Forestry", "life"),
    ("wos_subject", "Agriculture, Dairy & Animal Science", "life"),
    ("wos_subject", "Biology", "life"),
    ("wos_subject", "Soil Science", "life"),
    ("wos_subject", "Soil Science", "physical"),
    ("wos_subject", "Paleontology", "life"),
    ("wos_subject", "Paleontology", "physical"),
    ("wos_subject", "Biophysics", "life"),
    ("wos_subject", "Biophysics", "physical"),
    ("wos_subject", "Materials Science, Multidisciplinary", "physical"),
    ("wos_subject", "Chemistry, Multidisciplinary", "physical"),
    ("wos_subject", "Chemistry, Physical", "physical"),
    ("wos_subject", "Geochemistry & Geophysics", "physical"),
    ("wos_subject", "Oceanography", "physical"),
    ("wos_subject", "Physics, Nuclear", "physical"),
    ("wos_subject", "Physics, Multidisciplinary", "physical"),
    ("wos_subject", "Physics, Applied", "physical"),
    ("wos_subject", "Spectroscopy", "physical"),
    ("wos_subject", "Meteorology & Atmospheric Sciences", "physical"),
    ("wos_subject", "Mathematics, Applied", "physical"),
    ("wos_subject", "Engineering, Electrical & Electronic", "physical"),
    ("wos_subject", "Engineering, Civil", "physical"),
    ("wos_subject", "Operations Research & Management Science", "physical"),
    ("wos_subject", "Transportation", "physical"),
    ("wos_subject", "Economics", "social"),
    ("wos_subject", "Classics", "social"),
    ("wos_subject", "Demography", "social"),
    ("wos_subject", "Communication", "social"),
    ("wos_subject", "Management", "social"),
    ("wos_subject", "Literature", "social"),
    ("wos_subject", "Environmental Studies", "social"),
    ("wos_subject", "Environmental Studies", "physical"),
    ("wos_subject", "Architecture", "social"),
]

# DOAJ : premier niveau LCC du `journals.doaj_payload->>'Subjects'` mappé
# vers les 4 domains OA. `Science` seul est multi-affecté (physical+life)
# car la branche est trop large sans sous-niveau ; les sous-niveaux
# explicites discriminent finement.
_DOAJ_PATTERN_SQL = """
    CASE
        WHEN raw_lcc ~ '^Medicine'                                                              THEN ARRAY['health']
        WHEN raw_lcc ~ '^Science:\\s*(Biology|Microbiology|Botany|Zoology|Natural)'             THEN ARRAY['life']
        WHEN raw_lcc ~ '^Science(\\s*$|:\\s*(Mathematics|Physics|Chemistry|Astronomy|Geology))' THEN ARRAY['physical']
        WHEN raw_lcc ~ '^Science'                                                               THEN ARRAY['physical', 'life']
        WHEN raw_lcc ~ '^Technology'                                                            THEN ARRAY['physical']
        WHEN raw_lcc ~ '^Agriculture'                                                           THEN ARRAY['life']
        WHEN raw_lcc ~ '^Social Sciences'                                                       THEN ARRAY['social']
        WHEN raw_lcc ~ '^Language and Literature'                                               THEN ARRAY['social']
        WHEN raw_lcc ~ '^Philosophy'                                                            THEN ARRAY['social']
        WHEN raw_lcc ~ '^Education'                                                             THEN ARRAY['social']
        WHEN raw_lcc ~ '^History'                                                               THEN ARRAY['social']
        WHEN raw_lcc ~ '^Fine Arts'                                                             THEN ARRAY['social']
        WHEN raw_lcc ~ '^Music'                                                                 THEN ARRAY['social']
        WHEN raw_lcc ~ '^Political'                                                             THEN ARRAY['social']
        WHEN raw_lcc ~ '^Law'                                                                   THEN ARRAY['social']
        WHEN raw_lcc ~ '^Geography'                                                             THEN ARRAY['social', 'physical']
        WHEN raw_lcc ~ '^Auxiliary sciences of history'                                         THEN ARRAY['social']
        ELSE ARRAY[]::text[]
    END
"""

# Label OA du domain (level 0) → code court utilisé dans `_ARBITRE_MAPPING`.
_OA_DOMAIN_CODES: list[tuple[str, str]] = [
    ("Health Sciences", "health"),
    ("Life Sciences", "life"),
    ("Physical Sciences", "physical"),
    ("Social sciences", "social"),
]


def _values_clause(rows: Sequence[tuple[str, ...]]) -> str:
    """Construit la liste `(a, b, ...), (...)` pour un CTE VALUES.

    Les littéraux SQL utilisent le quoting `$tag$...$tag$` (dollar-quoting
    PostgreSQL), insensible aux apostrophes des labels HAL. Aucune valeur
    d'entrée n'est utilisateur — toutes proviennent des constantes ci-dessus.
    """
    parts = []
    for row in rows:
        cols = ", ".join(f"$lbl${col}$lbl$" for col in row)
        parts.append(f"({cols})")
    return ",\n    ".join(parts)


def _build_sql(*, dry_run: bool) -> str:
    arbitre_values = _values_clause(_ARBITRE_MAPPING)
    domain_values = _values_clause(_OA_DOMAIN_CODES)
    select_or_update = (
        """
        SELECT COUNT(*) AS n_liens_rejetes FROM to_reject;
    """
        if dry_run
        else """
        UPDATE publication_subjects ps
        SET rejected = TRUE
        FROM to_reject tr
        WHERE ps.publication_id = tr.publication_id
          AND ps.subject_id = tr.subject_id
          AND ps.source = 'openalex';

        SELECT COUNT(*) AS n_liens_rejetes FROM to_reject;
    """
    )
    return f"""
WITH RECURSIVE arbitre_mapping(ontology, label, oa_domain) AS (
    VALUES {arbitre_values}
),
oa_domain_codes(label, code) AS (
    VALUES {domain_values}
),
-- Pour chaque sujet OpenAlex, son domain de tête (level 0) en remontant
-- la chaîne `parent` au sein de l'ontologie. Matérialisé une fois.
--
-- Le JOIN passe par LOWER() : OpenAlex stocke les labels avec une casse
-- incohérente entre un sujet et la référence `parent` qui pointe vers lui
-- (ex. `Social sciences` vs `Social Sciences`, `Molecular biology` vs
-- `Molecular Biology`, `SURGERY` vs `Surgery`). Sans normalisation, ~50 %
-- des sujets se retrouvent orphelins de la chaîne.
oa_subject_root AS (
    SELECT
        s.id AS subject_id,
        s.label AS root_label,
        LOWER(s.label) AS current_label_lc,
        0 AS depth
    FROM subjects s
    WHERE s.ontologies ? 'openalex_topic'
      AND (s.ontologies->'openalex_topic'->>'level')::int = 0
    UNION ALL
    SELECT
        child.id,
        parent.root_label,
        LOWER(child.label),
        parent.depth + 1
    FROM subjects child
    JOIN oa_subject_root parent
      ON parent.current_label_lc = LOWER(child.ontologies->'openalex_topic'->>'parent')
    WHERE child.ontologies ? 'openalex_topic'
      AND parent.depth < 3
),
oa_subject_to_domain AS (
    SELECT DISTINCT r.subject_id, c.code AS root_code
    FROM oa_subject_root r
    JOIN oa_domain_codes c ON c.label = r.root_label
),
-- Publis avec ≥2 domains OpenAlex effectivement attestés (level 0).
publi_oa_domains AS (
    SELECT ps.publication_id, ARRAY_AGG(DISTINCT c.code ORDER BY c.code) AS domains
    FROM publication_subjects ps
    JOIN subjects s ON s.id = ps.subject_id
    JOIN oa_domain_codes c ON c.label = s.label
    WHERE ps.source = 'openalex' AND NOT ps.rejected
      AND s.ontologies ? 'openalex_topic'
      AND (s.ontologies->'openalex_topic'->>'level')::int = 0
    GROUP BY ps.publication_id
    HAVING COUNT(DISTINCT c.code) >= 2
),
-- Support arbitre via labels HAL/WoS/theses.
arbitre_support_labels AS (
    SELECT pod.publication_id, am.oa_domain AS code, COUNT(*) AS n
    FROM publi_oa_domains pod
    JOIN publication_subjects ps ON ps.publication_id = pod.publication_id
    JOIN subjects s ON s.id = ps.subject_id
    JOIN arbitre_mapping am ON am.label = s.label AND s.ontologies ? am.ontology
    WHERE NOT ps.rejected AND ps.source <> 'openalex'
    GROUP BY pod.publication_id, am.oa_domain
),
-- Support arbitre via le journal DOAJ.
doaj_lcc_per_journal AS (
    SELECT j.id AS journal_id, TRIM(seg) AS raw_lcc
    FROM journals j,
         LATERAL UNNEST(string_to_array(j.doaj_payload->>'Subjects', ' | ')) AS seg
    WHERE j.doaj_payload IS NOT NULL
      AND j.doaj_payload->>'Subjects' IS NOT NULL
      AND j.doaj_payload->>'Subjects' <> ''
),
doaj_journal_domain AS (
    SELECT journal_id, oa_domain
    FROM doaj_lcc_per_journal,
         LATERAL (SELECT UNNEST({_DOAJ_PATTERN_SQL}) AS oa_domain) m
),
arbitre_support_doaj AS (
    SELECT pod.publication_id, djd.oa_domain AS code, COUNT(*) AS n
    FROM publi_oa_domains pod
    JOIN publications p ON p.id = pod.publication_id
    JOIN doaj_journal_domain djd ON djd.journal_id = p.journal_id
    GROUP BY pod.publication_id, djd.oa_domain
),
arbitre_support AS (
    SELECT publication_id, code, SUM(n) AS n_support
    FROM (
        SELECT * FROM arbitre_support_labels
        UNION ALL
        SELECT * FROM arbitre_support_doaj
    ) t
    GROUP BY publication_id, code
),
publi_domain_status AS (
    SELECT pod.publication_id, d AS code,
           COALESCE(asup.n_support, 0) AS n_support
    FROM publi_oa_domains pod
    CROSS JOIN LATERAL UNNEST(pod.domains) AS d
    LEFT JOIN arbitre_support asup
        ON asup.publication_id = pod.publication_id AND asup.code = d
),
rejets AS (
    SELECT pds.publication_id, pds.code AS rejected_code
    FROM publi_domain_status pds
    WHERE pds.n_support = 0
      AND EXISTS (SELECT 1 FROM publi_domain_status pds2
                  WHERE pds2.publication_id = pds.publication_id
                    AND pds2.n_support > 0)
),
-- Cascade : pour chaque (publi, domain rejeté), on rejette le sujet de
-- tête ET tous ses descendants OA présents sur la publi via la chaîne
-- `parent`. Le mapping subject_id → root_code est fourni par
-- `oa_subject_to_domain`.
to_reject AS (
    SELECT DISTINCT r.publication_id, otd.subject_id
    FROM rejets r
    JOIN oa_subject_to_domain otd ON otd.root_code = r.rejected_code
    JOIN publication_subjects ps
      ON ps.publication_id = r.publication_id
     AND ps.subject_id = otd.subject_id
     AND ps.source = 'openalex'
     AND NOT ps.rejected
)
{select_or_update}
""".strip()


def _reset_existing_rejections(conn: Connection) -> int:
    """Remet à FALSE tous les `rejected = TRUE` pour réappliquer la règle.

    À ce stade le script est l'unique source de rejets ; quand une
    curation manuelle sera ajoutée côté admin, distinguer la source du
    rejet (colonne dédiée) avant de pouvoir reset sélectivement.
    """
    return conn.execute(
        text("UPDATE publication_subjects SET rejected = FALSE WHERE rejected = TRUE")
    ).rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien : compte les liens qui seraient rejetés.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        if args.dry_run:
            n = conn.execute(text(_build_sql(dry_run=True))).scalar_one()
            log.info("(dry-run) %d liens publication_subjects seraient rejetés.", n)
            return 0

        n_reset = _reset_existing_rejections(conn)
        log.info("Reset : %d rejets existants remis à FALSE.", n_reset)

        n_rejected = conn.execute(text(_build_sql(dry_run=False))).scalar_one()
        conn.commit()
        log.info("Terminé : %d liens publication_subjects rejetés.", n_rejected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
