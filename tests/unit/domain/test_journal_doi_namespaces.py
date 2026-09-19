"""Tests des espaces de noms DOI des revues (`domain.journals.doi_namespaces`)."""

from domain.journals.doi_namespaces import (
    designated_by_namespace,
    learn_namespaces,
    namespace_candidates,
    resolve_journal,
)
from domain.journals.journal import JournalType


def test_candidats_coupes_aux_separateurs_qu_ils_incluent():
    assert namespace_candidates("10.1016/j.physletb.2020.135") == [
        "10.1016/j.",
        "10.1016/j.physletb.",
        "10.1016/j.physletb.2020.",
    ]


def test_candidats_coupes_entre_lettres_et_chiffres():
    """Cas réel : MDPI colle le code de la revue au numéro (`nu` pour *Nutrients*)."""
    assert "10.3390/nu" in namespace_candidates("10.3390/nu12030745")
    assert "10.3390/nu" not in namespace_candidates("10.3390/nutrients12")


def test_un_espace_ne_prend_pas_un_mot_plus_long():
    """Cas réel : `10.1016/j.ins.` (*Information Sciences*) ne désigne pas `j.insmatheco` (*Insurance: Mathematics and Economics*)."""
    assert "10.1016/j.ins." not in namespace_candidates("10.1016/j.insmatheco.2024.07.007")


def test_un_issn_n_est_pas_coupe_a_son_tiret():
    """Cas réel : IOP construit ses DOI sur l'ISSN ; `10.1088/1748-` réunirait JINST (1748-0221) et *Biomedical Materials* (1748-6041)."""
    candidates = namespace_candidates("10.1088/1748-0221/13/05/p05012")
    assert "10.1088/1748-" not in candidates
    assert "10.1088/1748-0221/" in candidates


def test_doi_construit_sur_un_isbn_sans_candidat():
    assert namespace_candidates("10.1007/978-3-030-58080-3_309-1") == []


def _evidence(prefix: str, journal_id: int, n: int) -> list[tuple[str, int]]:
    return [(f"{prefix}{i:05d}", journal_id) for i in range(n)]


def test_espace_retenu_malgre_une_erreur_isolee():
    """Une notice HAL qui rattache à tort un article à une revue voisine ne défait pas l'espace."""
    evidence = _evidence("10.1016/j.physletb.", 1, 20) + [("10.1016/j.physletb.00003", 2)]
    evidence += _evidence("10.1016/j.epsl.", 4, 20)
    namespaces = learn_namespaces(evidence)
    assert namespaces["10.1016/j.physletb."].journal_id == 1
    assert resolve_journal("10.1016/j.physletb.99999", namespaces).journal_id == 1


def test_plusieurs_espaces_pour_une_revue():
    """Cas réel : *Scientific Reports*, `srep` puis `s41598-`."""
    evidence = _evidence("10.1038/srep", 7, 10) + _evidence("10.1038/s41598-", 7, 10)
    evidence += _evidence("10.1038/s41467-", 8, 10)
    namespaces = learn_namespaces(evidence)
    assert namespaces["10.1038/srep"].journal_id == 7
    assert namespaces["10.1038/s41598-"].journal_id == 7


def test_espace_partage_non_retenu():
    """Cas réel : *Physical Review C* et sa forme abrégée INSPIRE, deux revues en double."""
    evidence = _evidence("10.1103/physrevc.1", 1, 10) + _evidence("10.1103/physrevc.2", 2, 10)
    assert "10.1103/physrevc." not in learn_namespaces(evidence)


def test_le_deposant_seul_ne_designe_pas_une_revue():
    """Cas réel : sous `10.1056/`, le *NEJM* domine nos données, mais *NEJM Evidence* y publie aussi."""
    namespaces = learn_namespaces(_evidence("10.1056/nejmoa", 1, 20))
    assert "10.1056/" not in namespaces
    assert resolve_journal("10.1056/evidoa2200001", namespaces) is None


def test_espace_plus_court_de_meme_revue_suffit():
    """Cas réel : The Conversation France, seul titre sous `10.64628/aak.`."""
    namespaces = learn_namespaces(_evidence("10.64628/aak.", 3, 10))
    assert "10.64628/aak." in namespaces
    assert resolve_journal("10.64628/aak.335cx4kw5", namespaces).journal_id == 3


def test_sous_le_seuil_non_retenu():
    assert learn_namespaces(_evidence("10.1234/abc.", 1, 4)) == {}


def test_une_plateforme_n_est_designee_par_aucun_espace():
    """Cas réel : SSRN, dont le préfixe désigne la plateforme. Ses DOI comptent dans le total : une revue qui en porte quelques-uns ne capte pas l'espace."""
    evidence = _evidence("10.2139/ssrn.", 1, 20) + [("10.2139/ssrn.00003", 2)]
    namespaces = learn_namespaces(evidence, platforms={1})
    assert resolve_journal("10.2139/ssrn.99999", namespaces) is None


def test_types_designes_par_un_espace():
    assert designated_by_namespace(JournalType.JOURNAL)
    assert designated_by_namespace(JournalType.MEDIA)
    assert not designated_by_namespace(JournalType.PREPRINT_SERVER)
    assert not designated_by_namespace(JournalType.EBOOK_PLATFORM)
