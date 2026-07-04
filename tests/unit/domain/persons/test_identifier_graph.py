"""Tests unitaires du canal identifiant (clustering par identifiant fort gardé)."""

from domain.persons.identifier_graph import (
    IdentifierCandidate,
    cluster_by_identifier,
)


def _cand(identity_id, name, id_type="orcid", id_value="V", *, anchor=None, verdict=None):
    """Candidat : identité `identity_id` de nom `name`, portant `id_type=id_value`.
    `anchor` = (person_id, last_norm, first_norm) du détenteur, ou None."""
    apid, aln, afn = anchor if anchor else (None, "", "")
    return IdentifierCandidate(
        identity_id=identity_id,
        identity_name=name,
        id_type=id_type,
        id_value=id_value,
        anchor_person_id=apid,
        anchor_last_norm=aln,
        anchor_first_norm=afn,
        verdict=verdict,
    )


def _by_ids(components):
    return {c.identity_ids: c.anchor_person_ids for c in components}


def test_two_identities_matching_same_anchor_merge():
    """Deux identités qui corroborent le même détenteur forment une composante ancrée."""
    comps = cluster_by_identifier(
        [
            _cand(1, "julien cogan", anchor=(42, "cogan", "julien")),
            _cand(2, "j cogan", anchor=(42, "cogan", "julien")),
        ]
    )
    assert _by_ids(comps) == {(1, 2): (42,)}


def test_rejected_verdict_breaks_edge():
    """Un verdict `rejected` sur la forme casse le rattachement : l'identité reste seule."""
    comps = cluster_by_identifier(
        [
            _cand(1, "julien cogan", anchor=(42, "cogan", "julien")),
            _cand(2, "intrus x", anchor=(42, "cogan", "julien"), verdict="rejected"),
        ]
    )
    assert _by_ids(comps) == {(1,): (42,), (2,): ()}


def test_confirmed_overrides_incompatible_name():
    """`confirmed` corrobore sans test de tokens (changement de nom, variante, coquille)."""
    comps = cluster_by_identifier(
        [_cand(1, "van lander", anchor=(7, "maneval", "axelle"), verdict="confirmed")]
    )
    assert _by_ids(comps) == {(1,): (7,)}


def test_incompatible_name_without_verdict_not_matched():
    """Sans verdict, un nom incompatible ne corrobore pas : identité orpheline."""
    comps = cluster_by_identifier([_cand(1, "toto inconnu", anchor=(7, "maneval", "axelle"))])
    assert _by_ids(comps) == {(1,): ()}


def test_fluid_to_fluid_compatible_merges():
    """Deux identités partageant une valeur non détenue, noms compatibles → réunies."""
    comps = cluster_by_identifier([_cand(1, "j cogan"), _cand(2, "julien cogan")])
    assert _by_ids(comps) == {(1, 2): ()}


def test_fluid_to_fluid_incompatible_stays_split():
    """Même valeur non détenue mais noms incompatibles → deux composantes."""
    comps = cluster_by_identifier([_cand(1, "john smith"), _cand(2, "jane smith")])
    assert _by_ids(comps) == {(1,): (), (2,): ()}


def test_two_anchors_bridged_flagged():
    """Une identité qui corrobore deux détenteurs (via deux valeurs) réunit leurs personnes :
    composante à deux ancres, à ne pas fusionner d'office."""
    comps = cluster_by_identifier(
        [
            _cand(1, "jean martin", id_type="orcid", id_value="O", anchor=(10, "martin", "jean")),
            _cand(1, "jean martin", id_type="idref", id_value="I", anchor=(20, "martin", "jean")),
        ]
    )
    assert _by_ids(comps) == {(1,): (10, 20)}
