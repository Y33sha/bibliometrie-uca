"""Plafond du décalage qu'une lecture paginée peut demander.

Le coût d'une lecture profonde tient au produit du rang de page par la taille de page : un rang arbitrairement grand fait trier à la base l'ensemble du résultat pour n'en rendre aucune ligne. C'est donc le décalage qui se borne, non le rang seul.
"""

import pytest

from infrastructure.settings import settings
from interfaces.api.params import requested_offset


class TestDecalageDemande:
    @pytest.mark.parametrize(
        ("params", "attendu"),
        [
            ({"page": "1", "per_page": "50"}, 0),
            ({"page": "3", "per_page": "50"}, 100),
            ({"page": "11"}, 500),  # taille de page par défaut
            ({"page": "1000001", "per_page": "1"}, 1_000_000),
        ],
    )
    def test_multiplie_le_rang_par_la_taille_de_page(self, params, attendu):
        assert requested_offset(params) == attendu

    @pytest.mark.parametrize(
        "params",
        [
            {},  # aucune pagination demandée
            {"per_page": "50"},  # taille sans rang
            {"page": "deux"},  # illisible : la route rend son propre refus
            {"page": "0"},  # hors bornes : idem
            {"page": "2", "per_page": "-1"},
        ],
    )
    def test_rend_rien_quand_il_n_y_a_pas_de_pagination_lisible(self, params):
        assert requested_offset(params) is None


class TestPlafond:
    def test_le_plafond_est_un_reglage(self):
        # Le franchissement, le jour où un ensemble servi dépasse la valeur, se traite par la
        # configuration plutôt que par une livraison.
        assert isinstance(settings.max_pagination_offset, int)
        assert settings.max_pagination_offset > 0

    def test_une_demande_ordinaire_reste_sous_le_plafond(self):
        assert requested_offset({"page": "50", "per_page": "200"}) <= settings.max_pagination_offset

    def test_une_demande_absurde_le_depasse(self):
        demande = requested_offset({"page": "100000000", "per_page": "200"})
        assert demande > settings.max_pagination_offset
