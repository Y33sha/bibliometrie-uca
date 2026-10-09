from domain.structures.identifiers import RorId
from domain.structures.ror_coherence import tutelle_coherence

CNRS, INSU, OPGC, LABO, UNIV, EXTERNE = (
    RorId(r) for r in ("02feahw73", "04kdfz702", "01bch8q67", "03vgfxd91", "01a8ajp46", "02cp04407")
)
# Identifiants de structures : 1 CNRS, 2 INSU, 3 OPGC, 4 laboratoire, 5 université, 6 composante sans ROR.
RORS = {1: CNRS, 2: INSU, 3: OPGC, 4: LABO, 5: UNIV}


def _coherence(tutelles, ror_edges, *, rors=RORS, scope=frozenset({3, 4, 5})):
    return tutelle_coherence(
        structure_rors=rors, tutelles=tutelles, ror_edges=ror_edges, scope=scope
    )


class TestClotureTransitive:
    def test_un_parent_ror_atteint_par_un_chemin_de_tutelles_est_couvert(self):
        result = _coherence(
            tutelles=[(1, 2), (2, 3), (3, 4)],
            ror_edges=[(CNRS, INSU), (INSU, OPGC), (OPGC, LABO), (INSU, LABO)],
        )
        assert result.uncovered_ror_parents == frozenset()

    def test_une_tutelle_atteinte_par_un_chemin_ror_est_couverte(self):
        result = _coherence(
            tutelles=[(1, 4)],
            ror_edges=[(CNRS, INSU), (INSU, LABO)],
        )
        assert result.absent_from_ror == frozenset()

    def test_une_composante_sans_ror_relaie_la_tutelle(self):
        result = _coherence(tutelles=[(5, 6), (6, 4)], ror_edges=[(UNIV, LABO)])
        assert result.uncovered_ror_parents == frozenset()


class TestEcarts:
    def test_tutelle_absente_du_ror(self):
        result = _coherence(tutelles=[(5, 4)], ror_edges=[])
        assert result.absent_from_ror == {(5, 4)}

    def test_parent_ror_absent_des_tutelles(self):
        result = _coherence(tutelles=[], ror_edges=[(UNIV, LABO)])
        assert result.uncovered_ror_parents == {(5, 4)}

    def test_parent_et_enfant_ror_absents_de_structures_limites_au_perimetre(self):
        result = _coherence(
            tutelles=[],
            ror_edges=[(EXTERNE, LABO), (UNIV, EXTERNE), (EXTERNE, CNRS)],
        )
        assert result.outside_parents == {(4, EXTERNE)}
        assert result.outside_children == {(5, EXTERNE)}

    def test_ror_partage_par_deux_structures(self):
        result = _coherence(tutelles=[], ror_edges=[], rors={**RORS, 7: UNIV})
        assert result.shared_ror_ids == {UNIV}
