"""Ordre-dépendance de la phase persons — canal nominal.

Deux contributions sources d'une **même personne** sans identifiant partagé, l'une en forme pleine (« Jean Martin »), l'autre en forme initiale (« J Martin »). L'ordre de traitement suit `sa.id` (ORDER BY déterministe de `fetch_unlinked_contributions`).

La création live sème la map en mémoire via `compute_person_name_forms` (ordres + initiales) : une contribution source initiale rattrape une personne créée en forme pleine. Dans l'ordre inverse, la contribution source pleine rejoint la personne réduite par ses initiales compatibles, et la personne prend le prénom plein. Les deux ordres donnent une seule personne dès le premier run.

Les tests n'appellent que `run()` (pas `populate`, qui committe et casserait le rollback de la fixture) ; `_populate_canonical_forms` simule le peuplement des formes de nom.
"""

import logging

from sqlalchemy import text

from application.services.persons.core import create_person
from domain.persons.name_forms import compute_person_name_forms
from infrastructure.repositories import person_repository
from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.cascade import run_cascade
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from pipeline.transformation.persons.purge import purge
from tests.integration.helpers.groups import group_ungrouped, insert_group
from tests.integration.helpers.persons import insert_person_name_form
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_LOG = logging.getLogger("test")


def _seed_source_contribution(conn, *, publication_id, raw_name, name_norm):
    """Publication + source_record + contribution source in-périmètre non rattachée, avec
    les informations du contributeur `name_norm` (sans identifiant). L'id de la contribution source = `publication_id`, ce qui
    fixe l'ordre de traitement."""
    insert_publication(conn, f"publication {publication_id}", row_id=publication_id)
    insert_source_record(
        conn,
        publication_id,
        source_id=f"hal-{publication_id}",
        title=f"publication {publication_id}",
        row_id=publication_id,
        publication_year=2024,
        doc_type="article",
    )
    insert_source_contribution(
        conn,
        publication_id,
        row_id=publication_id,
        raw_author_name=raw_name,
        author_name_normalized=name_norm,
        in_perimeter=True,
    )


def _seed_two_source_records(
    conn, *, publication_id, sa1_id, raw1, norm1, sa2_id, raw2, norm2, grouped=True
):
    """Une publication vue par HAL (enregistrement source `sa1_id`) et OpenAlex (enregistrement source `sa2_id`), une contribution source non rattachée chacune, en position 0. `grouped` : les deux contributions sources forment un groupe, celui d'un même auteur."""
    insert_publication(conn, f"publication {publication_id}", row_id=publication_id)
    for source_record_id, source in ((sa1_id, "hal"), (sa2_id, "openalex")):
        insert_source_record(
            conn,
            publication_id,
            source=source,
            source_id=f"{source}-{source_record_id}",
            title=f"publication {publication_id}",
            row_id=source_record_id,
            publication_year=2024,
            doc_type="article",
        )
    for source_contribution_id, source, raw, norm in (
        (sa1_id, "hal", raw1, norm1),
        (sa2_id, "openalex", raw2, norm2),
    ):
        insert_source_contribution(
            conn,
            source_contribution_id,
            source=source,
            row_id=source_contribution_id,
            raw_author_name=raw,
            author_name_normalized=norm,
            in_perimeter=True,
        )
    if grouped:
        insert_group(conn, publication_id, [(sa1_id, sa1_id), (sa2_id, sa2_id)])


def _run_create(conn):
    """Arbitrage des conflits d'identifiant (no-op ici, pas d'identifiant) puis la cascade."""
    group_ungrouped(conn)
    arbitrate_identifier_conflicts(conn, _LOG, repo=PgPersonRepository(conn))
    run_cascade(conn, _LOG, repo=PgPersonRepository(conn))


def _populate_canonical_forms(conn):
    """Simule le peuplement des formes canoniques (source « persons » de `populate`) :
    chaque personne acquiert les variantes de son nom via `compute_person_name_forms` —
    initiales comprises, ce qui rend « j martin » commune à « J Martin » et « Jean Martin »."""
    for r in conn.execute(text("SELECT id, last_name, first_name FROM persons")).all():
        for form in compute_person_name_forms(r.last_name, r.first_name or ""):
            insert_person_name_form(
                conn, r.id, name_form=form, sources=["persons"], ignore_conflict=True
            )


def _run_phase(conn):
    """Run complet de la phase personnes : rattachement/création, peuplement des formes, purge.

    Le peuplement est simulé (`populate` committe, incompatible avec le rollback de la fixture),
    la purge appelée directement — l'ordre reproduit `PersonsPhase`."""
    _run_create(conn)
    _populate_canonical_forms(conn)
    purge(conn)


def _martin_count(conn) -> int:
    return conn.execute(
        text("SELECT COUNT(*) FROM persons WHERE last_name_normalized = 'martin'")
    ).scalar_one()


def _person_of(conn, source_contribution_id):
    return conn.execute(
        text("SELECT person_id FROM source_contributions WHERE id = :i"),
        {"i": source_contribution_id},
    ).scalar_one()


def test_full_then_initial_merges(sa_sync_conn):
    """Forme pleine (id bas, traitée d'abord) puis initiale dans le même run : la personne
    créée en « Jean Martin » sème « j martin », la contribution source « J Martin » s'y rattache —
    une seule personne."""
    _seed_source_contribution(
        sa_sync_conn, publication_id=95001, raw_name="Jean Martin", name_norm="jean martin"
    )
    _seed_source_contribution(
        sa_sync_conn, publication_id=95002, raw_name="J Martin", name_norm="j martin"
    )
    _run_create(sa_sync_conn)
    assert _martin_count(sa_sync_conn) == 1


def _martin_first_names(conn) -> list[str]:
    return (
        conn.execute(
            text(
                "SELECT first_name_normalized FROM persons "
                "WHERE last_name_normalized = 'martin' ORDER BY first_name_normalized"
            )
        )
        .scalars()
        .all()
    )


def _seed_person(conn, last_name, first_name, *, source_contributions=()):
    """Personne existante, rattachée par son nom aux contributions sources `source_contributions` (ids) et à leurs groupes."""
    pid = create_person(last_name, first_name, repo=person_repository(conn))
    group_ungrouped(conn)
    for source_contribution_id in source_contributions:
        conn.execute(
            text(
                "UPDATE source_contributions SET person_id = :p, resolution_mode = 'name' "
                "WHERE id = :s"
            ),
            {"p": pid, "s": source_contribution_id},
        )
        conn.execute(
            text("""
                UPDATE source_contribution_groups g
                SET person_id = :p, resolution_mode = 'name'
                FROM source_contribution_group_members gm
                WHERE gm.group_id = g.id AND gm.source_contribution_id = :s
            """),
            {"p": pid, "s": source_contribution_id},
        )
    return pid


def test_initial_then_full_joins_in_a_single_run(sa_sync_conn):
    """Forme initiale (id bas) puis pleine : « J Martin » crée « Martin J » ; « Jean Martin », de forme inconnue, la rejoint par ses initiales compatibles, et la personne prend le prénom « Jean »."""
    _seed_source_contribution(
        sa_sync_conn, publication_id=95003, raw_name="J Martin", name_norm="j martin"
    )
    _seed_source_contribution(
        sa_sync_conn, publication_id=95004, raw_name="Jean Martin", name_norm="jean martin"
    )
    _run_create(sa_sync_conn)
    assert _martin_first_names(sa_sync_conn) == ["jean"]
    assert _person_of(sa_sync_conn, 95003) == _person_of(sa_sync_conn, 95004)


def test_initial_then_full_stays_joined_over_runs(sa_sync_conn):
    """Le peuplement des formes et la purge ne défont pas le regroupement : « j martin » reste univoque, portée par « Jean Martin » seule."""
    conn = sa_sync_conn
    _seed_source_contribution(conn, publication_id=95003, raw_name="J Martin", name_norm="j martin")
    _seed_source_contribution(
        conn, publication_id=95004, raw_name="Jean Martin", name_norm="jean martin"
    )
    _run_phase(conn)
    _run_phase(conn)
    assert _martin_first_names(conn) == ["jean"]
    assert _person_of(conn, 95003) is not None
    assert _person_of(conn, 95003) == _person_of(conn, 95004)


def test_reduced_name_joins_a_compound_first_name(sa_sync_conn):
    """« Al-Izeri, A. » rejoint « Abdul-Majeed Al-Izeri » : les formes à initiales d'un prénom composé ne donnent que « a m al izeri », les initiales compatibles couvrent « a »."""
    conn = sa_sync_conn
    _seed_source_contribution(
        conn,
        publication_id=95070,
        raw_name="Abdul-Majeed Al-Izeri",
        name_norm="abdul majeed al izeri",
    )
    _seed_source_contribution(
        conn, publication_id=95071, raw_name="Al-Izeri, A.", name_norm="al izeri a"
    )
    _run_create(conn)
    count = conn.execute(
        text("SELECT COUNT(*) FROM persons WHERE last_name_normalized = 'al izeri'")
    ).scalar_one()
    assert count == 1
    assert _person_of(conn, 95070) == _person_of(conn, 95071)


def test_a_completed_first_name_turns_away_another_first_name(sa_sync_conn):
    """« Martin J » complétée en « Jean » : « Julie Martin » crée sa propre personne, et « J Martin », devenue ambiguë entre Jean et Julie, est re-orphelinée par la purge."""
    conn = sa_sync_conn
    _seed_source_contribution(conn, publication_id=95080, raw_name="J Martin", name_norm="j martin")
    _seed_source_contribution(
        conn, publication_id=95081, raw_name="Jean Martin", name_norm="jean martin"
    )
    _run_phase(conn)

    _seed_source_contribution(
        conn, publication_id=95082, raw_name="Julie Martin", name_norm="julie martin"
    )
    _run_phase(conn)

    assert _martin_first_names(conn) == ["jean", "julie"]
    assert _person_of(conn, 95082) != _person_of(conn, 95081)
    assert _person_of(conn, 95080) is None


def test_existing_reduced_person_takes_the_attested_first_name(sa_sync_conn):
    """Une personne « Tnourji A. » que ses contributions sources nomment « Abdellah » prend ce prénom avant la cascade ; « Abdelkader Tnourji » crée alors sa propre personne."""
    conn = sa_sync_conn
    _seed_source_contribution(
        conn, publication_id=95090, raw_name="Tnourji, A.", name_norm="tnourji a"
    )
    _seed_source_contribution(
        conn, publication_id=95091, raw_name="Abdellah Tnourji", name_norm="abdellah tnourji"
    )
    reduced = _seed_person(conn, "Tnourji", "A.", source_contributions=(95090, 95091))
    _seed_source_contribution(
        conn, publication_id=95092, raw_name="Abdelkader Tnourji", name_norm="abdelkader tnourji"
    )
    _run_create(conn)

    first_name = conn.execute(
        text("SELECT first_name FROM persons WHERE id = :p"), {"p": reduced}
    ).scalar_one()
    assert first_name == "Abdellah"
    assert _person_of(conn, 95092) not in (None, reduced)


def test_full_name_with_a_double_family_name_joins_the_reduced_person(sa_sync_conn):
    """« Florence Caldefie Chezet », sans virgule, rejoint « Caldefie-Chezet F. » par le découpage aux deux derniers mots, et la personne prend le prénom « Florence »."""
    conn = sa_sync_conn
    _seed_source_contribution(
        conn, publication_id=95110, raw_name="Caldefie-Chezet, F.", name_norm="caldefie chezet f"
    )
    reduced = _seed_person(conn, "Caldefie-Chezet", "F.", source_contributions=(95110,))
    _seed_source_contribution(
        conn,
        publication_id=95111,
        raw_name="Florence Caldefie Chezet",
        name_norm="florence caldefie chezet",
    )
    _run_create(conn)

    assert _person_of(conn, 95111) == reduced
    first_name = conn.execute(
        text("SELECT first_name FROM persons WHERE id = :p"), {"p": reduced}
    ).scalar_one()
    assert first_name == "Florence"


def test_reduced_person_with_competing_first_names_keeps_its_initials(sa_sync_conn):
    """Les contributions sources de « Martin J » la nomment « Jean » et « Julien » : elle garde ses initiales, et « Jacques Martin » ne s'y rattache pas."""
    conn = sa_sync_conn
    _seed_source_contribution(
        conn, publication_id=95100, raw_name="Jean Martin", name_norm="jean martin"
    )
    _seed_source_contribution(
        conn, publication_id=95101, raw_name="Julien Martin", name_norm="julien martin"
    )
    reduced = _seed_person(conn, "Martin", "J", source_contributions=(95100, 95101))
    _seed_source_contribution(
        conn, publication_id=95102, raw_name="Jacques Martin", name_norm="jacques martin"
    )
    _run_create(conn)

    first_name = conn.execute(
        text("SELECT first_name FROM persons WHERE id = :p"), {"p": reduced}
    ).scalar_one()
    assert first_name == "J"
    assert _person_of(conn, 95102) not in (None, reduced)


def test_ambiguous_form_reorphaned_when_homonym_appears(sa_sync_conn):
    """Sur-regroupement : « H Chanal » se colle d'abord à l'unique « Hervé Chanal » présent ;
    dès que « Hélène Chanal » coexiste et rend « h chanal » ambiguë, la contribution source réduite est
    re-orphelinée — elle ne reste pas collée au premier arrivé, quel que soit l'ordre."""
    conn = sa_sync_conn
    _seed_source_contribution(
        conn, publication_id=95010, raw_name="Hervé Chanal", name_norm="herve chanal"
    )
    _seed_source_contribution(conn, publication_id=95011, raw_name="H Chanal", name_norm="h chanal")
    _run_phase(conn)
    assert _person_of(conn, 95011) is not None  # rattachée à l'unique candidat

    _seed_source_contribution(
        conn, publication_id=95012, raw_name="Hélène Chanal", name_norm="helene chanal"
    )
    _run_phase(conn)  # crée « Hélène Chanal » ; « h chanal » devient ambiguë → re-orphelinage

    assert _person_of(conn, 95011) is None  # orpheline, plus collée à Hervé


def test_la_creation_annonce_les_indecidables_a_part(sa_sync_conn, caplog):
    """« H Chanal » désigne Hervé et Hélène : sa contribution source est comptée parmi celles qui peuvent créer une personne, et parmi elles comme indécidable. « Paul Durand », inconnu, crée sa personne."""
    conn = sa_sync_conn
    _seed_source_contribution(
        conn, publication_id=95040, raw_name="Hervé Chanal", name_norm="herve chanal"
    )
    _seed_source_contribution(
        conn, publication_id=95041, raw_name="Hélène Chanal", name_norm="helene chanal"
    )
    _run_create(conn)
    _populate_canonical_forms(conn)  # « h chanal » désigne les deux personnes

    _seed_source_contribution(conn, publication_id=95042, raw_name="H Chanal", name_norm="h chanal")
    _seed_source_contribution(
        conn, publication_id=95043, raw_name="Paul Durand", name_norm="paul durand"
    )
    with caplog.at_level(logging.INFO, logger="test"):
        _run_create(conn)

    assert "  ├─ 2 contributions sources non identifiées" in caplog.messages
    assert "  ├─ 1 indécidable (forme de nom ambiguë, ou candidats tous rejetés)" in caplog.messages
    assert "  └─ 1 personne créée" in caplog.messages


def test_une_forme_ambigue_rejoint_la_personne_de_son_groupe(sa_sync_conn):
    """« J Martin » (OpenAlex) désigne Julie et Joseph, et passe avant « Jacques Martin » (HAL) dans l'ordre des contributions sources. Les deux forment un groupe. Traitée après les créations, « J Martin » rejoint en cross-source la personne que crée l'autre contribution source du groupe."""
    conn = sa_sync_conn
    _seed_source_contribution(
        conn, publication_id=95050, raw_name="Julie Martin", name_norm="julie martin"
    )
    _seed_source_contribution(
        conn, publication_id=95051, raw_name="Joseph Martin", name_norm="joseph martin"
    )
    _run_create(conn)
    _populate_canonical_forms(conn)  # « j martin » désigne les deux personnes

    _seed_two_source_records(
        conn,
        publication_id=95060,
        sa1_id=95062,
        raw1="Jacques Martin",
        norm1="jacques martin",
        sa2_id=95061,
        raw2="J Martin",
        norm2="j martin",
    )
    _run_create(conn)

    assert _person_of(conn, 95061) is not None
    assert _person_of(conn, 95061) == _person_of(conn, 95062)


def test_un_groupe_reunit_deux_formes_disjointes_sur_une_personne(sa_sync_conn):
    """« Jean Martin » (HAL) et « J-P Martin » (OpenAlex) forment un groupe, et leurs noms sont compatibles (`names_compatible`). Leurs formes de nom sont disjointes. Traitée en premier, « Jean Martin » est différée puis créée. « J-P Martin » rejoint sa personne par cross-source."""
    conn = sa_sync_conn
    _seed_two_source_records(
        conn,
        publication_id=95020,
        sa1_id=95021,
        raw1="Jean Martin",
        norm1="jean martin",
        sa2_id=95022,
        raw2="J-P Martin",
        norm2="j p martin",
    )
    _run_create(conn)

    assert _martin_count(conn) == 1
    assert _person_of(conn, 95021) is not None
    assert _person_of(conn, 95021) == _person_of(conn, 95022)


def test_deux_contributions_sources_hors_groupe_creent_deux_personnes(sa_sync_conn):
    """« Jean Martin » (HAL) et « J-P Martin » (OpenAlex) occupent la même position, hors de tout groupe. Chacune crée sa personne."""
    conn = sa_sync_conn
    _seed_two_source_records(
        conn,
        publication_id=95030,
        sa1_id=95031,
        raw1="Jean Martin",
        norm1="jean martin",
        sa2_id=95032,
        raw2="J-P Martin",
        norm2="j p martin",
        grouped=False,
    )
    _run_create(conn)

    assert _martin_count(conn) == 2
