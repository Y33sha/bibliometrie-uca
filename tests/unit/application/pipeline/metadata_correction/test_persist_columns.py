"""Liste blanche des colonnes que les corrections de métadonnées peuvent poser.

Le nom d'une colonne s'écrit dans le texte de la requête — un paramètre lié ne porte qu'une valeur, jamais un identifiant. La liste est donc la seule origine possible, et une colonne étrangère est refusée avant toute composition de SQL.
"""

import pytest

from infrastructure.pipeline.metadata_correction import _persist_updates


class TestColonnesCorrigibles:
    def test_colonne_hors_liste_refusee(self):
        with pytest.raises(ValueError, match="titre; DROP TABLE"):
            _persist_updates(None, [{"id": 1}], set_columns=("titre; DROP TABLE x --",))

    def test_refus_avant_tout_acces_a_la_base(self):
        # `conn` vaut None : le refus tombe avant qu'on s'en serve.
        with pytest.raises(ValueError):
            _persist_updates(None, [{"id": 1}], set_columns=("doc_type", "colonne_inconnue"))

    def test_colonnes_connues_acceptees(self):
        assert _persist_updates(None, [], set_columns=("doc_type", "raw_metadata")) == 0

    def test_les_appelants_reels_passent_la_garde(self):
        for colonnes in (
            ("doc_type", "oa_status", "external_ids", "raw_metadata"),
            ("journal_id", "raw_metadata"),
            ("doi", "raw_metadata"),
        ):
            assert _persist_updates(None, [], set_columns=colonnes) == 0
