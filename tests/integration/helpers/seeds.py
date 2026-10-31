"""Semis de données pour les tests d'API, sous le propriétaire du schéma en validation immédiate.

Le serveur d'API lit les données sur sa propre connexion. Chaque fonction ouvre donc `owner_connection`, calcule ses valeurs par défaut, uniques quand la table l'exige, et délègue l'écriture à la fonction de semis du module de la table. Les fonctions qui insèrent une ligne renvoient son `id`.
"""

import datetime
import uuid
from collections.abc import Sequence

from sqlalchemy import text

from domain.normalize import normalize_text
from domain.source_records.identifiers import SourceIdentifier
from infrastructure.db.queues import Queue
from tests.integration.helpers.addresses import (
    ensure_country,
    insert_address,
    insert_address_structure,
)
from tests.integration.helpers.alignment import (
    align_source_contributions,
    contribution_person as _contribution_person,
    set_perimeter_author_contribution,
)
from tests.integration.helpers.config import set_config
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.db import owner_connection
from tests.integration.helpers.persons import (
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
    insert_rejected_contribution,
)
from tests.integration.helpers.pipeline_runs import insert_phase_execution
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.serials import (
    insert_doi_prefix,
    insert_monograph,
    insert_publisher,
    insert_serial,
    insert_serial_doi_namespace,
    insert_serial_issn,
)
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import (
    add_to_perimeter,
    insert_perimeter,
    insert_structure,
    insert_structure_name_form,
    insert_tutelle,
)
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject


def uniq(prefix: str, sep: str = "_") -> str:
    """Renvoie `prefix` suivi d'un suffixe aléatoire de 8 caractères hexadécimaux."""
    return f"{prefix}{sep}{uuid.uuid4().hex[:8]}"


def seed_address(
    raw_text: str, *, countries: list[str] | None = None, publication_count: int = 1
) -> int:
    with owner_connection() as conn:
        return insert_address(
            conn, raw_text, countries=countries, publication_count=publication_count
        )


def seed_structure(
    code: str | None = None,
    type_: str = "labo",
    *,
    name: str | None = None,
    hal_collection: str | None = None,
    reuse: bool = False,
) -> int:
    """Sème une structure de code unique par défaut ; le nom vaut le code par défaut. `reuse` renvoie la structure de même code si elle existe."""
    code = code or uniq("STR")
    with owner_connection() as conn:
        return insert_structure(
            conn,
            code,
            name=name or code,
            structure_type=type_,
            hal_collection=hal_collection,
            reuse=reuse,
        )


def seed_structure_name_form(structure_id: int, form_text: str | None = None) -> int:
    """Sème une forme de nom de structure ; une forme de 6 caractères au plus est en mots entiers, comme l'exige la table."""
    with owner_connection() as conn:
        return insert_structure_name_form(conn, structure_id, form_text=form_text or uniq("form"))


def seed_perimeter(
    code: str | None = None,
    root_structure_ids: list[int] | None = None,
    name: str | None = None,
    *,
    replace: bool = False,
) -> int:
    """Sème un périmètre de code unique par défaut. `replace` réécrit les racines d'un périmètre de même code."""
    code = code or uniq("perim")
    with owner_connection() as conn:
        return insert_perimeter(
            conn, code, root_structure_ids=root_structure_ids, name=name or code, replace=replace
        )


def seed_add_to_perimeter(structure_id: int, *, code: str, name: str) -> int:
    """Rattache `structure_id` au périmètre `code`, créé sous le nom `name` s'il est absent, et renvoie l'`id` du périmètre."""
    with owner_connection() as conn:
        return add_to_perimeter(conn, structure_id, code=code, name=name)


def seed_tutelle(parent_id: int, *, child_id: int) -> int:
    """Sème la tutelle de `parent_id` sur `child_id`."""
    with owner_connection() as conn:
        return insert_tutelle(conn, parent_id, child_id=child_id)


def seed_address_structure(
    address_id: int,
    *,
    structure_id: int,
    matched_form_id: int | None = None,
    is_confirmed: bool | None = None,
) -> int:
    """Sème le lien de l'adresse `address_id` à la structure `structure_id`."""
    with owner_connection() as conn:
        return insert_address_structure(
            conn,
            address_id,
            structure_id=structure_id,
            matched_form_id=matched_form_id,
            is_confirmed=is_confirmed,
        )


def seed_country(code: str, name: str) -> None:
    """Sème le pays `code`, s'il est absent du référentiel."""
    with owner_connection() as conn:
        ensure_country(conn, code, name)


def seed_config(key: str, value: object) -> None:
    """Pose le paramètre `key` à `value`, sérialisé en jsonb, même sur une valeur existante."""
    with owner_connection() as conn:
        set_config(conn, key, value)


def seed_publisher(name: str | None = None, *, name_normalized: str | None = None) -> int:
    """Sème un éditeur de nom unique par défaut, normalisé par `normalize_text` sauf `name_normalized`."""
    name = name or uniq("Publisher")
    with owner_connection() as conn:
        return insert_publisher(
            conn,
            name,
            name_normalized=normalize_text(name) if name_normalized is None else name_normalized,
        )


def seed_serial(
    title: str | None = None,
    *,
    title_normalized: str | None = None,
    publisher_id: int | None = None,
    serial_type: str = "unknown",
) -> int:
    """Sème une revue de titre unique par défaut, normalisé par `normalize_text` sauf `title_normalized`. Le type par défaut est celui du schéma."""
    title = title or uniq("Journal")
    with owner_connection() as conn:
        return insert_serial(
            conn,
            title,
            title_normalized=normalize_text(title)
            if title_normalized is None
            else title_normalized,
            publisher_id=publisher_id,
            serial_type=serial_type,
        )


def seed_serial_issn(
    serial_id: int,
    *,
    issn: str,
    support: str | None = None,
    issnl: str | None = None,
    status: str = "active",
) -> int:
    """Sème un ISSN de la revue `serial_id`. Les valeurs par défaut sont celles du schéma."""
    with owner_connection() as conn:
        return insert_serial_issn(
            conn, serial_id, issn=issn, support=support, issnl=issnl, status=status
        )


def seed_monograph(title: str, *, proceedings: bool = False, isbn: str | None = None) -> int:
    """Sème une monographie de titre normalisé par `normalize_text`."""
    with owner_connection() as conn:
        return insert_monograph(
            conn,
            title,
            title_normalized=normalize_text(title),
            proceedings=proceedings,
            isbn=isbn,
        )


def seed_person(
    last: str = "TEST",
    first: str = "J",
    *,
    normalizer: str = "lower",
    first_name_normalized: str | None = None,
) -> int:
    """Sème une personne aux nom et prénom normalisés par `normalizer` (`lower` ou `normalize_text`). `first_name_normalized` impose le prénom normalisé."""
    with owner_connection() as conn:
        return insert_person(
            conn,
            last,
            first_name=first,
            normalizer=normalizer,
            first_name_normalized=first_name_normalized,
        )


def seed_person_identifier(
    person_id: int, *, id_type: str, id_value: str, source: str = "manual", status: str = "pending"
) -> int:
    """Sème un identifiant de la personne `person_id`. Le statut par défaut est celui du schéma."""
    with owner_connection() as conn:
        return insert_person_identifier(
            conn, person_id, id_type=id_type, id_value=id_value, source=source, status=status
        )


def seed_person_name_form(person_id: int, *, name_form: str, sources: list[str]) -> None:
    """Sème une forme de nom de la personne `person_id`."""
    with owner_connection() as conn:
        insert_person_name_form(conn, person_id, name_form=name_form, sources=sources)


def seed_rejected_contribution(publication_id: int, *, person_id: int) -> None:
    """Rejette la paire publication ↔ personne, comme l'administration : un rejet par enregistrement source de la publication. Une publication sans enregistrement source en reçoit un."""
    with owner_connection() as conn:
        insert_rejected_contribution(conn, publication_id, person_id=person_id)


def seed_publication(
    title: str = "T",
    *,
    year: int = 2024,
    normalize_title: bool = True,
    doc_type: str | None = "other",
    oa_status: str | None = "unknown",
    serial_id: int | None = None,
    monograph_id: int | None = None,
    publisher_id: int | None = None,
    in_perimeter: bool = False,
) -> int:
    """Sème une publication de titre normalisé `lower(title)`, NULL si `normalize_title` est faux. Les valeurs par défaut sont celles du schéma ; `None` écrit NULL."""
    with owner_connection() as conn:
        return insert_publication(
            conn,
            title,
            title_normalized=title.lower() if normalize_title else None,
            normalize_title=normalize_title,
            publication_year=year,
            doc_type=doc_type,
            oa_status=oa_status,
            serial_id=serial_id,
            monograph_id=monograph_id,
            publisher_id=publisher_id,
            in_perimeter=in_perimeter,
            nullable=("doc_type", "oa_status"),
        )


def seed_contribution(
    publication_id: int,
    *,
    person_id: int,
    in_perimeter: bool = False,
    roles: list[str] | None = None,
) -> int:
    """Sème une contribution de la personne `person_id` à la publication `publication_id`, en mode de résolution `manual`. Les valeurs par défaut sont celles du schéma."""
    with owner_connection() as conn:
        return insert_contribution(
            conn, publication_id, person_id=person_id, in_perimeter=in_perimeter, roles=roles
        )


def seed_in_perimeter_contributions(serial_id: int) -> None:
    """Pose une contribution du périmètre (personne non rejetée) sur chaque publication de la revue, puis calcule comme le pipeline `publications.in_perimeter` et les `publication_count` de la revue et de son éditeur."""
    with owner_connection() as conn:
        publication_ids = (
            conn.execute(
                text("SELECT id FROM publications WHERE serial_id = :serial"), {"serial": serial_id}
            )
            .scalars()
            .all()
        )
        for publication_id in publication_ids:
            person_id = insert_person(
                conn, uniq("Author"), first_name="Jane", first_name_normalized="jane"
            )
            insert_contribution(
                conn, publication_id, person_id=person_id, in_perimeter=True, roles=["author"]
            )
        conn.execute(
            text(
                "UPDATE publications p SET perimeter_evidence = coalesce(("
                "SELECT array_agg(DISTINCT e ORDER BY e) FROM contributions a JOIN persons pe "
                "ON pe.id = a.person_id AND pe.exclusion IS NULL "
                "CROSS JOIN LATERAL unnest(a.perimeter_evidence) e "
                "WHERE a.publication_id = p.id), '{}') "
                "WHERE p.serial_id = :serial"
            ),
            {"serial": serial_id},
        )
        conn.execute(
            text(
                "UPDATE serials j SET publication_count = COALESCE((SELECT COUNT(*) "
                "FROM publications p WHERE p.serial_id = j.id AND p.in_perimeter "
                "AND p.doc_type NOT IN ('memoir', 'peer_review')), 0) WHERE j.id = :serial"
            ),
            {"serial": serial_id},
        )
        conn.execute(
            text(
                "UPDATE publishers pub SET publication_count = COALESCE((SELECT SUM(j.publication_count) "
                "FROM serials j WHERE j.publisher_id = pub.id), 0) "
                "WHERE pub.id = (SELECT publisher_id FROM serials WHERE id = :serial)"
            ),
            {"serial": serial_id},
        )


def seed_source_record(
    source: str = "hal",
    *,
    source_id: str | None = None,
    title: str = "T",
    publication_year: int | None = 2024,
    publication_id: int | None = None,
    serial_id: int | None = None,
    doc_type: str | None = None,
    raw_doc_type: str | None = None,
    doi: str | None = None,
    corrections: dict[str, object] | None = None,
    identifiers: Sequence[SourceIdentifier] = (),
) -> int:
    """Sème un enregistrement source d'identifiant `source_id`, unique par défaut. Une colonne à `None` garde la valeur par défaut du schéma. `raw_doc_type` vaut par défaut `doc_type`. `identifiers` s'écrivent comme dans `insert_source_record`."""
    with owner_connection() as conn:
        return insert_source_record(
            conn,
            publication_id,
            source=source,
            source_id=source_id or uniq("sid"),
            title=title,
            publication_year=publication_year,
            serial_id=serial_id,
            doc_type=doc_type,
            raw_doc_type=raw_doc_type,
            doi=doi,
            corrections=corrections,
            identifiers=identifiers,
        )


def seed_source_contribution(
    source: str = "hal",
    source_record_id: int | None = None,
    in_perimeter: bool = True,
    raw_author_name: str = "Test Author",
    author_position: int = 0,
    identifiers: dict[str, object] | None = None,
) -> int:
    """Sème une contribution source de nom brut `raw_author_name` et d'identifiants `identifiers`, sur un enregistrement source semé au besoin."""
    source_record = source_record_id or seed_source_record(source=source)
    with owner_connection() as conn:
        return insert_source_contribution(
            conn,
            source_record,
            source=source,
            author_position=author_position,
            raw_author_name=raw_author_name,
            author_name_normalized=raw_author_name.lower(),
            identifiers=identifiers,
            in_perimeter=in_perimeter,
        )


def seed_alignment(publication_id: int, source_contributions: list[tuple[int, int]]) -> int:
    """Aligne dans une contribution les contributions sources `(contribution source, enregistrement source)` de la publication `publication_id` ; la première la fonde, les autres la rejoignent par le nom."""
    with owner_connection() as conn:
        return align_source_contributions(conn, publication_id, source_contributions)


def seed_perimeter_author_contribution(
    contribution_id: int, *, person_id: int | None = None, mode: str | None = None
) -> None:
    """Fait de la contribution `contribution_id` une contribution d'auteur du périmètre (rôle d'auteur, indice `address`), rattachée à la personne `person_id` par le mode de résolution `mode`."""
    with owner_connection() as conn:
        set_perimeter_author_contribution(conn, contribution_id, person_id=person_id, mode=mode)


def publication_perimeter_evidence(publication_id: int) -> list[str]:
    """Renvoie les indices d'appartenance au périmètre de la publication `publication_id`."""
    with owner_connection() as conn:
        return conn.execute(
            text("SELECT perimeter_evidence::text[] FROM publications WHERE id = :id"),
            {"id": publication_id},
        ).scalar_one()


def contribution_to_resolve(contribution_id: int) -> bool:
    """Indique si la contribution `contribution_id` est dans la file des contributions à personne à redécider."""
    with owner_connection() as conn:
        return contribution_id in queued(conn, Queue.CONTRIBUTION_RESOLUTION)


def contribution_person(contribution_id: int) -> tuple[int | None, str | None]:
    """Renvoie la personne et le mode de résolution de la contribution `contribution_id`."""
    with owner_connection() as conn:
        return _contribution_person(conn, contribution_id)


def seed_subject(label: str | None = None, *, usage_count: int = 0) -> int:
    """Sème un sujet de libellé unique par défaut. Le compte d'usage par défaut est celui du schéma."""
    with owner_connection() as conn:
        return insert_subject(conn, label or uniq("Subject"), usage_count=usage_count)


def seed_publication_subject(publication_id: int, *, subject_id: int, source: str = "hal") -> None:
    """Sème le lien de la publication `publication_id` au sujet `subject_id`."""
    with owner_connection() as conn:
        insert_publication_subject(conn, publication_id, subject_id=subject_id, source=source)


def seed_doi_prefix(
    prefix: str,
    *,
    ra: str,
    publisher_id: int | None = None,
    crossref_member_id: int | None = None,
) -> None:
    """Sème le préfixe DOI `prefix` de l'agence `ra`."""
    with owner_connection() as conn:
        insert_doi_prefix(
            conn, prefix, ra=ra, publisher_id=publisher_id, crossref_member_id=crossref_member_id
        )


def seed_serial_doi_namespace(namespace: str, *, serial_id: int, dois: int, share: float) -> None:
    """Sème l'espace de noms DOI `namespace` appris pour la revue `serial_id`."""
    with owner_connection() as conn:
        insert_serial_doi_namespace(conn, namespace, serial_id=serial_id, dois=dois, share=share)


def seed_phase_execution(
    run_id: int,
    *,
    phase: str,
    mode: str,
    status: str,
    sources: list[str],
    signals: list[object],
    metrics: dict[str, object],
    details: dict[str, object],
) -> None:
    """Sème l'exécution de la phase `phase` du run `run_id`, commencée et finie à l'instant présent."""
    with owner_connection() as conn:
        insert_phase_execution(
            conn,
            run_id,
            phase=phase,
            started_at=datetime.datetime.now(datetime.UTC),
            mode=mode,
            status=status,
            sources=sources,
            signals=signals,
            metrics=metrics,
            details=details,
        )
