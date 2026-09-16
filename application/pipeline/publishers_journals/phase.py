"""Orchestrateur de la phase `publishers_journals` : enrichissement du référentiel `journals`.

Sous-étapes incrémentales, dans l'ordre :

1. **resolve_publishers** — préfixe DOI → Registration Agency + éditeur Crossref / repository DataCite (interroge Crossref et DataCite, email polite pool requis).
2. **enrich_journals_from_openalex** — OpenAlex Sources → APC + journal_type (clé ou email OpenAlex).
3. **check_journals_in_sudoc** — Sudoc (public) → ISSN des revues vérifiés, corrigés et rangés par support.
4. **merge_journals_by_issnl** — fusion des revues qui partagent leur ISSN-L.
5. **enrich_journals_from_doaj** — dump CSV DOAJ (public) → `doaj_payload` + `is_in_doaj`.

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
    merge_by_issnl: RunSubstep,
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
    merges = merge_by_issnl()
    doaj = enrich_from_doaj()

    # Les compteurs et signaux des sous-étapes remontent à la phase : le log (`as_summary()`), l'observabilité (`to_payload()`) et le passage en avertissement sur circuit-breaker tripé en dépendent. Les `details` sur-mesure sont posés juste après.
    for sub in (publishers, openalex, sudoc, merges, doaj):
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
                "key": "revues de même ISSN-L",
                "traités": merges.total,
                "identifiés": merges.extras.get("journals_merged", 0),
                "créés": 0,
            },
        ]
    }
    # DOAJ : ligne à part (sous-étape conditionnelle, métrique propre).
    metrics.details["summary"] = {"doaj_matched": doaj.extras.get("matched", 0)}
    # Chaque sous-étape conclut la sienne ; la table d'observabilité garde le détail.
    metrics.resume = ""
    return metrics
