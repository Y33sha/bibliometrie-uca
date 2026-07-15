"""Lectures et réinitialisations pour la phase personnes.

Appelé par les orchestrateurs `application/pipeline/persons/{reset,cascade,purge}.py`.
Regroupe les SELECT du rattachement (comptes HAL, cross-source, IdRef/ORCID connus,
lookup `person_name_forms`) et les réinitialisations ordre-indépendantes de la phase :
re-orphelinage des signatures nominales à forme devenue ambiguë, suppression des
personnes vidées.
"""

from sqlalchemy import Connection, Row, text

from application.ports.pipeline.persons_create import (
    BareUnlinkedAuthorship,
    LinkedAuthorshipRow,
    PersonsCreateQueries,
)


def fetch_unlinked_authorships(conn: Connection) -> list[BareUnlinkedAuthorship]:
    """Liste les `source_authorships` in-perimeter non rattachés à une `person`, toutes sources confondues.

    Colonnes :

    - `orcid`, `hal_person_id`, `idref` : lus sur les identifiants de l'identité (`author_identifying_keys`, jointe par `identity_id`), sans filtre par source. `hal_person_id` n'est porté que par les authorships HAL. La restriction de l'ORCID aux sources fiables (cf. `ORCID_MATCH_SOURCES`) est appliquée côté cascade de matching, pas ici.
    - `roles` : remonté tel quel ; en pratique non vide uniquement pour theses (distingue auteur vs directeur).

    Le nom (last/first) est parsé côté caller via `parse_raw_author_name(full_name)`.

    Les lignes sans `raw_author_name` sont exclues toutes sources confondues (sans nom, l'authorship est inexploitable pour le matching personnes).
    """
    rows = conn.execute(
        text("""
            SELECT sa_auth.id AS authorship_id,
                   sa_auth.source::text AS source,
                   sa_auth.raw_author_name AS full_name,
                   aik.author_name_normalized,
                   aik.person_identifiers->>'orcid' AS orcid,
                   aik.person_identifiers->>'hal_person_id' AS hal_person_id,
                   aik.person_identifiers->>'idref' AS idref,
                   sa_auth.roles,
                   sd.publication_id,
                   sa_auth.author_position,
                   TRUE AS in_perimeter,
                   NULL::integer AS current_person_id
            FROM source_authorships sa_auth
            JOIN author_identifying_keys aik ON aik.id = sa_auth.identity_id
            JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
            JOIN publications pub ON pub.id = sd.publication_id
            WHERE sa_auth.person_id IS NULL
              AND sa_auth.in_perimeter = TRUE
              AND sd.publication_id IS NOT NULL
              AND sa_auth.raw_author_name IS NOT NULL
            ORDER BY sa_auth.id
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
        current_person_id=r.current_person_id,
    )


_OOP_PROJECTION = """
    sa_auth.id AS authorship_id,
    sa_auth.source::text AS source,
    sa_auth.raw_author_name AS full_name,
    aik.author_name_normalized,
    aik.person_identifiers->>'orcid' AS orcid,
    aik.person_identifiers->>'hal_person_id' AS hal_person_id,
    aik.person_identifiers->>'idref' AS idref,
    sa_auth.roles,
    sd.publication_id,
    sa_auth.author_position,
    FALSE AS in_perimeter,
    NULL::integer AS current_person_id
"""

# Conditions communes à toutes les branches : SA orpheline hors-périmètre,
# rattachée à une publication active (les hors périmètre ne sont pas matérialisées), avec un nom.
_OOP_COMMON_WHERE = """
    sa_auth.person_id IS NULL
    AND sa_auth.in_perimeter = FALSE
    AND sd.publication_id IS NOT NULL
    AND sa_auth.raw_author_name IS NOT NULL
"""


def _oop_identifier_branch(id_type: str, *, source_filter: str = "") -> str:
    """Branche « identifiant-ancré » : SA hors-périmètre dont l'identifiant
    `id_type` (jsonb) est déjà porté par une personne connue (non rejetée).

    Le rapprochement par valeur jsonb (`->>'{id_type}' = pi.id_value`) se fait
    sur `author_identifying_keys` (~645 k identités) et non plus sur les 19 M
    signatures : la valeur jsonb reste non indexable, mais scannée sur la table
    d'identités, 25× plus petite. On rejoint ensuite les signatures par
    `identity_id` (index `idx_sa_identity`). `person_identifiers ? '{id_type}'`
    et la restriction de source ORCID sont des filtres de correction, pas
    d'optimisation.
    """
    return f"""
        SELECT {_OOP_PROJECTION}
        FROM person_identifiers pi
        JOIN author_identifying_keys aik
            ON aik.person_identifiers->>'{id_type}' = pi.id_value
        JOIN source_authorships sa_auth ON sa_auth.identity_id = aik.id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN publications pub ON pub.id = sd.publication_id
        WHERE pi.id_type = '{id_type}'
          AND pi.status <> 'rejected'
          AND aik.person_identifiers ? '{id_type}'
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
    JOIN author_identifying_keys aik ON aik.id = sa_auth.identity_id
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
    """`source_authorships` déjà rattachées par un canal **ferme** (identifiant / nom / épinglage), toutes sources confondues.

    Sert d'index d'ancrage au matching cross-source. Les liens cross-source eux-mêmes en sont exclus (`resolution_mode <> 'cross_source'`) : un résultat cross-source n'ancre jamais un autre. Ramène `raw_author_name` ; le caller parse via `parse_raw_author_name` uniformément.
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
              AND sa_auth.resolution_mode IS DISTINCT FROM 'cross_source'
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


def fetch_cross_source_linked(conn: Connection) -> list[BareUnlinkedAuthorship]:
    """Signatures déjà liées **en cross-source** (non épinglées), à re-juger contre les ancres fermes.

    Même projection que les non-liées, plus `current_person_id` = le `person_id` courant. Une signature cross-source peut porter un identifiant ou un nom qui matche une personne existante : la ré-évaluation passe par toute la cascade, d'où les colonnes d'identifiant.
    """
    rows = conn.execute(
        text("""
            SELECT sa_auth.id AS authorship_id,
                   sa_auth.source::text AS source,
                   sa_auth.raw_author_name AS full_name,
                   aik.author_name_normalized,
                   aik.person_identifiers->>'orcid' AS orcid,
                   aik.person_identifiers->>'hal_person_id' AS hal_person_id,
                   aik.person_identifiers->>'idref' AS idref,
                   sa_auth.roles,
                   sd.publication_id,
                   sa_auth.author_position,
                   sa_auth.in_perimeter,
                   sa_auth.person_id AS current_person_id
            FROM source_authorships sa_auth
            JOIN author_identifying_keys aik ON aik.id = sa_auth.identity_id
            JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
            WHERE sa_auth.resolution_mode = 'cross_source'
              AND sd.publication_id IS NOT NULL
              AND sa_auth.raw_author_name IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM confirmed_authorships ca WHERE ca.source_authorship_id = sa_auth.id
              )
            ORDER BY sa_auth.id
        """)
    ).all()
    return [_to_bare(r) for r in rows]


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
    `(name_form, person_id, sources[], status)` : un dict trié par
    `person_id` croissant pour stabilité.

    Les liens `status = 'rejected'` sont exclus : une forme de nom rejetée pour une
    personne ne doit plus la proposer au matching par nom (verrou de non-retour).
    """
    rows = conn.execute(
        text("""
            SELECT name_form,
                   array_agg(person_id ORDER BY person_id) AS person_ids
            FROM person_name_forms
            WHERE status <> 'rejected'
            GROUP BY name_form
        """)
    ).all()
    return {r.name_form: r.person_ids for r in rows}


def fetch_name_form_status_map(conn: Connection) -> dict[tuple[str, int], str]:
    """Charge les verdicts de lien forme↔personne : `{(name_form, person_id): verdict}`.

    Sert à la corroboration du matching par identifiant : quand un identifiant résout
    vers une personne, le verdict du couple (forme de la signature, personne) tranche
    sans test de compatibilité de nom — `confirmed` corrobore, `rejected` refuse ; en
    l'absence de verdict, on retombe sur la comparaison par tokens.

    Le verdict combine le statut admin et l'appartenance au nom canonique : un rejet
    admin l'emporte ; une confirmation admin (`status = 'confirmed'`) ou une forme
    dérivée du nom canonique (`'persons' ∈ sources`) corrobore. Les formes seulement
    `pending` et non canoniques sont omises.
    """
    rows = conn.execute(
        text("""
            SELECT name_form, person_id,
                   CASE WHEN status = 'rejected' THEN 'rejected' ELSE 'confirmed' END AS status
            FROM person_name_forms
            WHERE status = 'rejected' OR status = 'confirmed' OR 'persons' = ANY(sources)
        """)
    ).all()
    return {(r.name_form, r.person_id): r.status for r in rows}


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


def fetch_identifier_consensus(conn: Connection, id_type: str, values: list[str]) -> dict[str, str]:
    """Nom-autorité consensuel des valeurs d'identifiant fournies.

    Pour chaque valeur, l'`author_name_normalized` porté par le plus de **signatures**
    (poids en signatures, pas en identités — 99 correctes l'emportent sur 1 corrompue).
    Query ciblée sur les seules valeurs demandées : on part des identités portant l'une
    d'elles (`author_identifying_keys`, filtré par `person_identifiers->>id_type`), jointes
    aux `source_authorships` (index `identity_id`) pour le comptage — jamais de scan
    complet. Pour l'ORCID, seules les sources à dépôt auteur comptent, comme au matching.
    """
    if not values:
        return {}
    source_filter = "AND sa.source IN ('crossref', 'openalex', 'hal')" if id_type == "orcid" else ""
    rows = conn.execute(
        text(f"""
            SELECT DISTINCT ON (id_value) id_value, author_name_normalized
            FROM (
                SELECT aik.person_identifiers->>:id_type AS id_value,
                       aik.author_name_normalized,
                       count(*) AS n
                FROM author_identifying_keys aik
                JOIN source_authorships sa ON sa.identity_id = aik.id
                WHERE aik.person_identifiers->>:id_type = ANY(:values)
                  AND aik.author_name_normalized IS NOT NULL
                  {source_filter}
                GROUP BY 1, 2
            ) t
            ORDER BY id_value, n DESC, author_name_normalized
        """),
        {"id_type": id_type, "values": list(values)},
    ).all()
    return {r.id_value: r.author_name_normalized for r in rows}


def fetch_person_name_forms(
    conn: Connection, person_ids: list[int]
) -> dict[int, tuple[str, str, list[str]]]:
    """`{person_id: (nom_normalisé, prénom_normalisé, [formes confirmées])}`.

    Les formes `confirmed` accompagnent le nom-prénom canonique pour l'arbitrage des
    transferts (`form_matches_person`) : une personne peut matcher le consensus par une
    forme validée que le canonique ne recouvre pas (changement de nom). Les formes
    `pending` — vecteur de contamination des captures — sont exclues.
    """
    if not person_ids:
        return {}
    rows = conn.execute(
        text("""
            SELECT p.id,
                   p.last_name_normalized AS ln,
                   p.first_name_normalized AS fn,
                   COALESCE(
                       array_agg(nf.name_form) FILTER (WHERE nf.status = 'confirmed'),
                       ARRAY[]::text[]
                   ) AS confirmed_forms
            FROM persons p
            LEFT JOIN person_name_forms nf ON nf.person_id = p.id
            WHERE p.id = ANY(:ids)
            GROUP BY p.id, p.last_name_normalized, p.first_name_normalized
        """),
        {"ids": list(person_ids)},
    ).all()
    return {r.id: (r.ln or "", r.fn or "", list(r.confirmed_forms)) for r in rows}


def fetch_identifier_owners(conn: Connection, id_type: str) -> dict[str, tuple[int, str]]:
    """`{id_value: (person_id, status)}` — propriétaires non rejetés d'un type d'identifiant.

    Sert au balayage frontal des conflits d'attribution : le propriétaire attribué d'une
    valeur, à confronter aux personnes qui en portent des signatures.
    """
    rows = conn.execute(
        text("""
            SELECT id_value, person_id, status
            FROM person_identifiers
            WHERE id_type = :t AND status <> 'rejected'
        """),
        {"t": id_type},
    ).all()
    return {r.id_value: (r.person_id, r.status) for r in rows}


def fetch_identifier_bearer_persons(
    conn: Connection, id_type: str, sources: tuple[str, ...] | None = None
) -> list[tuple[str, int]]:
    """Couples `(id_value, person_id)` : les personnes portant des signatures d'une valeur.

    Agrégat sur les signatures rattachées dont l'identité porte le type d'identifiant.
    `sources` restreint aux sources fiables (ORCID déposé par l'auteur, cf.
    `ORCID_MATCH_SOURCES`) ; absent, toutes sources.
    """
    source_filter = "AND sa.source = ANY(:sources)" if sources else ""
    params: dict[str, object] = {"id_type": id_type}
    if sources:
        params["sources"] = list(sources)
    rows = conn.execute(
        text(f"""
            SELECT aik.person_identifiers->>:id_type AS id_value, sa.person_id
            FROM source_authorships sa
            JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE aik.person_identifiers ? :id_type
              AND sa.person_id IS NOT NULL
              {source_filter}
            GROUP BY 1, 2
        """),
        params,
    ).all()
    return [(r.id_value, r.person_id) for r in rows]


def null_identifier_signatures(
    conn: Connection, id_type: str, id_value: str, old_owner_person_id: int
) -> int:
    """Détache les signatures affectées par le transfert d'une valeur d'identifiant.

    Après réattribution d'une valeur de l'ancien propriétaire vers la personne du consensus,
    les signatures portées sur l'ancien propriétaire, résolues **par identifiant**
    (`resolution_mode = 'identifier'`), dont l'identité porte cette valeur et non épinglées,
    repassent à NULL : la cascade les re-résout contre la carte corrigée. Les signatures
    nominales portant la valeur ne bougent pas (leur `person_id` ne dépend pas d'elle).
    Retourne le nombre de signatures détachées.
    """
    return conn.execute(
        text("""
            UPDATE source_authorships sa
            SET person_id = NULL, resolution_mode = NULL
            FROM author_identifying_keys aik
            WHERE sa.identity_id = aik.id
              AND sa.person_id = :old_owner
              AND sa.resolution_mode = 'identifier'
              AND aik.person_identifiers->>:id_type = :id_value
              AND NOT EXISTS (
                  SELECT 1 FROM confirmed_authorships ca WHERE ca.source_authorship_id = sa.id
              )
        """),
        {"old_owner": old_owner_person_id, "id_type": id_type, "id_value": id_value},
    ).rowcount


def reorphan_ambiguous_nominal(conn: Connection) -> int:
    """Re-orpheline les signatures nominales dont la forme de nom est devenue ambiguë.

    Réinitialisation ordre-indépendante du canal nominal : une signature résolue par
    forme de nom (`resolution_mode = 'name'`), non épinglée par l'admin
    (`confirmed_authorships`), dont l'`author_name_normalized` désigne au moins deux
    personnes dans `person_name_forms` (hors `rejected`), repasse à NULL — `person_id` et
    mode. Le sur-regroupement (une forme réduite collée au seul candidat présent avant
    l'arrivée de l'homonyme qui la départage) se défait ainsi dès que l'homonyme coexiste,
    quel que soit l'ordre d'ingestion. Retourne le nombre de signatures re-orphelinées.
    """
    return conn.execute(
        text("""
            UPDATE source_authorships sa
            SET person_id = NULL, resolution_mode = NULL
            FROM author_identifying_keys aik
            WHERE sa.identity_id = aik.id
              AND sa.resolution_mode = 'name'
              AND NOT EXISTS (
                  SELECT 1 FROM confirmed_authorships ca WHERE ca.source_authorship_id = sa.id
              )
              AND aik.author_name_normalized IN (
                  SELECT name_form
                  FROM person_name_forms
                  WHERE status <> 'rejected'
                  GROUP BY name_form
                  HAVING count(DISTINCT person_id) >= 2
              )
        """)
    ).rowcount


def detach_authorships(conn: Connection, authorship_ids: list[int]) -> int:
    """Détache un lot de signatures (`person_id` et `resolution_mode` → NULL), par id.

    Sert aux liens cross-source devenus sans appui : une signature dont l'ancre ferme a disparu ce run et que la cascade n'a pas re-résolue. Retourne le nombre détaché.
    """
    if not authorship_ids:
        return 0
    return conn.execute(
        text("""
            UPDATE source_authorships sa
            SET person_id = NULL, resolution_mode = NULL
            WHERE sa.id = ANY(:ids)
              AND NOT EXISTS (
                  SELECT 1 FROM confirmed_authorships ca WHERE ca.source_authorship_id = sa.id
              )
        """),
        {"ids": authorship_ids},
    ).rowcount


def delete_empty_persons(conn: Connection) -> int:
    """Supprime les personnes vidées de toute signature, hors référentiel RH.

    Après le re-orphelinage, une personne purement nominale peut se retrouver sans aucune
    `source_authorships` — typiquement une forme réduite dont les signatures ont rejoint la
    forme pleine. La supprimer retire ses formes de nom canoniques (FK `CASCADE`), ce qui
    désambiguïse la forme réduite et laisse les orphelines se re-attacher au run suivant.
    Une personne vide est nécessairement non curée (la curation ne vit que sur des personnes
    à publications) ; les notices RH sont protégées, personnes légitimes sans publication
    dans le corpus. Retourne le nombre de personnes supprimées.
    """
    return conn.execute(
        text("""
            DELETE FROM persons p
            WHERE NOT EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.person_id = p.id)
              AND NOT EXISTS (SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id)
        """)
    ).rowcount


class PgPersonsCreateQueries(PersonsCreateQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.persons_create.PersonsCreateQueries`."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        return fetch_unlinked_authorships(conn)

    def fetch_out_of_perimeter_candidates(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        return fetch_out_of_perimeter_candidates(conn)

    def fetch_linked_authorships(self, conn: Connection) -> list[LinkedAuthorshipRow]:
        return fetch_linked_authorships(conn)

    def fetch_cross_source_linked(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        return fetch_cross_source_linked(conn)

    def fetch_idref_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]:
        return fetch_idref_to_person_map(conn)

    def fetch_orcid_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]:
        return fetch_orcid_to_person_map(conn)

    def fetch_hal_account_to_person_map(self, conn: Connection) -> dict[str, tuple[int, str, str]]:
        return fetch_hal_account_to_person_map(conn)

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]:
        return fetch_name_form_map(conn)

    def fetch_name_form_status_map(self, conn: Connection) -> dict[tuple[str, int], str]:
        return fetch_name_form_status_map(conn)

    def fetch_rejected_person_ids_by_pub(self, conn: Connection) -> dict[int, frozenset[int]]:
        return fetch_rejected_person_ids_by_pub(conn)

    def fetch_identifier_consensus(
        self, conn: Connection, id_type: str, values: list[str]
    ) -> dict[str, str]:
        return fetch_identifier_consensus(conn, id_type, values)

    def fetch_person_name_forms(
        self, conn: Connection, person_ids: list[int]
    ) -> dict[int, tuple[str, str, list[str]]]:
        return fetch_person_name_forms(conn, person_ids)

    def fetch_identifier_owners(self, conn: Connection, id_type: str) -> dict[str, tuple[int, str]]:
        return fetch_identifier_owners(conn, id_type)

    def fetch_identifier_bearer_persons(
        self, conn: Connection, id_type: str, sources: tuple[str, ...] | None = None
    ) -> list[tuple[str, int]]:
        return fetch_identifier_bearer_persons(conn, id_type, sources)

    def null_identifier_signatures(
        self, conn: Connection, id_type: str, id_value: str, old_owner_person_id: int
    ) -> int:
        return null_identifier_signatures(conn, id_type, id_value, old_owner_person_id)

    def reorphan_ambiguous_nominal(self, conn: Connection) -> int:
        return reorphan_ambiguous_nominal(conn)

    def detach_authorships(self, conn: Connection, authorship_ids: list[int]) -> int:
        return detach_authorships(conn, authorship_ids)

    def delete_empty_persons(self, conn: Connection) -> int:
        return delete_empty_persons(conn)
