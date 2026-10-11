"""Fusion de deux revues : données d'une revue avec leur règle de fusion (`JOURNAL_DATA`)."""

from domain.journals.journal import JournalType
from domain.merge import DataNature, MergedData, MergeRule

JOURNAL_DATA: dict[str, MergedData] = {
    "publications": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Publications."),
    "source_publications": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Notices."),
    "apc_payments": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Paiements d'APC."),
    "monographs": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Monographies."),
    "issns": MergedData(
        MergeRule.COMBINE,
        DataNature.MIXED,
        "ISSN. Un ISSN que la conservée a déjà reste le sien ; les autres passent à la conservée, à revérifier dans le Sudoc. L'ISSN de liaison de la conservée l'emporte.",
    ),
    "name_forms": MergedData(
        MergeRule.TRANSFER_UNIQUE, DataNature.DERIVED, "Formes de nom, une par éditeur."
    ),
    "doi_namespaces": MergedData(MergeRule.RECOMPUTED, DataNature.DERIVED, "Espaces de noms DOI."),
    "title": MergedData(MergeRule.KEEP_TARGET, DataNature.MIXED, "Titre."),
    "created_at": MergedData(MergeRule.KEEP_TARGET, DataNature.DERIVED, "Date de création."),
    "publisher": MergedData(MergeRule.FILL_EMPTY, DataNature.MIXED, "Éditeur."),
    "openalex_id": MergedData(MergeRule.FILL_EMPTY, DataNature.DERIVED, "Identifiant OpenAlex."),
    "oa_model": MergedData(MergeRule.FILL_EMPTY, DataNature.MIXED, "Modèle OA."),
    "apc": MergedData(
        MergeRule.FILL_EMPTY, DataNature.MIXED, "APC : montant et devise, pris ensemble."
    ),
    "journal_type": MergedData(
        MergeRule.FILL_EMPTY,
        DataNature.MIXED,
        "Type de revue. Le type inconnu compte comme vide (`merged_journal_type`).",
    ),
    "is_academic": MergedData(MergeRule.KEEP_TARGET, DataNature.MIXED, "Caractère académique."),
    "is_in_doaj": MergedData(
        MergeRule.COMBINE, DataNature.MIXED, "Présence au DOAJ : vraie si l'une des deux y est."
    ),
    "doaj_record": MergedData(
        MergeRule.RECOMPUTED, DataNature.DERIVED, "Notice DOAJ et date de son import."
    ),
    "pub_count": MergedData(MergeRule.RECOMPUTED, DataNature.DERIVED, "Nombre de publications."),
}


def merged_journal_type(target: JournalType, source: JournalType) -> JournalType:
    """Type de la revue fusionnée : celui de la conservée, sauf s'il est inconnu."""
    return source if target == JournalType.UNKNOWN else target
