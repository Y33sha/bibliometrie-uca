"""Orchestrateur de la phase `publishers_journals` : enrichissement du référentiel `journals`.

Sous-étapes incrémentales, dans l'ordre :

1. **resolve_publishers** — préfixe DOI → Registration Agency + éditeur Crossref / repository DataCite (interroge Crossref et DataCite, email polite pool requis).
2. **enrich_journals_from_openalex** — OpenAlex Sources → APC + journal_type (clé ou email OpenAlex).
3. **check_journals_in_sudoc** — Sudoc (public) → ISSN des revues vérifiés, corrigés et rangés par support.
4. **merge_duplicate_journals** — fusion des revues en double : même ISSN-L, même ISSN sous un titre emboîté, même titre et même préfixe DOI.
5. **delete_empty_journals** — suppression des revues sans enregistrement, sans publication et sans paiement APC, puis des monographies sans enregistrement ni publication, après la fusion des monographies en double, puis des éditeurs sans revue, sans monographie, sans préfixe DOI, sans paiement APC et sans forme de nom de revue.
6. **type_proceedings_journals** — typage en recueil d'actes des revues de type inconnu qui contiennent surtout des articles de congrès.
7. **learn_journal_doi_namespaces** — calcul des espaces de noms DOI des revues, sur les revues fusionnées et typées.
8. **enrich_journals_from_doaj** — dump CSV DOAJ (public) → `doaj_payload` + `is_in_doaj`.

La vérification Sudoc précède la fusion, qui lui prend l'ISSN-L, et l'import DOAJ, qui apparie les revues par ISSN. Chaque accès non configuré est sauté avec un signal `source_unconfigured`. Les runners de sous-étape (connexion, circuit-breaker, adapters) et la détection de config sont injectés par le composition-root ; ici, la séquence, les gardes de configuration et l'assemblage des métriques.
"""

import logging
from collections.abc import Callable

from application.pipeline.libelles import rien_a_faire
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.signals import filter_configured

RunSubstep = Callable[[], PhaseMetrics]
CredentialsMissing = Callable[[str], str | None]


def run(
    *,
    resolve_publishers: RunSubstep,
    enrich_from_openalex: RunSubstep,
    check_in_sudoc: RunSubstep,
    merge_duplicates: RunSubstep,
    delete_empty: RunSubstep,
    merge_duplicate_monographs: RunSubstep,
    delete_empty_monographs: RunSubstep,
    delete_empty_publishers: RunSubstep,
    type_proceedings: RunSubstep,
    learn_doi_namespaces: RunSubstep,
    enrich_from_doaj: RunSubstep,
    credentials_missing: CredentialsMissing,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Enchaîne les sous-étapes (les deux premières sous garde de config) et assemble les métriques de la phase."""
    metrics = PhaseMetrics()

    publishers = PhaseMetrics()
    if filter_configured(
        ["crossref", "datacite"],
        metrics,
        credentials_missing=credentials_missing,
        logger=logger,
        phase="publishers_journals",
    ):
        publishers = resolve_publishers()

    openalex = PhaseMetrics()
    if filter_configured(
        ["openalex"],
        metrics,
        credentials_missing=credentials_missing,
        logger=logger,
        phase="publishers_journals",
    ):
        openalex = enrich_from_openalex()

    sudoc = check_in_sudoc()
    merges = merge_duplicates()
    deletions = delete_empty()
    monograph_merges = merge_duplicate_monographs()
    monograph_deletions = delete_empty_monographs()
    publisher_deletions = delete_empty_publishers()
    proceedings = type_proceedings()
    namespaces = learn_doi_namespaces()
    doaj = enrich_from_doaj()

    # Les compteurs et signaux des sous-étapes remontent à la phase : le log (`as_summary()`), l'observabilité (`to_payload()`) et le passage en avertissement sur circuit-breaker tripé en dépendent. Les `details` sur-mesure sont posés juste après.
    for sub in (
        publishers,
        openalex,
        sudoc,
        merges,
        deletions,
        monograph_merges,
        monograph_deletions,
        publisher_deletions,
        proceedings,
        namespaces,
        doaj,
    ):
        metrics.merge(sub)

    # Chaque sous-étape se tait quand elle n'a rien à traiter : la phase le dit pour elles.
    if metrics.total == 0 and not metrics.extras:
        rien_a_faire(logger)

    metrics.details["table"] = {
        "rows": [
            {
                "key": "préfixes DOI → publishers",
                "traités": publishers.total,
                "identifiés": publishers.extras.get("publisher_matched", 0),
                "créés": publishers.extras.get("publisher_created", 0),
            },
            {
                "key": "revues OpenAlex",
                "traités": openalex.total,
                "identifiés": openalex.updated,
                "créés": 0,
            },
            {
                "key": "revues vérifiées dans le Sudoc",
                "traités": sudoc.total,
                "identifiés": sudoc.extras.get("sudoc_found", 0),
                "créés": 0,
            },
            {
                "key": "groupes de revues en double",
                "traités": merges.total,
                "identifiés": merges.extras.get("journals_merged", 0),
                "créés": 0,
            },
            {
                "key": "revues vides supprimées",
                "traités": deletions.total,
                "identifiés": deletions.extras.get("journals_deleted", 0),
                "créés": 0,
            },
            {
                "key": "monographies en double fusionnées",
                "traités": monograph_merges.total,
                "identifiés": monograph_merges.extras.get("monographs_merged", 0),
                "créés": 0,
            },
            {
                "key": "monographies vides supprimées",
                "traités": monograph_deletions.total,
                "identifiés": monograph_deletions.extras.get("monographs_deleted", 0),
                "créés": 0,
            },
            {
                "key": "éditeurs vides supprimés",
                "traités": publisher_deletions.total,
                "identifiés": publisher_deletions.extras.get("publishers_deleted", 0),
                "créés": 0,
            },
            {
                "key": "revues typées recueils d'actes",
                "traités": proceedings.total,
                "identifiés": proceedings.extras.get("journals_typed_proceedings", 0),
                "créés": 0,
            },
            {
                "key": "DOI → espaces de noms des revues",
                "traités": namespaces.total,
                "identifiés": namespaces.extras.get("journal_doi_namespaces", 0),
                "créés": 0,
            },
        ]
    }
    # DOAJ : ligne à part (sous-étape conditionnelle, métrique propre).
    metrics.details["summary"] = {"doaj_matched": doaj.extras.get("matched", 0)}
    # Chaque sous-étape conclut la sienne ; la table d'observabilité garde le détail.
    metrics.resume = ""
    return metrics
