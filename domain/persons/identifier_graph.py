"""Canal identifiant du record linkage : clustering des identités par identifiant fort.

Première couche de la résolution des personnes (cf. chantier record linkage). Les nœuds
sont les **identités d'auteur** (`author_identifying_keys`) ; deux identités sont reliées
quand elles partagent une valeur d'identifiant fort (ORCID, IdRef, idHAL, `hal_person_id`)
sous garde de nom. Le regroupement est la fermeture transitive de ces arêtes
(`domain.entity_resolution.connected_components`).

La garde reprend la corroboration existante (`decide_match_by_identifier`) : face à la
personne qui détient la valeur, un verdict `rejected` de la forme de l'identité casse
l'arête, `confirmed` l'arme sans test, sinon `names_compatible` tranche. Entre deux
identités moissonnées qu'aucune personne ne détient encore, il n'y a pas de verdict :
seul `names_compatible` relie.

Pur, sans I/O : la projection des candidats (identités + détenteur + verdict) est fournie
par le caller. L'assignation des `person_id` aux composantes et la partition par cannot-link
sont des étapes ultérieures (réconciliation).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from domain.entity_resolution import connected_components
from domain.persons.name_matching import names_compatible


@dataclass(frozen=True)
class IdentifierCandidate:
    """Une identité porteuse d'une valeur d'identifiant fort, avec le détenteur éventuel
    de cette valeur (personne existante) et le verdict forme de l'identité ↔ détenteur.

    `verdict` : ``'confirmed'`` / ``'rejected'`` / ``None`` (pas de verdict décisif).
    Les champs `anchor_*` sont vides si aucune personne ne détient la valeur.
    """

    identity_id: int
    identity_name: str
    id_type: str
    id_value: str
    anchor_person_id: int | None
    anchor_last_norm: str
    anchor_first_norm: str
    verdict: str | None


@dataclass(frozen=True)
class IdentifierComponent:
    """Composante d'identités reliées par identifiant fort gardé.

    `anchor_person_ids` : personnes existantes dont une valeur détenue a armé une arête
    dans la composante — 0 = composante purement fluide (candidate à une nouvelle personne,
    sous incarnation conservatrice) ; 1 = ancrée sur une personne ; ≥ 2 = plusieurs
    personnes du noyau réunies, à ne pas fusionner d'office (signal pour la réconciliation).
    """

    identity_ids: tuple[int, ...]
    anchor_person_ids: tuple[int, ...]


def _matches_anchor(c: IdentifierCandidate) -> bool:
    """La forme de l'identité corrobore-t-elle son rattachement au détenteur ? Reprend la
    cascade de `decide_match_by_identifier` : `rejected` casse, `confirmed` prime, sinon
    compatibilité de noms."""
    if c.verdict == "rejected":
        return False
    if c.verdict == "confirmed":
        return True
    return names_compatible(c.identity_name, "", c.anchor_last_norm, c.anchor_first_norm)


def cluster_by_identifier(
    candidates: Iterable[IdentifierCandidate],
) -> list[IdentifierComponent]:
    """Regroupe les identités reliées par identifiant fort gardé, en composantes connexes.

    Deux identités sont reliées dans deux cas : elles se rattachent toutes deux à la même
    personne connue qui détient la valeur (rattachement gardé par `_matches_anchor`) ; ou
    elles portent la même valeur qu'aucune personne ne détient et leurs noms sont
    compatibles. Le regroupement suit ces liens de proche en proche ; une identité sans
    aucun lien reste seule. L'implémentation relie deux identités en leur donnant un
    marqueur commun, que `connected_components` regroupe.
    """
    # Marqueurs `(catégorie, valeur)` partagés par les identités reliées, au format attendu
    # par `connected_components`. Un rattachement à un détenteur : `('anchor', person_id)`.
    # Un lien entre deux identités sans détenteur : `('pair', 'type:valeur:id1:id2')`.
    tokens: dict[int, set[tuple[str, str]]] = {}
    all_identities: set[int] = set()
    no_anchor: dict[tuple[str, str], list[IdentifierCandidate]] = {}

    for c in candidates:
        all_identities.add(c.identity_id)
        tokens.setdefault(c.identity_id, set())
        if c.anchor_person_id is not None:
            if _matches_anchor(c):
                tokens[c.identity_id].add(("anchor", str(c.anchor_person_id)))
        else:
            no_anchor.setdefault((c.id_type, c.id_value), []).append(c)

    # Aucun détenteur pour la valeur : on relie deux à deux les identités qui la portent,
    # quand leurs noms sont compatibles.
    for (id_type, id_value), group in no_anchor.items():
        for a, b in combinations(group, 2):
            if names_compatible(a.identity_name, "", b.identity_name, ""):
                lo, hi = sorted((a.identity_id, b.identity_id))
                edge = ("pair", f"{id_type}:{id_value}:{lo}:{hi}")
                tokens[a.identity_id].add(edge)
                tokens[b.identity_id].add(edge)

    members = [(iid, frozenset(tokens[iid])) for iid in all_identities]
    components = connected_components(members)

    result: list[IdentifierComponent] = []
    for comp in components:
        anchors = sorted({int(t[1]) for iid in comp for t in tokens[iid] if t[0] == "anchor"})
        result.append(IdentifierComponent(tuple(comp), tuple(anchors)))
    return result
