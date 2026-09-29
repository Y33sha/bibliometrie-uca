"""Synchronisation des signatures d'une notice renormalisée (`domain.source_publications.signature_sync`)."""

from domain.source_publications.signature_sync import (
    IncomingSignature,
    SignatureSyncPlan,
    StoredSignature,
    plan_signature_sync,
    signature_content,
)


def _plan(stored, incoming) -> SignatureSyncPlan:
    return plan_signature_sync(
        [StoredSignature(*s) for s in stored], [IncomingSignature(*i) for i in incoming]
    )


class TestPlanSignatureSync:
    def test_signatures_inchangees_conservees(self):
        plan = _plan(
            [(10, 0, "dupont", "h1"), (11, 1, "xu", "h2")], [(0, "dupont", "h1"), (1, "xu", "h2")]
        )
        assert plan == SignatureSyncPlan(updates=(), kept=(10, 11), inserts=(), deletes=())

    def test_auteur_ajoute_en_tete_decale_les_autres(self):
        """Identité unique : la signature garde son identifiant malgré le changement de position."""
        plan = _plan(
            [(10, 0, "dupont", "h1"), (11, 1, "xu", "h2")],
            [(0, "martin", "h0"), (1, "dupont", "h1-bis"), (2, "xu", "h2-bis")],
        )
        assert plan == SignatureSyncPlan(
            updates=((10, 1), (11, 2)), kept=(), inserts=(0,), deletes=()
        )

    def test_auteur_disparu_supprime(self):
        plan = _plan([(10, 0, "dupont", "h1"), (11, 1, "xu", "h2")], [(0, "xu", "h2-bis")])
        assert plan == SignatureSyncPlan(updates=((11, 0),), kept=(), inserts=(), deletes=(10,))

    def test_identite_repetee_departagee_par_position(self):
        """Deux « Z. Xu » sur la même publication : rapprochés par leur position."""
        plan = _plan(
            [(10, 2, "xu z", "h2"), (11, 5, "xu z", "h5")],
            [(2, "xu z", "h2"), (5, "xu z", "h5"), (7, "dupont", "h7")],
        )
        assert plan == SignatureSyncPlan(updates=(), kept=(10, 11), inserts=(7,), deletes=())

    def test_identite_repetee_sans_position_commune(self):
        plan = _plan(
            [(10, 2, "xu z", "h2"), (11, 5, "xu z", "h5")], [(3, "xu z", "h3"), (6, "xu z", "h6")]
        )
        assert plan == SignatureSyncPlan(updates=(), kept=(), inserts=(3, 6), deletes=(10, 11))

    def test_identite_unique_en_base_repetee_a_l_arrivee(self):
        plan = _plan([(10, 2, "xu z", "h2")], [(2, "xu z", "h2"), (4, "xu z", "h4")])
        assert plan == SignatureSyncPlan(updates=(), kept=(10,), inserts=(4,), deletes=())

    def test_identite_differente_ne_rapproche_rien(self):
        """Le nom normalisé fait partie de l'identité : un nom corrigé donne une signature nouvelle."""
        plan = _plan([(10, 0, "bartoli adrien 1977", "h1")], [(0, "bartoli adrien", "h1")])
        assert plan == SignatureSyncPlan(updates=(), kept=(), inserts=(0,), deletes=(10,))

    def test_empreinte_absente_en_base(self):
        """Une signature écrite avant l'empreinte est réécrite à sa première synchronisation."""
        plan = _plan([(10, 0, "dupont", None)], [(0, "dupont", "h1")])
        assert plan.updates == ((10, 0),)


class TestSignatureContent:
    _BASE = {
        "position": 0,
        "raw_author_name": "Dupont, Jean",
        "is_corresponding": False,
        "roles": ["author"],
        "neutralized_identifiers": None,
        "addresses": [("Université Clermont Auvergne", ["FR"], None)],
    }

    def test_stable(self):
        assert signature_content(**self._BASE) == signature_content(**self._BASE)

    def test_change_avec_chaque_champ_ecrit(self):
        variantes = [
            {"position": 1},
            {"raw_author_name": "Dupont, J."},
            {"is_corresponding": True},
            {"roles": ["supervisor"]},
            {"neutralized_identifiers": {"orcid": "shared"}},
            {"addresses": [("Université Clermont Auvergne", ["FR"], ["FR"])]},
            {"addresses": []},
        ]
        base = signature_content(**self._BASE)
        for variante in variantes:
            assert signature_content(**{**self._BASE, **variante}) != base, variante
