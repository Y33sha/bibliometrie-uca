"""Fusion de deux éditeurs : données d'un éditeur avec leur règle de fusion (`PUBLISHER_DATA`).

Les revues homonymes des deux éditeurs sont fusionnées d'abord, selon `domain.journals.merge.JOURNAL_DATA`.
"""

from domain.merge import DataNature, MergedData, MergeRule

PUBLISHER_DATA: dict[str, MergedData] = {
    "journals": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Revues."),
    "monographs": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Monographies."),
    "apc_payments": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Paiements d'APC."),
    "doi_prefixes": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Préfixes DOI."),
    "name_forms": MergedData(MergeRule.TRANSFER, DataNature.DERIVED, "Formes de nom."),
    "journal_name_forms": MergedData(
        MergeRule.TRANSFER_UNIQUE,
        DataNature.DERIVED,
        "Formes de nom des revues, rattachées à l'éditeur ; une par forme.",
    ),
    "name": MergedData(MergeRule.KEEP_TARGET, DataNature.MIXED, "Nom."),
    "created_at": MergedData(MergeRule.KEEP_TARGET, DataNature.DERIVED, "Date de création."),
    "openalex_id": MergedData(MergeRule.FILL_EMPTY, DataNature.DERIVED, "Identifiant OpenAlex."),
    "country": MergedData(MergeRule.FILL_EMPTY, DataNature.MIXED, "Pays."),
    "publisher_type": MergedData(
        MergeRule.FILL_EMPTY,
        DataNature.MIXED,
        "Type d'éditeur. Le type inconnu compte comme vide.",
    ),
    "pub_count": MergedData(MergeRule.RECOMPUTED, DataNature.DERIVED, "Nombre de publications."),
}
