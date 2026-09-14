"""Lectures et réinitialisations pour la phase personnes.

Appelé par les orchestrateurs `application/pipeline/persons/{reset,cascade,purge}.py`. Regroupe les SELECT du rattachement (comptes HAL, cross-source, IdRef/ORCID connus, lookup `person_name_forms`) et les réinitialisations ordre-indépendantes de la phase : re-orphelinage des signatures nominales à forme devenue ambiguë, suppression des personnes vidées.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import Connection, Row, bindparam, text

from application.ports.pipeline.persons.matching import (
    BareUnlinkedAuthorship,
    IdentityIdentifier,
    LinkedAuthorshipRow,
    MisplacedNeutralizations,
    PersonsMatchingQueries,
)
from domain.persons.identifiers import (
    AttributionStatus,
    IdentifierNeutralization,
    IdentifierOrigin,
    PersonIdentifierType,
)
from domain.persons.matching import (
    ORCID_MATCH_SOURCES,
    IdentifiedPerson,
    PersonNameForms,
    ResolutionMode,
)
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.sql_fragments import identifier_neutralized, usable_identifier

# Condition vraie quand la signature `sa` neutralise l'identifiant du paramètre `:id_type`.
_ID_TYPE_NEUTRALIZED = identifier_neutralized(":id_type")
# Même condition, restreinte au partage de la valeur entre signatures d'un document.
_ID_TYPE_SHARED = identifier_neutralized(":id_type", reason=IdentifierNeutralization.SHARED.value)
_MISPLACED = IdentifierNeutralization.MISPLACED.value


def _usable(id_type: str) -> str:
    """Valeur de l'identifiant `id_type` de la signature `sa_auth`, NULL quand elle le neutralise."""
    return usable_identifier(f"'{id_type}'", signature="sa_auth")


def _to_bare(r: Row[tuple[object, ...]]) -> BareUnlinkedAuthorship:
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


# Colonnes communes des projections d'authorship non-liée (`BareUnlinkedAuthorship`).
# Chaque requête y ajoute ses deux colonnes finales `in_perimeter` et `current_person_id`.
# Un identifiant que la signature neutralise vaut NULL.
_BARE_PROJECTION_HEAD = f"""
    sa_auth.id AS authorship_id,
    sa_auth.source::text AS source,
    sa_auth.raw_author_name AS full_name,
    aik.author_name_normalized,
    {_usable("orcid")} AS orcid,
    {_usable("hal_person_id")} AS hal_person_id,
    {_usable("idref")} AS idref,
    sa_auth.roles,
    sd.publication_id,
    sa_auth.author_position"""

_OOP_PROJECTION = f"""{_BARE_PROJECTION_HEAD},
    FALSE AS in_perimeter,
    NULL::integer AS current_person_id"""

# Conditions communes à toutes les branches : SA orpheline hors-périmètre,
# rattachée à une publication active (les hors périmètre ne sont pas matérialisées), avec un nom.
_OOP_COMMON_WHERE = """
    sa_auth.person_id IS NULL
    AND sa_auth.in_perimeter = FALSE
    AND sd.publication_id IS NOT NULL
    AND sa_auth.raw_author_name IS NOT NULL
"""


def _oop_identifier_branch(id_type: str, *, source_filter: str = "") -> str:
    """Branche « identifiant-ancré » : signature hors-périmètre dont l'identifiant `id_type` (jsonb) est déjà porté par une personne connue (non rejetée).

    Le rapprochement par valeur jsonb (`->>'{id_type}' = pi.id_value`) porte sur `author_identifying_keys` (~645 k identités), non sur les 19 M signatures : la valeur jsonb reste non indexable, mais scannée sur la table d'identités, 25× plus petite. On rejoint ensuite les signatures par `identity_id` (index `idx_sa_identity`). `person_identifiers ? '{id_type}'`, la neutralisation par la signature et la restriction de source ORCID sont des filtres de correction, pas d'optimisation.
    """
    neutralized = identifier_neutralized(f"'{id_type}'", "sa_auth")
    return f"""
        SELECT {_OOP_PROJECTION}
        FROM person_identifiers pi
        JOIN author_identifying_keys aik
            ON aik.person_identifiers->>'{id_type}' = pi.id_value
        JOIN source_authorships sa_auth ON sa_auth.identity_id = aik.id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN publications pub ON pub.id = sd.publication_id
        WHERE pi.id_type = '{id_type}'
          AND pi.status <> '{AttributionStatus.REJECTED.value}'
          AND aik.person_identifiers ? '{id_type}'
          AND NOT {neutralized}
          {source_filter}
          AND {_OOP_COMMON_WHERE}
    """


# Branche « cross-source-ancrée » : signature hors-périmètre à une (publication,
# position) où une autre est déjà rattachée. Self-join sur `linked.author_position`
# (position source, clé de `linked_index`) ; le matching nom-compatible est tranché
# côté Python (`decide_cross_source_match`).
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

# ORCID : restreint aux sources à ORCID déposé par l'auteur (`ORCID_MATCH_SOURCES` du domaine,
# passé en bind param `:orcid_sources`). L'ORCID WoS/ScanR est dérivé algorithmiquement, pas un
# signal de matching.
_OOP_CANDIDATES_SQL = " UNION ".join(
    [
        _oop_identifier_branch(
            PersonIdentifierType.ORCID, source_filter="AND sa_auth.source = ANY(:orcid_sources)"
        ),
        _oop_identifier_branch(PersonIdentifierType.IDREF),
        _oop_identifier_branch(PersonIdentifierType.HAL_PERSON_ID),
        _OOP_CROSS_SOURCE_BRANCH,
    ]
)


class PgPersonsMatchingQueries(PersonsMatchingQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.persons.matching.PersonsMatchingQueries`."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        """Colonnes de la projection des `source_authorships` in-perimeter non liés :

        - `orcid`, `hal_person_id`, `idref` : lus sur les identifiants de l'identité (`author_identifying_keys`, jointe par `identity_id`), sans filtre par source. `hal_person_id` n'est porté que par les authorships HAL. La restriction de l'ORCID aux sources fiables (cf. `ORCID_MATCH_SOURCES`) est appliquée côté cascade de matching, pas ici.
        - `roles` : remonté tel quel ; en pratique non vide uniquement pour theses (distingue auteur vs directeur).

        Le nom (last/first) est parsé côté caller via `parse_raw_author_name(full_name)`. Les lignes sans `raw_author_name` sont exclues toutes sources confondues (sans nom, l'authorship est inexploitable pour le matching personnes).
        """
        rows = conn.execute(
            text(f"""
                SELECT {_BARE_PROJECTION_HEAD},
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

    def fetch_out_of_perimeter_candidates(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        """Union des quatre branches d'accès, dédupliquée en SQL (`UNION`) : une même signature peut être candidate par plusieurs chemins (identifiant fort partagé, ou ancrage cross-source sur une position déjà liée). La cascade côté orchestrateur arbitre ensuite (les barreaux nom/création y sont neutralisés pour ces candidats hors-périmètre).

        Seules les signatures ancrées sur une personne existante (identifiant partagé) ou sur une position déjà rattachée (cross-source) sont ramenées. La requête reparcourt cet ensemble à chaque run, et la branche cross-source porte l'essentiel de son coût.
        """
        rows = conn.execute(
            text(_OOP_CANDIDATES_SQL), {"orcid_sources": list(ORCID_MATCH_SOURCES)}
        ).all()
        return [_to_bare(r) for r in rows]

    def fetch_linked_authorships(self, conn: Connection) -> list[LinkedAuthorshipRow]:
        """Sert d'index d'ancrage au matching cross-source. Les liens cross-source eux-mêmes en sont exclus (`resolution_mode <> 'cross_source'`) : un résultat cross-source n'en ancre aucun autre. Ramène `raw_author_name` ; le caller parse via `parse_raw_author_name` uniformément."""
        rows = conn.execute(
            text(f"""
                SELECT sa_auth.person_id, sa_auth.author_position,
                       sd.publication_id,
                       sa_auth.raw_author_name AS full_name,
                       sa_auth.source::text AS source
                FROM source_authorships sa_auth
                JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
                WHERE sa_auth.person_id IS NOT NULL
                  AND sa_auth.resolution_mode IS DISTINCT FROM '{ResolutionMode.CROSS_SOURCE.value}'
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

    def fetch_cross_source_linked(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        """Même projection que les non-liées, plus `current_person_id` = le `person_id` courant. Une signature cross-source peut porter un identifiant ou un nom qui matche une personne existante : la ré-évaluation passe par toute la cascade, d'où les colonnes d'identifiant."""
        rows = conn.execute(
            text(f"""
                SELECT {_BARE_PROJECTION_HEAD},
                       sa_auth.in_perimeter,
                       sa_auth.person_id AS current_person_id
                FROM source_authorships sa_auth
                JOIN author_identifying_keys aik ON aik.id = sa_auth.identity_id
                JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
                WHERE sa_auth.resolution_mode = '{ResolutionMode.CROSS_SOURCE.value}'
                  AND sd.publication_id IS NOT NULL
                  AND sa_auth.raw_author_name IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM confirmed_authorships ca WHERE ca.source_authorship_id = sa_auth.id
                  )
                ORDER BY sa_auth.id
            """)
        ).all()
        return [_to_bare(r) for r in rows]

    def fetch_identifier_to_person_map(
        self, conn: Connection, id_type: str
    ) -> dict[str, IdentifiedPerson]:
        """Le nom normalisé de la personne ciblée accompagne le `person_id` : la cascade corrobore le match identifiant par le nom (`decide_match_by_identifier`), refusant un identifiant porté par une signature étrangère."""
        rows = conn.execute(
            text(f"""
                SELECT pi.id_value, pi.person_id,
                       p.last_name_normalized AS ln, p.first_name_normalized AS fn
                FROM person_identifiers pi
                JOIN persons p ON p.id = pi.person_id
                WHERE pi.id_type = :id_type
                  AND pi.status != '{AttributionStatus.REJECTED.value}'
            """),
            {"id_type": id_type},
        ).all()
        return {r.id_value: IdentifiedPerson(r.person_id, r.ln or "", r.fn or "") for r in rows}

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]:
        """Agrégation par `name_form` sur la table dénormalisée `(name_form, person_id, sources[], status)` : un dict trié par `person_id` croissant pour stabilité. Les liens `status = 'rejected'` sont exclus : une forme de nom rejetée pour une personne reste écartée du matching par nom (verrou de non-retour)."""
        rows = conn.execute(
            text(f"""
                SELECT name_form,
                       array_agg(person_id ORDER BY person_id) AS person_ids
                FROM person_name_forms
                WHERE status <> '{AttributionStatus.REJECTED.value}'
                GROUP BY name_form
            """)
        ).all()
        return {r.name_form: r.person_ids for r in rows}

    def fetch_name_form_status_map(self, conn: Connection) -> dict[tuple[str, int], str]:
        """Sert à la corroboration du matching par identifiant : quand un identifiant résout vers une personne, le verdict du couple (forme de la signature, personne) tranche sans test de compatibilité de nom — `confirmed` corrobore, `rejected` refuse ; en l'absence de verdict, on retombe sur la comparaison par tokens.

        Le verdict combine le statut admin et l'appartenance au nom canonique : un rejet admin l'emporte ; une confirmation admin (`status = 'confirmed'`) ou une forme dérivée du nom canonique (`'persons' ∈ sources`) corrobore. Les formes seulement `pending` et non canoniques sont omises.
        """
        rows = conn.execute(
            text(f"""
                SELECT name_form, person_id,
                       CASE WHEN status = '{AttributionStatus.REJECTED.value}'
                            THEN '{AttributionStatus.REJECTED.value}'
                            ELSE '{AttributionStatus.CONFIRMED.value}' END AS status
                FROM person_name_forms
                WHERE status = '{AttributionStatus.REJECTED.value}'
                   OR status = '{AttributionStatus.CONFIRMED.value}'
                   OR '{CANONICAL_NAME_FORM_SOURCE}' = ANY(sources)
            """)
        ).all()
        return {(r.name_form, r.person_id): r.status for r in rows}

    def fetch_rejected_person_ids_by_pub(self, conn: Connection) -> dict[int, frozenset[int]]:
        """Garde de matching : une paire `(publication, personne)` rejetée reste hors de portée de la cascade, jamais re-rattachée. Le caller élimine ces personnes des candidats (cf. `domain.persons.matching.decide_person_match` et `decide_name_form_outcome`)."""
        rows = conn.execute(
            text("""
                SELECT publication_id, array_agg(person_id) AS person_ids
                FROM rejected_authorships
                GROUP BY publication_id
            """)
        ).all()
        return {r.publication_id: frozenset(r.person_ids) for r in rows}

    def fetch_identifier_votes(self, conn: Connection, id_type: str) -> dict[str, dict[str, int]]:
        """Pour chaque valeur du type, le nombre de **signatures** qui la portent sous chaque `author_name_normalized` (poids en signatures, pas en identités — 99 correctes l'emportent sur 1 corrompue). Le rapprochement part des identités portant le type (`author_identifying_keys`), jointes aux `source_authorships` (index `identity_id`) pour le comptage.

        Une signature qui neutralise la valeur pour cause de partage ne vote pas. Une signature qui la neutralise comme mal placée vote : le consensus ne dépend ainsi que des données, pas des requalifications précédentes. Pour l'ORCID, seules les sources à dépôt auteur comptent, comme au matching."""
        source_filter = (
            "AND sa.source = ANY(:orcid_sources)" if id_type == PersonIdentifierType.ORCID else ""
        )
        params: dict[str, object] = {"id_type": id_type}
        if id_type == PersonIdentifierType.ORCID:
            params["orcid_sources"] = list(ORCID_MATCH_SOURCES)
        rows = conn.execute(
            text(f"""
                SELECT aik.person_identifiers->>:id_type AS id_value,
                       aik.author_name_normalized AS name,
                       count(*) AS votes
                FROM author_identifying_keys aik
                JOIN source_authorships sa ON sa.identity_id = aik.id
                WHERE aik.person_identifiers ? :id_type
                  AND aik.author_name_normalized IS NOT NULL
                  AND NOT {_ID_TYPE_SHARED}
                  {source_filter}
                GROUP BY 1, 2
            """),
            params,
        ).all()
        votes: dict[str, dict[str, int]] = {}
        for r in rows:
            votes.setdefault(r.id_value, {})[r.name] = int(r.votes)
        return votes

    def fetch_identity_identifiers(
        self, conn: Connection, id_type: str
    ) -> list[IdentityIdentifier]:
        """Identités portant un identifiant du type, avec leur nom normalisé."""
        rows = conn.execute(
            text("""
                SELECT id, author_name_normalized AS name, person_identifiers->>:id_type AS value
                FROM author_identifying_keys
                WHERE person_identifiers ? :id_type AND author_name_normalized IS NOT NULL
            """),
            {"id_type": id_type},
        ).all()
        return [IdentityIdentifier(r.id, r.name, r.value) for r in rows]

    def write_misplaced_neutralizations(
        self, conn: Connection, misplaced: Mapping[int, Sequence[str]]
    ) -> MisplacedNeutralizations:
        """Réécrit les neutralisations `misplaced` de toutes les signatures : celles des identités de `misplaced` (`{identity_id: types d'identifiant}`) sont posées, les autres effacées. Une neutralisation `shared` du même identifiant l'emporte. Seules les lignes dont la carte change sont écrites."""
        payload = [
            {"identity_id": identity_id, "carte": dict.fromkeys(id_types, _MISPLACED)}
            for identity_id, id_types in misplaced.items()
        ]
        rows = conn.execute(
            text(f"""
                WITH marques AS (
                    SELECT m.identity_id, m.carte
                    FROM jsonb_to_recordset(:payload) AS m(identity_id integer, carte jsonb)
                ),
                cibles AS (
                    SELECT sa.id,
                           sa.neutralized_identifiers AS avant,
                           NULLIF(
                               coalesce(m.carte, '{{}}'::jsonb)
                               || coalesce(
                                   (SELECT jsonb_object_agg(e.k, e.v)
                                      FROM jsonb_each(sa.neutralized_identifiers) AS e(k, v)
                                     WHERE e.v <> to_jsonb('{_MISPLACED}'::text)),
                                   '{{}}'::jsonb),
                               '{{}}'::jsonb
                           ) AS apres
                    FROM source_authorships sa
                    LEFT JOIN marques m ON m.identity_id = sa.identity_id
                    WHERE m.identity_id IS NOT NULL
                       OR (sa.neutralized_identifiers IS NOT NULL
                           AND EXISTS (
                               SELECT 1 FROM jsonb_each_text(sa.neutralized_identifiers) AS e(k, v)
                               WHERE e.v = '{_MISPLACED}'
                           ))
                ),
                modifiees AS (
                    UPDATE source_authorships sa
                    SET neutralized_identifiers = c.apres
                    FROM cibles c
                    WHERE sa.id = c.id AND c.apres IS DISTINCT FROM c.avant
                    RETURNING sa.id, sa.resolution_mode, c.avant, c.apres
                )
                SELECT id,
                       coalesce(resolution_mode = '{ResolutionMode.IDENTIFIER.value}', false)
                       AND NOT EXISTS (
                           SELECT 1 FROM confirmed_authorships ca
                           WHERE ca.source_authorship_id = modifiees.id
                       ) AS a_detacher
                FROM modifiees
                WHERE EXISTS (
                    SELECT 1 FROM jsonb_object_keys(coalesce(apres, '{{}}'::jsonb)) AS k
                    WHERE NOT coalesce(avant ? k, false)
                )
                ORDER BY id
            """).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": payload},
        ).all()
        return MisplacedNeutralizations(
            neutralized=len(rows), to_detach=[r.id for r in rows if r.a_detacher]
        )

    def fetch_person_name_forms(
        self, conn: Connection, person_ids: list[int]
    ) -> dict[int, PersonNameForms]:
        """Les formes `confirmed` accompagnent le nom-prénom canonique pour l'arbitrage des transferts (`form_matches_person`) : une personne peut matcher le consensus par une forme validée que le canonique ne recouvre pas (changement de nom). Les formes `pending` — vecteur de contamination des captures — sont exclues."""
        if not person_ids:
            return {}
        rows = conn.execute(
            text(f"""
                SELECT p.id,
                       p.last_name_normalized AS ln,
                       p.first_name_normalized AS fn,
                       COALESCE(
                           array_agg(nf.name_form)
                               FILTER (WHERE nf.status = '{AttributionStatus.CONFIRMED.value}'),
                           ARRAY[]::text[]
                       ) AS confirmed_forms
                FROM persons p
                LEFT JOIN person_name_forms nf ON nf.person_id = p.id
                WHERE p.id = ANY(:ids)
                GROUP BY p.id, p.last_name_normalized, p.first_name_normalized
            """),
            {"ids": list(person_ids)},
        ).all()
        return {
            r.id: PersonNameForms(r.ln or "", r.fn or "", list(r.confirmed_forms)) for r in rows
        }

    def fetch_identifier_owners(self, conn: Connection, id_type: str) -> dict[str, tuple[int, str]]:
        """Sert au balayage frontal des conflits d'attribution : le propriétaire attribué d'une valeur, à confronter aux personnes qui en portent des signatures."""
        rows = conn.execute(
            text(f"""
                SELECT id_value, person_id, status
                FROM person_identifiers
                WHERE id_type = :t AND status <> '{AttributionStatus.REJECTED.value}'
            """),
            {"t": id_type},
        ).all()
        return {r.id_value: (r.person_id, r.status) for r in rows}

    def fetch_identifier_bearer_persons(
        self, conn: Connection, id_type: str, sources: tuple[str, ...] | None = None
    ) -> list[tuple[str, int]]:
        """Agrégat sur les signatures rattachées dont l'identité porte le type d'identifiant. `sources` restreint aux sources fiables (ORCID déposé par l'auteur, cf. `ORCID_MATCH_SOURCES`) ; absent, toutes sources."""
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
                  AND NOT {_ID_TYPE_NEUTRALIZED}
                  AND sa.person_id IS NOT NULL
                  {source_filter}
                GROUP BY 1, 2
            """),
            params,
        ).all()
        return [(r.id_value, r.person_id) for r in rows]

    def enforce_confirmed_authorships(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                UPDATE source_authorships sa
                SET person_id = ca.person_id
                FROM confirmed_authorships ca
                WHERE ca.source_authorship_id = sa.id
                  AND sa.person_id IS DISTINCT FROM ca.person_id
            """)
        ).rowcount

    def null_identifier_signatures(
        self, conn: Connection, id_type: str, id_value: str, old_owner_person_id: int
    ) -> int:
        """Après réattribution d'une valeur de l'ancien propriétaire vers la personne du consensus, les signatures portées sur l'ancien propriétaire, résolues **par identifiant** (`resolution_mode = 'identifier'`), dont l'identité porte cette valeur et non épinglées, repassent à NULL : la cascade les re-résout contre la carte corrigée. Les signatures nominales portant la valeur ne bougent pas (leur `person_id` ne dépend pas d'elle)."""
        return conn.execute(
            text(f"""
                UPDATE source_authorships sa
                SET person_id = NULL, resolution_mode = NULL
                FROM author_identifying_keys aik
                WHERE sa.identity_id = aik.id
                  AND sa.person_id = :old_owner
                  AND sa.resolution_mode = '{ResolutionMode.IDENTIFIER.value}'
                  AND aik.person_identifiers->>:id_type = :id_value
                  AND NOT {_ID_TYPE_NEUTRALIZED}
                  AND NOT EXISTS (
                      SELECT 1 FROM confirmed_authorships ca WHERE ca.source_authorship_id = sa.id
                  )
            """),
            {"old_owner": old_owner_person_id, "id_type": id_type, "id_value": id_value},
        ).rowcount

    def reorphan_ambiguous_nominal(self, conn: Connection) -> int:
        """Une signature résolue par forme de nom (`resolution_mode = 'name'`), non épinglée par l'admin (`confirmed_authorships`), dont l'`author_name_normalized` désigne au moins deux personnes dans `person_name_forms` (hors `rejected`), repasse à NULL — `person_id` et mode. Le sur-regroupement (une forme réduite collée au seul candidat présent avant l'arrivée de l'homonyme qui la départage) se défait ainsi dès que l'homonyme coexiste, quel que soit l'ordre d'ingestion.

        Comme la cascade, le décompte écarte les personnes rejetées pour la publication de la signature (`rejected_authorships`) : un rejet qui laisse un seul candidat rend la forme univoque pour cette signature.
        """
        # Les candidates (nominales, non épinglées, à forme ambiguë) sont matérialisées d'abord : le
        # décompte par signature et la jointure vers la publication ne portent que sur elles.
        return conn.execute(
            text(f"""
                WITH candidates AS MATERIALIZED (
                    SELECT sa.id, sa.source_publication_id,
                           aik.author_name_normalized AS name_form
                    FROM source_authorships sa
                    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                    WHERE sa.resolution_mode = '{ResolutionMode.NAME.value}'
                      AND NOT EXISTS (
                          SELECT 1 FROM confirmed_authorships ca
                          WHERE ca.source_authorship_id = sa.id
                      )
                      AND aik.author_name_normalized IN (
                          SELECT name_form
                          FROM person_name_forms
                          WHERE status <> '{AttributionStatus.REJECTED.value}'
                          GROUP BY name_form
                          HAVING count(DISTINCT person_id) >= 2
                      )
                )
                UPDATE source_authorships sa
                SET person_id = NULL, resolution_mode = NULL
                FROM candidates c
                JOIN source_publications sp ON sp.id = c.source_publication_id
                WHERE sa.id = c.id
                  AND (
                      SELECT count(DISTINCT pnf.person_id)
                      FROM person_name_forms pnf
                      WHERE pnf.name_form = c.name_form
                        AND pnf.status <> '{AttributionStatus.REJECTED.value}'
                        AND NOT EXISTS (
                            SELECT 1 FROM rejected_authorships r
                            WHERE r.publication_id = sp.publication_id
                              AND r.person_id = pnf.person_id
                        )
                  ) >= 2
            """)
        ).rowcount

    def detach_authorships(self, conn: Connection, authorship_ids: list[int]) -> int:
        """Sert aux liens cross-source devenus sans appui : une signature dont l'ancre ferme a disparu ce run et que la cascade n'a pas re-résolue."""
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

    def delete_empty_persons(self, conn: Connection) -> int:
        """Après le re-orphelinage, une personne purement nominale peut se retrouver sans aucune `source_authorships` — typiquement une forme réduite dont les signatures ont rejoint la forme pleine. La supprimer retire ses formes de nom canoniques (FK `CASCADE`), ce qui désambiguïse la forme réduite et laisse les orphelines se re-attacher au run suivant. Une personne vide est nécessairement non curée (la curation ne vit que sur des personnes à publications) ; les notices RH sont protégées, personnes légitimes sans publication dans le corpus."""
        return conn.execute(
            text("""
                DELETE FROM persons p
                WHERE NOT EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.person_id = p.id)
                  AND NOT EXISTS (SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id)
            """)
        ).rowcount

    def delete_unsupported_identifier_attributions(self, conn: Connection) -> int:
        """Supprime les attributions d'identifiant posées par le pipeline (origine `auto`), encore en attente, qu'aucune signature de leur personne ne porte. Une signature qui neutralise l'identifiant ne le porte pas. Les attributions confirmées, authentifiées ou saisies à la main restent."""
        return conn.execute(
            text(f"""
                DELETE FROM person_identifiers pi
                WHERE pi.source = '{IdentifierOrigin.AUTO.value}'
                  AND pi.status = '{AttributionStatus.PENDING.value}'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM source_authorships sa
                      JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                      WHERE sa.person_id = pi.person_id
                        AND aik.person_identifiers ->> pi.id_type::text = pi.id_value
                        AND NOT {identifier_neutralized("pi.id_type::text")}
                  )
            """)
        ).rowcount
