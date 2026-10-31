# STATUS: maintenance
"""Bilan Science ouverte d'un laboratoire pour une année, au format Markdown.

Une publication appartient au laboratoire quand au moins un de ses auteurs du périmètre signe avec lui. Les évolutions portent sur les cinq années qui finissent à l'année du bilan, les thèses sur dix années.

Usage :
    uv run python -m interfaces.cli.maintenance.report_open_science --structure m2ish --year 2025 [--output data/reports/science-ouverte/m2ish-2025.md]
"""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Connection, Row, text

from domain.countries import non_international_country_codes
from domain.dates import today
from domain.platforms.platform import PlatformType
from domain.platforms.registry import known_platform_of_copy, preprint_servers_of_prefix
from domain.publications.doc_types import DocType
from domain.publications.licenses import OPEN_LICENSES, license_label
from domain.publications.metadata import OaStatus
from domain.sources.registry import source_label
from infrastructure.db.engine import get_sync_engine
from infrastructure.read_models.perimeters.queries import get_institution_country
from infrastructure.read_models.structures.queries import (
    AUTHOR_SOURCE_CONTRIBUTION,
    AUTHORED_PUBLICATION,
)
from infrastructure.sql_fragments import diamond_journal_sql

EVOLUTION_YEARS = 5
THESIS_YEARS = 10
TOP_SERIAL_MIN_ARTICLES = 2
TOP_COUNTRIES = 6

type SqlRow = Row[tuple[object, ...]]

# Types comptés dans le taux d'open access.
OA_RATE_TYPES = (DocType.ARTICLE, DocType.REVIEW, DocType.LETTER, DocType.CONFERENCE_PAPER)
# Types parus dans une revue, pour les modèles de revues et les APC.
SERIAL_TYPES = (DocType.ARTICLE, DocType.REVIEW, DocType.LETTER, DocType.EDITORIAL)
CONFERENCE_TYPES = (DocType.CONFERENCE, DocType.CONFERENCE_PAPER, DocType.POSTER)
OPEN_STATUSES = (OaStatus.DIAMOND, OaStatus.GOLD, OaStatus.HYBRID, OaStatus.BRONZE, OaStatus.GREEN)

DOC_TYPE_LABELS = {
    DocType.ARTICLE: "Article",
    DocType.REVIEW: "Revue de littérature (review)",
    DocType.CONFERENCE_PAPER: "Texte publié dans des actes",
    DocType.CONFERENCE: "Communication sans texte publié",
    DocType.RECORDED_TALK: "Conférence filmée",
    DocType.POSTER: "Poster",
    DocType.EDITORIAL: "Éditorial",
    DocType.LETTER: "Lettre",
    DocType.BOOK: "Ouvrage",
    DocType.BOOK_CHAPTER: "Chapitre d'ouvrage",
    DocType.BOOK_REVIEW: "Compte rendu de lecture",
    DocType.THESIS: "Thèse soutenue",
    DocType.ONGOING_THESIS: "Thèse en cours",
    DocType.HDR: "HDR",
    DocType.PREPRINT: "Preprint",
    DocType.DATASET: "Jeu de données",
    DocType.DATA_PAPER: "Data paper",
    DocType.SOFTWARE: "Logiciel",
    DocType.REPORT: "Rapport",
    DocType.MEDIA: "Média",
    DocType.ERRATUM: "Erratum",
    DocType.OTHER: "Autre",
}

MODEL_LABELS = {"full_oa": "Open access", "diamond": "Open access", "subscription": "Abonnement"}

# Modèles des revues entièrement en open access.
OPEN_ACCESS_MODELS = "('full_oa', 'diamond')"

# Publications `p` du laboratoire.
LAB_PUBLICATIONS = f"SELECT p.* FROM publications p WHERE {AUTHORED_PUBLICATION}"

# Fichier déposé dans HAL pour la publication `p`, sous embargo ou non.
HAL_FULL_TEXT = """
    EXISTS (
        SELECT 1 FROM source_records sr
        JOIN source_record_locations l ON l.source_record_id = sr.id
        WHERE sr.publication_id = p.id AND sr.source = 'hal' AND l.pdf_url IS NOT NULL
    )
"""

# Publication `p` cosignée hors du pays de l'établissement. Le paramètre `:non_international` liste les codes pays non internationaux.
INTERNATIONAL = "EXISTS (SELECT 1 FROM unnest(p.countries) c WHERE c <> ALL(:non_international))"

# Revue `j` diamant : marquée diamant, ou dans le DOAJ sans APC ni autres frais.
DIAMOND_JOURNAL = f"COALESCE({diamond_journal_sql('j')}, false)"


def _values(members: Sequence[str]) -> list[str]:
    return [str(m) for m in members]


def _num(n: float) -> str:
    """Formate un nombre à la française : espace insécable pour les milliers."""
    return f"{n:,.0f}".replace(",", " ")


def _pct(part: int, total: int) -> str:
    return f"{100 * part / total:.1f}".replace(".", ",") + " %" if total else "—"


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


class OpenScienceReport:
    """Sections du bilan d'une structure pour une année."""

    def __init__(self, conn: Connection, structure_id: int, year: int) -> None:
        self._conn = conn
        self._binds: dict[str, object] = {
            "structure_id": structure_id,
            "year": year,
            "non_international": non_international_country_codes(get_institution_country(conn)),
        }
        self.year = year

    def _rows(self, sql: str, **binds: object) -> Sequence[SqlRow]:
        return self._conn.execute(text(sql), {**self._binds, **binds}).all()

    def _one(self, sql: str, **binds: object) -> SqlRow:
        return self._conn.execute(text(sql), {**self._binds, **binds}).one()

    def title(self) -> str:
        s = self._one("SELECT name, acronym FROM structures WHERE id = :structure_id")
        return f"# Bilan Science ouverte {self.year} — {s.acronym or s.name}\n\n{s.name}.\n\nDonnées extraites de la base bibliométrique le {today():%d/%m/%Y}. Document de travail."

    def typology(self) -> str:
        rows = self._rows(f"""
            SELECT p.doc_type, COUNT(*) AS n FROM ({LAB_PUBLICATIONS}) p
            WHERE p.publication_year = :year GROUP BY 1 ORDER BY 2 DESC, 1
        """)
        n_oa = sum(r.n for r in rows if r.doc_type in OA_RATE_TYPES)
        return (
            "## Typologie\n\n"
            + _table(
                ["Type", str(self.year)],
                [(DOC_TYPE_LABELS.get(r.doc_type, r.doc_type), r.n) for r in rows],
            )
            + f"\n\nLe taux d'open access porte sur les articles, revues de littérature, lettres et textes publiés dans des actes de congrès : {n_oa} publications en {self.year}."
        )

    def oa_evolution(self) -> tuple[str, SqlRow | None]:
        rows = self._rows(
            f"""
            SELECT p.publication_year AS year, COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE {HAL_FULL_TEXT}) AS hal,
                   COUNT(*) FILTER (WHERE NOT {HAL_FULL_TEXT} AND p.oa_status = ANY(:open)) AS elsewhere
            FROM ({LAB_PUBLICATIONS}) p
            WHERE p.publication_year BETWEEN :year - :span + 1 AND :year AND p.doc_type::text = ANY(:types)
            GROUP BY 1 ORDER BY 1
            """,
            span=EVOLUTION_YEARS,
            types=_values(OA_RATE_TYPES),
            open=_values(OPEN_STATUSES),
        )
        table = _table(
            [
                "Année",
                "Publications",
                "Texte intégral dans HAL",
                "Ouvert hors HAL",
                "Fermé",
                "Taux d'ouverture",
            ],
            [
                (
                    r.year,
                    r.total,
                    r.hal,
                    r.elsewhere,
                    r.total - r.hal - r.elsewhere,
                    _pct(r.hal + r.elsewhere, r.total),
                )
                for r in rows
            ],
        )
        current = next((r for r in rows if r.year == self.year), None)
        text_ = (
            f"## Open access : évolution {self.year - EVOLUTION_YEARS + 1}–{self.year}\n\n{table}\n\n"
            "« Texte intégral dans HAL » : fichier déposé dans HAL, ou lien HAL vers arXiv ou PubMed Central. "
            "« Ouvert hors HAL » : texte ouvert chez l'éditeur ou dans une autre archive, selon OpenAlex, Web of Science ou scanR.\n\n"
            "Toutes les années sont observées à la même date. Le dépôt dans HAL est en partie rétrospectif."
        )
        return text_, current

    def serial_models(self) -> str:
        r = self._one(
            f"""
            SELECT COUNT(*) AS total, COUNT(DISTINCT p.serial_id) AS serials,
                   COUNT(*) FILTER (WHERE j.oa_model IN {OPEN_ACCESS_MODELS}) AS full_oa,
                   COUNT(*) FILTER (WHERE j.oa_model IN {OPEN_ACCESS_MODELS} AND p.oa_status = ANY(:open)) AS full_oa_open,
                   COUNT(*) FILTER (WHERE j.oa_model IN {OPEN_ACCESS_MODELS} AND {DIAMOND_JOURNAL}) AS diamond,
                   COUNT(*) FILTER (WHERE j.oa_model = 'subscription') AS subscription,
                   COUNT(*) FILTER (WHERE j.oa_model = 'subscription' AND p.oa_status = 'hybrid') AS hybrid,
                   COUNT(*) FILTER (WHERE j.oa_model = 'subscription' AND p.oa_status = 'bronze') AS bronze,
                   COUNT(*) FILTER (WHERE j.oa_model = 'subscription' AND p.oa_status = 'green') AS green,
                   COUNT(*) FILTER (WHERE j.oa_model IS NULL OR j.oa_model NOT IN ('full_oa', 'diamond', 'subscription')) AS unknown
            FROM ({LAB_PUBLICATIONS}) p
            LEFT JOIN publishing.serials j ON j.id = p.serial_id
            WHERE p.publication_year = :year AND p.doc_type::text = ANY(:types)
            """,
            types=_values(SERIAL_TYPES),
            open=_values(OPEN_STATUSES),
        )
        sub_open = r.hybrid + r.bronze + r.green
        rows = [
            (
                "Revue entièrement en open access",
                r.full_oa,
                f"{r.full_oa_open}, dont {r.diamond} en revue diamant",
            ),
            (
                "Revue sur abonnement",
                r.subscription,
                f"{sub_open} : {r.hybrid} hybrides payants, {r.bronze} ouverts chez l'éditeur sans licence, {r.green} par dépôt en archive",
            ),
        ]
        if r.unknown:
            rows.append(("Modèle inconnu ou hors revue", r.unknown, "—"))
        return (
            f"## Modèles de revues et APC\n\nPérimètre : {r.total} articles, revues de littérature, lettres et éditoriaux de {self.year}, parus dans {r.serials} revues.\n\n"
            + _table(["Modèle de la revue", "Articles", "Dont ouverts"], rows)
            + "\n\nRevue diamant : revue marquée diamant, ou revue du DOAJ sans APC ni autres frais."
        )

    def apc(self) -> str:
        paid = self._rows(f"""
            SELECT p.publication_year AS year, ap.open_access_fee, COUNT(*) AS n, SUM(ap.amount_eur_ht) AS amount
            FROM publishing.apc_payments ap
            JOIN ({LAB_PUBLICATIONS}) p ON p.id = ap.publication_id
            WHERE p.publication_year IN (:year, :year - 1)
            GROUP BY 1, 2
        """)

        def paid_line(year: int, oa_fee: bool) -> str:
            r = next((r for r in paid if r.year == year and r.open_access_fee is oa_fee), None)
            return f"{r.n} paiements pour {_num(r.amount or 0)} € HT" if r else "aucun"

        gold_hybrid = self._rows(
            f"""
            SELECT EXISTS (
                       SELECT 1 FROM contributions a
                       WHERE a.publication_id = p.id AND a.is_corresponding AND {AUTHOR_SOURCE_CONTRIBUTION}
                   ) AS lab_corresponding
            FROM ({LAB_PUBLICATIONS}) p
            JOIN publishing.serials j ON j.id = p.serial_id
            WHERE p.publication_year = :year AND p.doc_type::text = ANY(:types) AND p.oa_status IN ('gold', 'hybrid')
            """,
            types=_values(SERIAL_TYPES),
        )
        corresponding = sum(1 for r in gold_hybrid if r.lab_corresponding)
        return (
            "### APC\n\n"
            f"Frais d'open access payés (Open APC, enquête APC) : {paid_line(self.year, True)} pour les publications de {self.year}, {paid_line(self.year - 1, True)} pour celles de {self.year - 1}. "
            f"Autres frais de publication : {paid_line(self.year, False)} pour {self.year}.\n\n"
            f"L'auteur correspondant appartient au laboratoire pour {corresponding} des {len(gold_hybrid)} articles gold et hybrides de {self.year}."
        )

    def serials(self) -> str:
        rows = self._rows(
            f"""
            SELECT j.title, pb.name AS publisher, j.oa_model, {DIAMOND_JOURNAL} AS diamond, COUNT(*) AS n
            FROM ({LAB_PUBLICATIONS}) p
            JOIN publishing.serials j ON j.id = p.serial_id
            LEFT JOIN publishing.publishers pb ON pb.id = j.publisher_id
            WHERE p.publication_year = :year AND p.doc_type::text = ANY(:types)
            GROUP BY j.id, pb.name ORDER BY n DESC, j.title
            """,
            types=_values(SERIAL_TYPES),
        )
        top = [r for r in rows if r.n >= TOP_SERIAL_MIN_ARTICLES]
        others = len(rows) - len(top)

        def model(r: SqlRow) -> str:
            label = MODEL_LABELS.get(r.oa_model, "Inconnu")
            return f"{label} (diamant)" if r.diamond else label

        return (
            "## Revues\n\n"
            + _table(
                ["Revue", "Éditeur", "Modèle", "Articles"],
                [(r.title, r.publisher or "—", model(r), r.n) for r in top],
            )
            + (f"\n\n{others} autres revues comptent un article chacune." if others else "")
        )

    def conferences(self) -> str:
        rows = self._rows(
            f"""
            SELECT COALESCE(p.container_title, 'Conférence non renseignée') AS conference, COUNT(*) AS n
            FROM ({LAB_PUBLICATIONS}) p
            WHERE p.publication_year = :year AND p.doc_type::text = ANY(:types)
            GROUP BY 1 ORDER BY 2 DESC, 1
            """,
            types=_values(CONFERENCE_TYPES),
        )
        if not rows:
            return f"## Conférences\n\nAucune communication en {self.year}."
        total = sum(r.n for r in rows)
        listed = ", ".join(f"{r.conference} ({r.n})" if r.n > 1 else r.conference for r in rows)
        return f"## Conférences\n\n{total} communications, posters et textes publiés dans des actes, dans {len(rows)} conférences : {listed}."

    def books(self) -> str:
        r = self._one(f"""
            SELECT COUNT(*) FILTER (WHERE p.doc_type = 'book') AS books,
                   COUNT(*) FILTER (WHERE p.doc_type = 'book_chapter') AS chapters
            FROM ({LAB_PUBLICATIONS}) p WHERE p.publication_year = :year
        """)
        if not (r.books or r.chapters):
            return f"## Ouvrages et chapitres\n\nAucun ouvrage ni chapitre en {self.year}."
        return f"## Ouvrages et chapitres\n\n{r.books} ouvrages et {r.chapters} chapitres en {self.year}."

    def theses(self) -> str:
        rows = self._rows(
            f"""
            SELECT p.publication_year AS year,
                   COUNT(*) FILTER (WHERE p.doc_type = 'thesis') AS defended,
                   COUNT(*) FILTER (WHERE p.doc_type = 'thesis' AND p.oa_status = ANY(:open)) AS open,
                   COUNT(*) FILTER (WHERE p.doc_type = 'thesis' AND p.oa_status = 'embargoed') AS embargoed
            FROM ({LAB_PUBLICATIONS}) p
            WHERE p.publication_year BETWEEN :year - :span + 1 AND :year AND p.doc_type = 'thesis'
            GROUP BY 1 ORDER BY 1
            """,
            span=THESIS_YEARS,
            open=_values(OPEN_STATUSES),
        )
        ongoing = self._one(f"""
            SELECT COUNT(*) AS n FROM ({LAB_PUBLICATIONS}) p WHERE p.doc_type = 'ongoing_thesis'
        """).n
        defended = sum(r.defended for r in rows)
        opened = sum(r.open for r in rows)
        return (
            "## Thèses\n\nL'ouverture d'une thèse se mesure sur plusieurs années : les thèses récentes sont en traitement ou sous embargo.\n\n"
            + _table(
                [
                    "Année de soutenance",
                    "Thèses soutenues",
                    "En open access",
                    "Sous embargo",
                    "Taux d'ouverture",
                ],
                [(r.year, r.defended, r.open, r.embargoed, _pct(r.open, r.defended)) for r in rows],
            )
            + f"\n\nSur {THESIS_YEARS} ans : {opened} thèses ouvertes sur {defended} ({_pct(opened, defended)}). theses.fr signale {ongoing} thèses en cours."
        )

    def collaborations(self) -> str:
        countries = self._rows(
            f"""
            SELECT COALESCE(rc.name, upper(c)) AS country, COUNT(*) AS n
            FROM ({LAB_PUBLICATIONS}) p, unnest(p.countries) AS c
            LEFT JOIN ref.countries rc ON rc.code = c
            WHERE p.publication_year = :year AND c <> ALL(:non_international)
            GROUP BY 1 ORDER BY 2 DESC, 1
            """
        )
        r = self._one(
            f"""
            WITH lab AS (
                SELECT p.*, {INTERNATIONAL} AS international
                FROM ({LAB_PUBLICATIONS}) p WHERE p.publication_year = :year
            )
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE international) AS international,
                   COUNT(*) FILTER (WHERE international AND doc_type::text = ANY(:types)) AS intl_oa_base,
                   COUNT(*) FILTER (WHERE international AND doc_type::text = ANY(:types) AND oa_status = ANY(:open)) AS intl_open,
                   COUNT(*) FILTER (WHERE NOT international AND doc_type::text = ANY(:types)) AS other_oa_base,
                   COUNT(*) FILTER (WHERE NOT international AND doc_type::text = ANY(:types) AND oa_status = ANY(:open)) AS other_open
            FROM lab
            """,
            types=_values(OA_RATE_TYPES),
            open=_values(OPEN_STATUSES),
        )
        top = ", ".join(f"{c.country} ({c.n})" for c in countries[:TOP_COUNTRIES])
        return (
            "## Collaborations internationales\n\n"
            f"{r.international} publications sur {r.total} ont au moins un coauteur affilié à l'étranger, avec {len(countries)} pays au total. "
            f"Pays les plus fréquents : {top}.\n\n"
            f"Taux d'ouverture des copublications internationales : {r.intl_open} sur {r.intl_oa_base} ({_pct(r.intl_open, r.intl_oa_base)}). "
            f"Autres publications : {r.other_open} sur {r.other_oa_base} ({_pct(r.other_open, r.other_oa_base)})."
        )

    def orcid(self) -> SqlRow:
        return self._one(f"""
            WITH lab_authors AS (
                SELECT DISTINCT a.person_id
                FROM publications p JOIN contributions a ON a.publication_id = p.id
                WHERE p.publication_year = :year AND a.person_id IS NOT NULL AND {AUTHOR_SOURCE_CONTRIBUTION}
            ),
            hal_accounts AS (
                SELECT la.person_id, bool_or(k.identifiers ? 'orcid') AS has_orcid
                FROM lab_authors la
                JOIN contributions g ON g.person_id = la.person_id
                JOIN aligned_source_contributions m ON m.contribution_id = g.id
                JOIN source_contributions sc ON sc.id = m.source_contribution_id AND sc.source = 'hal'
                JOIN contributor_information k ON k.id = sc.contributor_information_id
                WHERE k.identifiers ? 'hal_person_id'
                GROUP BY la.person_id
            )
            SELECT (SELECT COUNT(*) FROM lab_authors) AS authors,
                   {_with_identifier("orcid")} AS with_orcid,
                   {_with_identifier("idhal")} AS with_idhal,
                   (SELECT COUNT(*) FROM hal_accounts) AS hal_accounts,
                   (SELECT COUNT(*) FROM hal_accounts WHERE has_orcid) AS hal_with_orcid
        """)

    def orcid_section(self, r: SqlRow) -> str:
        return (
            "## ORCID et idHAL\n\n"
            f"{r.with_orcid} des {r.authors} auteurs du laboratoire en {self.year} ont un ORCID connu de la base.\n\n"
            f"{r.hal_accounts} auteurs ont un compte HAL. Le compte HAL de {r.hal_with_orcid} d'entre eux est lié à un ORCID.\n\n"
            f"{r.with_idhal} auteurs ont un idHAL, préalable au CV HAL.\n\n"
            "Absent de la base : effectif du laboratoire, CV HAL."
        )

    def datasets(self) -> str:
        counts = self._rows(
            f"""
            SELECT p.publication_year AS year,
                   COUNT(*) FILTER (WHERE p.doc_type = 'dataset') AS datasets,
                   COUNT(*) FILTER (WHERE p.doc_type = 'data_paper') AS data_papers
            FROM ({LAB_PUBLICATIONS}) p
            WHERE p.publication_year BETWEEN :year - :span + 1 AND :year AND p.doc_type IN ('dataset', 'data_paper')
            GROUP BY 1 ORDER BY 1
            """,
            span=EVOLUTION_YEARS,
        )
        details = self._rows(
            f"""
            SELECT COALESCE(j.title, p.container_title, 'Entrepôt non renseigné') AS repository,
                   p.license::text AS license, COUNT(*) AS n
            FROM ({LAB_PUBLICATIONS}) p
            LEFT JOIN publishing.serials j ON j.id = p.serial_id
            WHERE p.publication_year BETWEEN :year - :span + 1 AND :year AND p.doc_type = 'dataset'
            GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2
            """,
            span=EVOLUTION_YEARS,
        )
        period = f"{self.year - EVOLUTION_YEARS + 1}–{self.year}"
        if not counts:
            return f"## Jeux de données\n\nAucun jeu de données ni data paper sur {period}."
        return (
            "## Jeux de données\n\n"
            + _table(
                ["Année", "Jeux de données", "Data papers"],
                [(r.year, r.datasets, r.data_papers) for r in counts],
            )
            + f"\n\nEntrepôts et licences des jeux de données, {period} :\n\n"
            + _table(
                ["Entrepôt", "Licence", "Jeux de données"],
                [(r.repository, license_label(r.license), r.n) for r in details],
            )
        )

    def hal_deposits(self) -> str:
        rows = self._rows(f"""
            SELECT p.deposit_license::text AS license, COUNT(*) AS n
            FROM ({LAB_PUBLICATIONS}) p
            WHERE p.publication_year = :year AND {HAL_FULL_TEXT}
            GROUP BY 1 ORDER BY 2 DESC
        """)
        total = sum(r.n for r in rows)
        if not total:
            return f"## Dépôts dans HAL\n\nAucun texte intégral déposé dans HAL pour {self.year}."
        closed = sum(r.n for r in rows if r.license not in OPEN_LICENSES)
        return (
            "## Dépôts dans HAL\n\n"
            + _table(
                ["Licence du fichier déposé", f"Textes intégraux {self.year}"],
                [(license_label(r.license), r.n) for r in rows],
            )
            + f"\n\n{closed} textes intégraux sur {total} sont déposés sans licence ouverte : "
            "autorisation de diffusion HAL, droits réservés, ou licence non renseignée."
        )

    def preprints(self) -> str:
        rows = self._rows(
            f"""
            SELECT p.publication_year AS year, p.license::text AS license,
                   ARRAY(
                       SELECT DISTINCT split_part(i.id_value, '/', 1) FROM source_records sr
                       JOIN source_record_identifiers i ON i.source_record_id = sr.id
                       WHERE sr.publication_id = p.id AND i.id_type = 'doi'
                         AND i.removed_by IS NULL AND i.role <> 'related'
                   ) AS prefixes,
                   ARRAY(
                       SELECT DISTINCT ARRAY[l.url, COALESCE(pl.openalex_id, '')]
                       FROM source_records sr
                       JOIN source_record_locations l ON l.source_record_id = sr.id
                       LEFT JOIN platforms pl ON pl.id = l.platform_id
                       WHERE sr.publication_id = p.id
                   ) AS copies
            FROM ({LAB_PUBLICATIONS}) p
            WHERE p.publication_year BETWEEN :year - :span + 1 AND :year AND p.doc_type = 'preprint'
            """,
            span=EVOLUTION_YEARS,
        )
        period = f"{self.year - EVOLUTION_YEARS + 1}–{self.year}"
        if not rows:
            return f"## Preprints\n\nAucun preprint sur {period}."
        by_year = Counter(r.year for r in rows)
        by_platform = Counter(
            preprint_server(r.prefixes, r.copies) or "Autre plateforme ou archive" for r in rows
        )
        return (
            "## Preprints\n\n"
            + _table(["Année", "Preprints"], sorted(by_year.items()))
            + f"\n\nPlateformes, {period} :\n\n"
            + _table(["Serveur", "Preprints"], by_platform.most_common())
            + f"\n\nLicences des preprints, {period} :\n\n"
            + _table(
                ["Licence", "Preprints"],
                Counter(license_label(r.license) for r in rows).most_common(),
            )
        )

    def sources(self) -> str:
        rows = self._rows(f"""
            SELECT s AS source, COUNT(*) AS n
            FROM ({LAB_PUBLICATIONS}) p, unnest(p.sources) AS s
            WHERE p.publication_year = :year GROUP BY 1 ORDER BY 2 DESC
        """)
        return "## Sources\n\n" + _table(
            ["Source", f"Publications {self.year}"],
            [(source_label(r.source), r.n) for r in rows],
        )

    def synthesis(self, oa: SqlRow | None, orcid: SqlRow) -> str:
        r = self._one(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE {INTERNATIONAL}) AS international,
                   COUNT(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM contributions a
                       WHERE a.publication_id = p.id AND a.is_corresponding AND {AUTHOR_SOURCE_CONTRIBUTION}
                   )) AS corresponding
            FROM ({LAB_PUBLICATIONS}) p WHERE p.publication_year = :year
            """
        )
        n_countries = self._one(
            f"""
            SELECT COUNT(DISTINCT c) AS n FROM ({LAB_PUBLICATIONS}) p, unnest(p.countries) AS c
            WHERE p.publication_year = :year AND c <> ALL(:non_international)
            """
        ).n
        opened = oa.hal + oa.elsewhere if oa else 0
        oa_total = oa.total if oa else 0
        return "## Synthèse\n\n" + _table(
            ["Indicateur", "Valeur"],
            [
                (f"Publications {self.year} rattachées au laboratoire", r.total),
                (
                    "Articles et communications en open access",
                    f"{_pct(opened, oa_total)} ({opened} sur {oa_total})",
                ),
                (
                    "Copublications internationales",
                    f"{r.international} publications, {n_countries} pays",
                ),
                (
                    "Auteurs du laboratoire avec un ORCID connu",
                    f"{orcid.with_orcid} sur {orcid.authors}",
                ),
                (
                    "Auteurs dont le compte HAL est lié à un ORCID",
                    f"{orcid.hal_with_orcid} sur {orcid.authors}",
                ),
                (
                    "Publications dont l'auteur correspondant appartient au laboratoire",
                    r.corresponding,
                ),
            ],
        )

    def render(self) -> str:
        oa_text, oa_current = self.oa_evolution()
        orcid = self.orcid()
        sections = [
            self.title(),
            self.synthesis(oa_current, orcid),
            self.typology(),
            oa_text,
            self.serial_models() + "\n\n" + self.apc(),
            self.serials(),
            self.conferences(),
            self.books(),
            self.theses(),
            self.collaborations(),
            self.orcid_section(orcid),
            self.hal_deposits(),
            self.preprints(),
            self.datasets(),
            self.sources(),
        ]
        return "\n\n".join(sections) + "\n"


def _with_identifier(id_type: str) -> str:
    """Renvoie la sous-requête comptant les auteurs de `lab_authors` pourvus d'un identifiant de ce type, non rejeté."""
    return f"""(SELECT COUNT(DISTINCT pi.person_id) FROM person_identifiers pi
                JOIN lab_authors la ON la.person_id = pi.person_id
                WHERE pi.id_type = '{id_type}' AND pi.status <> 'rejected')"""


def preprint_server(prefixes: Sequence[str], copies: Sequence[Sequence[str]]) -> str | None:
    """Renvoie le serveur de preprints d'une publication, d'après ses copies (URL et source OpenAlex, vide à défaut), à défaut d'après les préfixes de ses DOI."""
    for url, source in sorted((url, source) for url, source in copies):
        known = known_platform_of_copy(url, source or None)
        if known and known.platform_type is PlatformType.PREPRINT_SERVER:
            return known.name
    for prefix in sorted(prefixes):
        if servers := preprint_servers_of_prefix(prefix):
            return servers[0].name
    return None


def structure_id(conn: Connection, code: str) -> int | None:
    return conn.execute(
        text("SELECT id FROM structures WHERE code = :code"), {"code": code}
    ).scalar()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--structure", required=True, help="code de la structure (`structures.code`)"
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", type=Path, help="fichier Markdown ; sortie standard par défaut")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        sid = structure_id(conn, args.structure)
        if sid is None:
            print(f"Structure inconnue : {args.structure}", file=sys.stderr)
            return 1
        report = OpenScienceReport(conn, sid, args.year).render()
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
