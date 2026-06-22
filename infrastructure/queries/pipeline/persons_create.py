"""Query service : lectures pour `create_persons_from_source_authorships`.

Appelé par `application/pipeline/create/create_persons_from_source_authorships.py`.
Regroupe les SELECT nécessaires aux 4 passes de rattachement
(comptes HAL, cross-source, IdRef/ORCID connus, lookup `person_name_forms`).
"""

from sqlalchemy import Connection, Row, text

from application.ports.pipeline.persons_create import (
    BareUnlinkedAuthorship,
    LinkedAuthorshipRow,
    PersonsCreateQueries,
)
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES_SQL


def fetch_unlinked_authorships(conn: Connection) -> list[BareUnlinkedAuthorship]:
    """Liste les `source_authorships` in-perimeter non rattachés à une `person`, toutes sources confondues.

    Colonnes :

    - `orcid`, `hal_person_id`, `idref` : lus directement depuis `person_identifiers` (JSONB), sans filtre par source. `hal_person_id` n'est porté que par les authorships HAL. La restriction de l'ORCID aux sources fiables (cf. `ORCID_MATCH_SOURCES`) est appliquée côté cascade de matching, pas ici.
    - `roles` : remonté tel quel ; en pratique non vide uniquement pour theses (distingue auteur vs directeur).

    Le nom (last/first) est parsé côté caller via `parse_raw_author_name(full_name)`.

    Les lignes sans `raw_author_name` sont exclues toutes sources confondues (sans nom, l'authorship est inexploitable pour le matching personnes).
    """
    rows = conn.execute(
        text(f"""
            SELECT sa_auth.id AS authorship_id,
                   sa_auth.source::text AS source,
                   sa_auth.raw_author_name AS full_name,
                   sa_auth.author_name_normalized,
                   sa_auth.person_identifiers->>'orcid' AS orcid,
                   sa_auth.person_identifiers->>'hal_person_id' AS hal_person_id,
                   sa_auth.person_identifiers->>'idref' AS idref,
                   sa_auth.roles,
                   sd.publication_id,
                   sa_auth.author_position,
                   TRUE AS in_perimeter
            FROM source_authorships sa_auth
            JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
            JOIN publications pub ON pub.id = sd.publication_id
            WHERE sa_auth.person_id IS NULL
              AND sa_auth.in_perimeter = TRUE
              AND sd.publication_id IS NOT NULL
              AND sa_auth.raw_author_name IS NOT NULL
              AND pub.doc_type NOT IN {OUT_OF_SCOPE_DOC_TYPES_SQL}
        """)
    ).all()
    return [_to_bare(r) for r in rows]


def _to_bare(r: Row) -> BareUnlinkedAuthorship:
    """Mappe une ligne SQL (projection partagée) vers `BareUnlinkedAuthorship`."""
    return BareUnlinkedAuthorship(
        authorship_id=r.authorship_id,
        source=r.source,
        full_name=r.full_name,
        author_name_normalized=r.author_name_normalized,
        orcid=r.orcid,
        hal_person_id=r.hal_person_id,
        idref=r.idref,
        roles=r.roles,
        publication_id=r.publication_id,
        author_position=r.author_position,
        in_perimeter=r.in_perimeter,
    )


_OOP_PROJECTION = """
    sa_auth.id AS authorship_id,
    sa_auth.source::text AS source,
    sa_auth.raw_author_name AS full_name,
    sa_auth.author_name_normalized,
    sa_auth.person_identifiers->>'orcid' AS orcid,
    sa_auth.person_identifiers->>'hal_person_id' AS hal_person_id,
    sa_auth.person_identifiers->>'idref' AS idref,
    sa_auth.roles,
    sd.publication_id,
    sa_auth.author_position,
    FALSE AS in_perimeter
"""

# Conditions communes à toutes les branches : SA orpheline hors-périmètre,
# rattachée à une publication active dans le scope métier, avec un nom.
_OOP_COMMON_WHERE = f"""
    sa_auth.person_id IS NULL
    AND sa_auth.in_perimeter = FALSE
    AND sd.publication_id IS NOT NULL
    AND sa_auth.raw_author_name IS NOT NULL
    AND pub.doc_type NOT IN {OUT_OF_SCOPE_DOC_TYPES_SQL}
"""


def _oop_identifier_branch(id_type: str, *, source_filter: str = "") -> str:
    """Branche « identifiant-ancré » : SA hors-périmètre dont l'identifiant
    `id_type` (jsonb) est déjà porté par une personne connue (non rejetée).

    Jointure `person_identifiers` ↔ `source_authorships` sur la valeur jsonb.
    Pas d'index d'expression : le planner ne sait pas sonder par valeur sur un
    jsonb (testé : JOIN / `= ANY` / LATERAL aboutissent tous à un seq scan des
    SA orphelines), il scanne donc l'espace orphelin. Coût assumé (cf. fiche
    `METIER_authorships-cross-source-matching`) en attendant la refonte ER
    set-based. `person_identifiers ? '{id_type}'` et la restriction de source
    ORCID sont des filtres de correction, pas d'optimisation.
    """
    return f"""
        SELECT {_OOP_PROJECTION}
        FROM person_identifiers pi
        JOIN source_authorships sa_auth
            ON sa_auth.person_identifiers->>'{id_type}' = pi.id_value
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN publications pub ON pub.id = sd.publication_id
        WHERE pi.id_type = '{id_type}'
          AND pi.status <> 'rejected'
          AND sa_auth.person_identifiers ? '{id_type}'
          {source_filter}
          AND {_OOP_COMMON_WHERE}
    """


# Branche « cross-source-ancrée » : SA hors-périmètre à une (publication,
# position) où une autre source_authorship est déjà rattachée à une personne.
# Self-join sur la **position source** (`linked.author_position`), pas la position
# canonique de `authorships` : c'est la clé qu'utilise `linked_index` côté
# orchestrateur ; s'ancrer sur la canonique sous-fetcherait dès que les sources
# divergent sur l'ordre des auteurs. La requête ne fait que borner les candidats ;
# le matching nom-compatible est tranché côté Python (`decide_cross_source_match`).
_OOP_CROSS_SOURCE_BRANCH = f"""
    SELECT {_OOP_PROJECTION}
    FROM source_authorships linked
    JOIN source_publications sd_linked ON sd_linked.id = linked.source_publication_id
    JOIN source_publications sd ON sd.publication_id = sd_linked.publication_id
    JOIN source_authorships sa_auth
        ON sa_auth.source_publication_id = sd.id
       AND sa_auth.author_position = linked.author_position
    JOIN publications pub ON pub.id = sd.publication_id
    WHERE linked.person_id IS NOT NULL
      AND linked.author_position IS NOT NULL
      AND {_OOP_COMMON_WHERE}
"""

# ORCID : restreint aux sources à ORCID déposé par l'auteur, à garder synchronisé
# avec `ORCID_MATCH_SOURCES` du domaine (filtre de correction : l'ORCID WoS/ScanR
# est dérivé algorithmiquement, pas un signal de matching).
_OOP_CANDIDATES_SQL = " UNION ".join(
    [
        _oop_identifier_branch(
            "orcid", source_filter="AND sa_auth.source IN ('crossref', 'openalex', 'hal')"
        ),
        _oop_identifier_branch("idref"),
        _oop_identifier_branch("hal_person_id"),
        _OOP_CROSS_SOURCE_BRANCH,
    ]
)


def fetch_out_of_perimeter_candidates(conn: Connection) -> list[BareUnlinkedAuthorship]:
    """Candidats hors-périmètre (`in_perimeter = FALSE`) rattachables sans
    forme de nom : par identifiant fort partagé avec une personne connue, ou
    par ancrage cross-source (même publication × position qu'un authorship
    déjà rattaché).

    Union des quatre branches d'accès, dédupliquée en SQL (`UNION`) : une même
    SA peut être candidate par plusieurs chemins. La cascade côté orchestrateur
    arbitre ensuite (les barreaux nom/création y sont neutralisés pour ces
    candidats hors-périmètre).

    On ne ramène jamais le pool mondial non-UCA : seulement les SA ancrées sur
    une personne existante (jointure identifiant) ou une position liée
    (cross-source). L'ensemble *rendu* décroît à chaque run (une fois rattachée,
    une SA n'est plus orpheline) ; le *coût* du fetch, lui, reste celui d'un scan
    de l'espace orphelin (cf. docstrings des branches) — acceptable (~minutes)
    en attendant la refonte ER set-based.
    """
    rows = conn.execute(text(_OOP_CANDIDATES_SQL)).all()
    return [_to_bare(r) for r in rows]


def fetch_linked_authorships(conn: Connection) -> list[LinkedAuthorshipRow]:
    """`source_authorships` déjà rattachées (toutes sources confondues).

    Ramène `raw_author_name` ; le caller parse via `domain.names.parse_raw_author_name` pour toutes les sources uniformément.
    """
    rows = conn.execute(
        text("""
            SELECT sa_auth.person_id, sa_auth.author_position,
                   sd.publication_id,
                   sa_auth.raw_author_name AS full_name,
                   sa_auth.source::text AS source
            FROM source_authorships sa_auth
            JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
            WHERE sa_auth.person_id IS NOT NULL
              AND sd.publication_id IS NOT NULL
        """)
    ).all()
    return [
        LinkedAuthorshipRow(
            person_id=r.person_id,
            author_position=r.author_position,
            publication_id=r.publication_id,
            full_name=r.full_name,
            source=r.source,
        )
        for r in rows
    ]


def _fetch_identifier_to_person_map(
    conn: Connection, id_type: str
) -> dict[str, tuple[int, str, str]]:
    """`{id_value: (person_id, last_name_normalized, first_name_normalized)}` pour les
    identifiants `id_type` connus non rejetés.

    Le nom normalisé de la personne ciblée accompagne le `person_id` : la cascade
    corrobore le match identifiant par le nom (`decide_match_by_identifier`), refusant
    un identifiant porté par une signature étrangère.
    """
    rows = conn.execute(
        text("""
            SELECT pi.id_value, pi.person_id,
                   p.last_name_normalized AS ln, p.first_name_normalized AS fn
            FROM person_identifiers pi
            JOIN persons p ON p.id = pi.person_id
            WHERE pi.id_type = :id_type
              AND pi.status != 'rejected'
        """),
        {"id_type": id_type},
    ).all()
    return {r.id_value: (r.person_id, r.ln or "", r.fn or "") for r in rows}


def fetch_idref_to_person_map(conn: Connection) -> dict[str, tuple[int, str, str]]:
    """`{idref: (person_id, nom, prénom) normalisés}` pour les IdRef connus non rejetés."""
    return _fetch_identifier_to_person_map(conn, "idref")


def fetch_orcid_to_person_map(conn: Connection) -> dict[str, tuple[int, str, str]]:
    """`{orcid: (person_id, nom, prénom) normalisés}` pour les ORCID connus non rejetés."""
    return _fetch_identifier_to_person_map(conn, "orcid")


def fetch_hal_account_to_person_map(conn: Connection) -> dict[str, tuple[int, str, str]]:
    """`{hal_person_id: (person_id, nom, prénom) normalisés}` pour les comptes HAL connus non rejetés."""
    return _fetch_identifier_to_person_map(conn, "hal_person_id")


def fetch_name_form_map(conn: Connection) -> dict[str, list[int]]:
    """Charge `person_name_forms` sous forme `{name_form: [person_id, ...]}`.

    Agrégation par `name_form` sur la table dénormalisée
    `(name_form, person_id, sources[])` : un dict trié par
    `person_id` croissant pour stabilité.
    """
    rows = conn.execute(
        text("""
            SELECT name_form,
                   array_agg(person_id ORDER BY person_id) AS person_ids
            FROM person_name_forms
            GROUP BY name_form
        """)
    ).all()
    return {r.name_form: r.person_ids for r in rows}


def fetch_rejected_person_ids_by_pub(conn: Connection) -> dict[int, frozenset[int]]:
    """Charge `rejected_authorships` sous forme `{publication_id: {person_id, ...}}`.

    Garde de matching : une paire `(publication, personne)` rejetée ne doit
    jamais être re-rattachée par la cascade. Le caller élimine ces personnes
    des candidats (cf. `domain.persons.matching.decide_person_match` et
    `decide_name_form_outcome`).
    """
    rows = conn.execute(
        text("""
            SELECT publication_id, array_agg(person_id) AS person_ids
            FROM rejected_authorships
            GROUP BY publication_id
        """)
    ).all()
    return {r.publication_id: frozenset(r.person_ids) for r in rows}


class PgPersonsCreateQueries(PersonsCreateQueries):
    """Adapter PostgreSQL pour `application.ports.persons_create.PersonsCreateQueries`."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        return fetch_unlinked_authorships(conn)

    def fetch_out_of_perimeter_candidates(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        return fetch_out_of_perimeter_candidates(conn)

    def fetch_linked_authorships(self, conn: Connection) -> list[LinkedAuthorshipRow]:
        return fetch_linked_authorships(conn)

    def fetch_idref_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]:
        return fetch_idref_to_person_map(conn)

    def fetch_orcid_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]:
        return fetch_orcid_to_person_map(conn)

    def fetch_hal_account_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]:
        return fetch_hal_account_to_person_map(conn)

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]:
        return fetch_name_form_map(conn)

    def fetch_rejected_person_ids_by_pub(self, conn: Connection) -> dict[int, frozenset[int]]:
        return fetch_rejected_person_ids_by_pub(conn)
