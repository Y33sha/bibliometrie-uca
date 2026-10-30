"""Tests de la décision de rattachement d'une contribution à une personne."""

from domain.normalize import normalize_text
from domain.persons.contribution_matching import (
    AlignedSourceContribution,
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    ContributionSkipReason,
    PersonIndex,
    decide_contribution,
    founding_name,
    settle_publication,
)
from domain.persons.contributor_name import ContributorName
from domain.persons.matching import IdentifiedPerson, Namesake
from domain.persons.name_forms import compute_person_name_forms
from domain.publications.contribution_roles import ContributionRole

_ORCID = "0000-0002-1825-0097"
_IDREF = "123456789"


def _member(raw, source="hal", identifiers=None, in_perimeter=True, roles=(), pinned=None):
    return AlignedSourceContribution(
        source=source,
        name=ContributorName(raw=raw),
        identifiers=identifiers or {},
        in_perimeter=in_perimeter,
        roles=roles,
        pinned_person_id=pinned,
    )


def _index(persons=(), orcid=None, idref=None):
    """Construit l'index des personnes `(person_id, nom, prénom)`, avec des attributions d'identifiants `{valeur: person_id}`."""
    by_id = {p[0]: p for p in persons}
    name_forms: dict[str, list[int]] = {}
    namesakes: dict[str, list[Namesake]] = {}
    for person_id, last, first in persons:
        for form in compute_person_name_forms(last, first):
            name_forms.setdefault(form, []).append(person_id)
        namesakes.setdefault(normalize_text(last), []).append(Namesake(person_id, last, first))

    def identified(attributions):
        return {
            value: IdentifiedPerson(
                pid, normalize_text(by_id[pid][1]), normalize_text(by_id[pid][2])
            )
            for value, pid in (attributions or {}).items()
        }

    return PersonIndex(
        identifiers={"orcid": identified(orcid), "idref": identified(idref)},
        name_forms=name_forms,
        name_form_status={},
        namesakes=namesakes,
    )


def test_un_epinglage_l_emporte():
    index = _index([(1, "Martin", "Jean"), (2, "Martin", "Paul")], orcid={_ORCID: 2})
    members = [
        _member("Jean Martin", pinned=1),
        _member("J. Martin", "crossref", {"orcid": _ORCID}),
    ]

    decision = decide_contribution(members, index)

    assert (decision.outcome, decision.person_id, decision.reason) == (
        ContributionOutcome.MATCH,
        1,
        ContributionMatchReason.MANUAL,
    )


def test_deux_epinglages_differents_laissent_le_groupe_sans_personne():
    members = [_member("Jean Martin", pinned=1), _member("J. Martin", "openalex", pinned=2)]

    assert decide_contribution(members, _index()).reason == ContributionSkipReason.PIN_CONFLICT


def test_un_identifiant_d_une_contribution_source_rattache_toute_la_contribution():
    index = _index([(1, "Martin", "Jean")], idref={_IDREF: 1})
    members = [_member("Jean Martin", "scanr", {"idref": _IDREF}), _member("J. Martin", "openalex")]

    decision = decide_contribution(members, index)

    assert (decision.person_id, decision.reason) == (1, ContributionMatchReason.IDREF)


def test_deux_identifiants_de_deux_personnes_laissent_le_groupe_sans_personne():
    index = _index(
        [(1, "Martin", "Jean"), (2, "Martin", "Jeanne")], orcid={_ORCID: 1}, idref={_IDREF: 2}
    )
    members = [
        _member("Jean Martin", "crossref", {"orcid": _ORCID}),
        _member("J. Martin", "scanr", {"idref": _IDREF}),
    ]

    assert decide_contribution(members, index).reason == ContributionSkipReason.IDENTIFIER_CONFLICT


def test_l_orcid_d_une_source_sans_depot_par_l_auteur_est_ignore():
    index = _index([(1, "Martin", "Jean")], orcid={_ORCID: 1})
    members = [_member("Jean Martin", "wos", {"orcid": _ORCID}, in_perimeter=False)]

    assert decide_contribution(members, index).reason == ContributionSkipReason.OUT_OF_PERIMETER


def test_un_identifiant_au_nom_incompatible_est_refuse():
    index = _index([(1, "Durand", "Claire")], orcid={_ORCID: 1})
    members = [_member("Jean Martin", "crossref", {"orcid": _ORCID})]

    decision = decide_contribution(members, index)

    assert decision.outcome == ContributionOutcome.CREATE
    assert decision.refused == (("orcid", _ORCID, 1),)


def test_une_personne_rejetee_pour_la_publication_est_ecartee():
    index = _index([(1, "Martin", "Jean")], orcid={_ORCID: 1})
    members = [_member("Jean Martin", "crossref", {"orcid": _ORCID})]

    decision = decide_contribution(members, index, rejected_person_ids=frozenset({1}))

    assert decision.reason == ContributionSkipReason.ALL_CANDIDATES_REJECTED


def test_un_nom_seul_ne_rattache_pas_hors_perimetre():
    index = _index([(1, "Martin", "Jean")])
    members = [_member("Jean Martin", in_perimeter=False)]

    assert decide_contribution(members, index).reason == ContributionSkipReason.OUT_OF_PERIMETER


def test_un_membre_du_perimetre_suffit_au_rattachement_par_le_nom():
    index = _index([(1, "Martin", "Jean")])
    members = [_member("Jean Martin", in_perimeter=False), _member("J. Martin", "openalex")]

    decision = decide_contribution(members, index)

    assert (decision.person_id, decision.reason) == (1, ContributionMatchReason.NAME)


def test_un_prenom_plein_tranche_l_ambiguite_d_une_initiale():
    index = _index([(1, "Martin", "Jean"), (2, "Martin", "Jacques")])
    members = [_member("J. Martin", "openalex"), _member("Jean Martin")]

    decision = decide_contribution(members, index)

    assert (decision.outcome, decision.person_id) == (ContributionOutcome.MATCH, 1)


def test_deux_membres_qui_designent_deux_personnes_laissent_le_groupe_sans_personne():
    index = _index([(1, "Martin", "Jean"), (2, "Martin", "Jacques")])
    members = [_member("Jean Martin"), _member("Jacques Martin", "openalex")]

    assert decide_contribution(members, index).reason == ContributionSkipReason.NAME_CONFLICT


def test_un_nom_ambigu_ne_cree_pas_de_personne():
    index = _index([(1, "Martin", "Jean"), (2, "Martin", "Jacques")])
    members = [_member("J. Martin")]

    assert decide_contribution(members, index).reason == ContributionSkipReason.AMBIGUOUS_NAME_FORM


def test_un_nom_inconnu_du_perimetre_cree_une_personne():
    assert (
        decide_contribution([_member("Jean Martin")], _index()).outcome
        == ContributionOutcome.CREATE
    )


def test_un_jury_de_these_ne_cree_pas_de_personne():
    members = [_member("Jean Martin", "theses", roles=(ContributionRole.RAPPORTEUR,))]

    assert (
        decide_contribution(members, _index()).reason == ContributionSkipReason.CREATION_NOT_ALLOWED
    )


def test_une_personne_revient_au_groupe_le_mieux_appuye_de_la_publication():
    by_name = ContributionDecision(ContributionOutcome.MATCH, 1, ContributionMatchReason.NAME)
    by_orcid = ContributionDecision(ContributionOutcome.MATCH, 1, ContributionMatchReason.ORCID)
    other = ContributionDecision(ContributionOutcome.MATCH, 2, ContributionMatchReason.NAME)

    settled = settle_publication({10: (by_name, 6), 11: (by_orcid, 2), 12: (other, 1)})

    assert settled[11] == by_orcid
    assert settled[12] == other
    assert settled[10].reason == ContributionSkipReason.PERSON_IN_OTHER_CONTRIBUTION


def test_a_appui_egal_la_personne_revient_au_groupe_le_plus_fourni():
    decision = ContributionDecision(ContributionOutcome.MATCH, 1, ContributionMatchReason.NAME)

    settled = settle_publication({10: (decision, 1), 11: (decision, 6)})

    assert (settled[10].outcome, settled[11].outcome) == (
        ContributionOutcome.SKIP,
        ContributionOutcome.MATCH,
    )


def test_une_personne_deja_rattachee_dans_la_publication_n_est_pas_reprise():
    decision = ContributionDecision(ContributionOutcome.MATCH, 1, ContributionMatchReason.ORCID)

    settled = settle_publication({10: (decision, 3)}, taken=frozenset({1}))

    assert settled[10].reason == ContributionSkipReason.PERSON_IN_OTHER_CONTRIBUTION


def _split_member(last, first, source):
    return AlignedSourceContribution(
        source=source,
        name=ContributorName(last_name=last, first_name=first),
        identifiers={},
        in_perimeter=True,
    )


class TestFoundingName:
    def test_une_source_qui_separe_nom_et_prenom_l_emporte(self):
        members = [_member("Jean Martin", source="theses"), _split_member("Martin", "J.", "wos")]
        assert founding_name(members) == ("Martin", "J.")

    def test_un_prenom_complet_l_emporte_sur_une_initiale(self):
        members = [
            _split_member("Martin", "J.", "crossref"),
            _split_member("Martin", "Jean", "hal"),
        ]
        assert founding_name(members) == ("Martin", "Jean")

    def test_la_preseance_des_sources_departage_et_non_la_longueur_du_prenom(self):
        members = [
            _split_member("Martin", "Jean-Pierre", "hal"),
            _split_member("Martin", "Jean", "openalex"),
        ]
        assert founding_name(members) == ("Martin", "Jean")

    def test_le_role_et_le_perimetre_des_membres_sont_ignores(self):
        hors = AlignedSourceContribution(
            source="crossref",
            name=ContributorName(last_name="Martin", first_name="Jean"),
            identifiers={},
            in_perimeter=False,
            roles=("jury",),
        )
        members = [_split_member("Martin", "Jeanne", "hal"), hors]
        assert founding_name(members) == ("Martin", "Jean")
