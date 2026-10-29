"""Synchronisation des contributions sources d'un enregistrement source renormalisé (`domain.source_records.source_contribution_sync`)."""

from domain.source_records.source_contribution_sync import (
    IncomingSourceContribution,
    SourceContributionSyncPlan,
    StoredSourceContribution,
    plan_source_contribution_sync,
    source_contribution_content,
)


def _plan(stored, incoming) -> SourceContributionSyncPlan:
    """`incoming` : (position, informations du contributeur, empreinte) ; la clé entrante vaut la position."""
    return plan_source_contribution_sync(
        [StoredSourceContribution(*s) for s in stored],
        [IncomingSourceContribution(i[0], *i) for i in incoming],
    )


class TestPlanSourceContributionSync:
    def test_contributions_sources_inchangees_conservees(self):
        plan = _plan(
            [(10, 0, "dupont", "h1"), (11, 1, "xu", "h2")], [(0, "dupont", "h1"), (1, "xu", "h2")]
        )
        assert plan == SourceContributionSyncPlan(
            updates=(), kept=(10, 11), inserts=(), deletes=(), regroup=False
        )

    def test_auteur_ajoute_en_tete_decale_les_autres(self):
        """Informations du contributeur uniques : la contribution source garde son identifiant malgré le changement de position."""
        plan = _plan(
            [(10, 0, "dupont", "h1"), (11, 1, "xu", "h2")],
            [(0, "martin", "h0"), (1, "dupont", "h1-bis"), (2, "xu", "h2-bis")],
        )
        assert plan == SourceContributionSyncPlan(
            updates=((10, 1), (11, 2)), kept=(), inserts=(0,), deletes=(), regroup=True
        )

    def test_auteur_disparu_supprime(self):
        plan = _plan([(10, 0, "dupont", "h1"), (11, 1, "xu", "h2")], [(0, "xu", "h2-bis")])
        assert plan == SourceContributionSyncPlan(
            updates=((11, 0),), kept=(), inserts=(), deletes=(10,), regroup=True
        )

    def test_identite_repetee_departagee_par_position(self):
        """Deux « Z. Xu » sur la même publication : rapprochés par leur position."""
        plan = _plan(
            [(10, 2, "xu z", "h2"), (11, 5, "xu z", "h5")],
            [(2, "xu z", "h2"), (5, "xu z", "h5"), (7, "dupont", "h7")],
        )
        assert plan == SourceContributionSyncPlan(
            updates=(), kept=(10, 11), inserts=(7,), deletes=(), regroup=True
        )

    def test_identite_repetee_sans_position_commune(self):
        plan = _plan(
            [(10, 2, "xu z", "h2"), (11, 5, "xu z", "h5")], [(3, "xu z", "h3"), (6, "xu z", "h6")]
        )
        assert plan == SourceContributionSyncPlan(
            updates=(), kept=(), inserts=(3, 6), deletes=(10, 11), regroup=True
        )

    def test_identite_unique_en_base_repetee_a_l_arrivee(self):
        plan = _plan([(10, 2, "xu z", "h2")], [(2, "xu z", "h2"), (4, "xu z", "h4")])
        assert plan == SourceContributionSyncPlan(
            updates=(), kept=(10,), inserts=(4,), deletes=(), regroup=True
        )

    def test_identite_differente_ne_rapproche_rien(self):
        """Le nom normalisé fait partie des informations du contributeur : un nom corrigé donne une autre contribution source."""
        plan = _plan([(10, 0, "bartoli adrien 1977", "h1")], [(0, "bartoli adrien", "h1")])
        assert plan == SourceContributionSyncPlan(
            updates=(), kept=(), inserts=(0,), deletes=(10,), regroup=True
        )

    def test_contribution_source_sans_position_rapprochee_par_identifiant(self):
        """Un directeur de thèse est sans position d'auteur : ses informations du contributeur suffisent."""
        plan = plan_source_contribution_sync(
            [
                StoredSourceContribution(10, 0, "doctorant", "h0"),
                StoredSourceContribution(11, None, "directeur", "h1"),
            ],
            [
                IncomingSourceContribution(0, 0, "doctorant", "h0"),
                IncomingSourceContribution(1, None, "directeur", "h1"),
            ],
        )
        assert plan == SourceContributionSyncPlan(
            updates=(), kept=(10, 11), inserts=(), deletes=(), regroup=False
        )

    def test_identite_repetee_sans_position_ne_rapproche_rien(self):
        plan = plan_source_contribution_sync(
            [
                StoredSourceContribution(10, None, "dupont", "h1"),
                StoredSourceContribution(11, None, "dupont", "h2"),
            ],
            [
                IncomingSourceContribution(0, None, "dupont", "h1"),
                IncomingSourceContribution(1, None, "dupont", "h2"),
            ],
        )
        assert plan == SourceContributionSyncPlan(
            updates=(), kept=(), inserts=(0, 1), deletes=(10, 11), regroup=True
        )

    def test_adresse_modifiee_reecrit_sans_regrouper(self):
        """Seule l'empreinte change, par exemple une adresse : la contribution source est réécrite, son groupe reste valable."""
        plan = _plan([(10, 0, "dupont", "h1")], [(0, "dupont", "h1-adresse")])
        assert plan.updates == ((10, 0),)
        assert not plan.regroup

    def test_positions_permutees_regroupent(self):
        plan = _plan(
            [(10, 0, "dupont", "h1"), (11, 1, "xu", "h2")], [(1, "dupont", "h1"), (0, "xu", "h2")]
        )
        assert plan.regroup

    def test_roles_modifies_regroupent(self):
        plan = plan_source_contribution_sync(
            [StoredSourceContribution(10, None, "dupont", "h1", ("thesis_reviewer",))],
            [IncomingSourceContribution(0, None, "dupont", "h2", ("jury_president",))],
        )
        assert plan.updates == ((10, 0),)
        assert plan.regroup

    def test_empreinte_absente_en_base(self):
        """Une contribution source écrite avant l'empreinte est réécrite à sa première synchronisation."""
        plan = _plan([(10, 0, "dupont", None)], [(0, "dupont", "h1")])
        assert plan.updates == ((10, 0),)


class TestSourceContributionContent:
    _BASE = {
        "position": 0,
        "name": (None, "Dupont", "Jean"),
        "is_corresponding": False,
        "roles": ["author"],
        "neutralized_identifiers": None,
        "addresses": [("Université Clermont Auvergne", ["FR"], [])],
    }

    def test_stable(self):
        assert source_contribution_content(**self._BASE) == source_contribution_content(
            **self._BASE
        )

    def test_change_avec_chaque_champ_ecrit(self):
        variantes = [
            {"position": 1},
            {"name": (None, "Dupont", "J.")},
            {"name": ("Jean Dupont", None, None)},
            {"is_corresponding": True},
            {"roles": ["supervisor"]},
            {"neutralized_identifiers": {"orcid": "shared"}},
            {"addresses": [("Université Clermont Auvergne", ["FR", "IT"], [])]},
            {"addresses": [("Université Clermont Auvergne", ["FR"], ["01a8ajp46"])]},
            {"addresses": []},
            {"ror_ids": ["01a8ajp46"]},
        ]
        base = source_contribution_content(**self._BASE)
        for variante in variantes:
            assert source_contribution_content(**{**self._BASE, **variante}) != base, variante

    def test_sans_ror_le_contenu_omet_la_cle(self):
        assert "ror_ids" not in source_contribution_content(**self._BASE)

    def test_adresse_sans_ror_garde_le_contenu_sans_ror(self):
        """Une adresse sans ROR omet la liste de ses ROR."""
        assert source_contribution_content(**self._BASE)["addresses"] == [
            ["Université Clermont Auvergne", ["FR"]]
        ]

    def test_ror_independants_de_l_ordre(self):
        assert source_contribution_content(
            **self._BASE, ror_ids=["b", "a"]
        ) == source_contribution_content(**self._BASE, ror_ids=["a", "b"])
