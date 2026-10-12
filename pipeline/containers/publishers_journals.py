"""Orchestrateur de la phase `publishers_journals` : enrichissement des référentiels d'éditeurs, de revues et de monographies.

Trois groupes de sous-étapes, dans l'ordre :

- **Éditeurs** — `resolve_publishers` : éditeur Crossref ou repository DataCite de chaque préfixe DOI en attente.
- **Revues** — `enrich_journals_from_openalex` (type et frais de publication), `check_journals_in_sudoc` (ISSN vérifiés, corrigés et rangés par support), `merge_duplicate_journals`, `type_proceedings_journals`, `learn_journal_doi_namespaces`, `enrich_journals_from_doaj`.
- **Monographies** — `merge_duplicate_monographs`, `link_monographs_to_collections`, `type_proceedings_volumes`.

Contraintes d'ordre :

- OpenAlex type les revues `unknown` avant le typage en recueil d'actes, qui vise aussi les revues `unknown`.
- La vérification Sudoc précède la fusion des revues, qui lit l'ISSN-L, et l'import DOAJ, qui apparie les revues par ISSN.
- Les espaces de noms DOI suivent la fusion et le typage des revues.
- Le rattachement des monographies suit la fusion des revues. La nature des monographies lit le type de la collection que pose le rattachement.

Chaque sous-étape tient une ligne du journal, sous le titre de son groupe. Un accès non configuré est sauté avec un signal `source_unconfigured`. Les runners de sous-étape (connexion, circuit-breaker, adapters) et la détection de configuration sont injectés par le câblage ; ici, la séquence, les gardes de configuration et l'assemblage des métriques.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pipeline.containers import (
    check_journals_in_sudoc,
    enrich_journals_from_openalex,
    import_journals_from_doaj_dump,
    learn_journal_doi_namespaces,
    link_monographs_to_collections,
    merge_duplicate_journals,
    merge_duplicate_monographs,
    resolve_publishers,
    type_proceedings_journals,
    type_proceedings_volumes,
)
from pipeline.context import PhaseContext
from pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, etape
from pipeline.metrics import PhaseMetrics
from pipeline.signals import filter_configured

RunSubstep = Callable[[], PhaseMetrics]
CredentialsMissing = Callable[[str], str | None]


@dataclass(frozen=True)
class _SousEtape:
    """Sous-étape de la phase : le champ de `PublishersJournalsPhase` qui l'exécute, son libellé, et les accès à configurer avant de la lancer."""

    champ: str
    libelle: str
    acces: tuple[str, ...] = ()


_GROUPES: tuple[tuple[str, tuple[_SousEtape, ...]], ...] = (
    (
        "Éditeurs",
        (_SousEtape("resolve_publishers", resolve_publishers.LIBELLE, ("crossref", "datacite")),),
    ),
    (
        "Revues",
        (
            _SousEtape(
                "enrich_journals_from_openalex",
                enrich_journals_from_openalex.LIBELLE,
                ("openalex",),
            ),
            _SousEtape("check_journals_in_sudoc", check_journals_in_sudoc.LIBELLE),
            _SousEtape("merge_duplicate_journals", merge_duplicate_journals.LIBELLE),
            _SousEtape("type_proceedings_journals", type_proceedings_journals.LIBELLE),
            _SousEtape("learn_journal_doi_namespaces", learn_journal_doi_namespaces.LIBELLE),
            _SousEtape("enrich_journals_from_doaj", import_journals_from_doaj_dump.LIBELLE),
        ),
    ),
    (
        "Monographies",
        (
            _SousEtape("merge_duplicate_monographs", merge_duplicate_monographs.LIBELLE),
            _SousEtape("link_monographs_to_collections", link_monographs_to_collections.LIBELLE),
            _SousEtape("type_proceedings_volumes", type_proceedings_volumes.LIBELLE),
        ),
    ),
)


@dataclass(frozen=True)
class PublishersJournalsPhase:
    resolve_publishers: RunSubstep
    enrich_journals_from_openalex: RunSubstep
    check_journals_in_sudoc: RunSubstep
    merge_duplicate_journals: RunSubstep
    type_proceedings_journals: RunSubstep
    learn_journal_doi_namespaces: RunSubstep
    enrich_journals_from_doaj: RunSubstep
    merge_duplicate_monographs: RunSubstep
    link_monographs_to_collections: RunSubstep
    type_proceedings_volumes: RunSubstep
    credentials_missing: CredentialsMissing

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Enchaîne les groupes de sous-étapes, écrit une ligne par sous-étape et assemble les métriques de la phase."""
        logger = ctx.logger
        metrics = PhaseMetrics()
        by_step: dict[str, PhaseMetrics] = {}
        for titre, sous_etapes in _GROUPES:
            etape(logger, titre)
            for indice, sous_etape in enumerate(sous_etapes):
                branche = DERNIERE_BRANCHE if indice == len(sous_etapes) - 1 else BRANCHE
                by_step[sous_etape.champ] = self._run_one(sous_etape, branche, metrics, logger)
        _assemble(metrics, by_step)
        return metrics

    def _run_one(
        self, sous_etape: _SousEtape, branche: str, metrics: PhaseMetrics, logger: logging.Logger
    ) -> PhaseMetrics:
        """Exécute une sous-étape, sauf si aucun de ses accès n'est configuré, et écrit sa ligne de bilan."""
        if sous_etape.acces and not filter_configured(
            list(sous_etape.acces),
            metrics,
            credentials_missing=self.credentials_missing,
            logger=logger,
            phase="publishers_journals",
        ):
            logger.info("%s%s : sautée, accès non configuré", branche, sous_etape.libelle)
            return PhaseMetrics()
        sub: PhaseMetrics = getattr(self, sous_etape.champ)()
        if sub.resume is not None:
            bilan = sub.resume
        elif sub.signals:
            bilan = "interrompue"
        else:
            bilan = "rien à faire"
        logger.info("%s%s : %s", branche, sous_etape.libelle, bilan)
        return sub


# Ligne de la table d'observabilité de chaque sous-étape : son champ, son libellé, et ce qui compte comme identifié.
_TABLE: tuple[tuple[str, str, Callable[[PhaseMetrics], int]], ...] = (
    (
        "resolve_publishers",
        "préfixes DOI → publishers",
        lambda m: m.extras.get("publisher_matched", 0),
    ),
    ("enrich_journals_from_openalex", "revues OpenAlex", lambda m: m.updated),
    (
        "check_journals_in_sudoc",
        "revues vérifiées dans le Sudoc",
        lambda m: m.extras.get("sudoc_found", 0),
    ),
    (
        "merge_duplicate_journals",
        "groupes de revues en double",
        lambda m: m.extras.get("journals_merged", 0),
    ),
    (
        "type_proceedings_journals",
        "revues typées recueils d'actes",
        lambda m: m.extras.get("journals_typed_proceedings", 0),
    ),
    (
        "learn_journal_doi_namespaces",
        "DOI → espaces de noms des revues",
        lambda m: m.extras.get("journal_doi_namespaces", 0),
    ),
    (
        "merge_duplicate_monographs",
        "monographies en double fusionnées",
        lambda m: m.extras.get("monographs_merged", 0),
    ),
    (
        "link_monographs_to_collections",
        "monographies rattachées à leur collection",
        lambda m: m.extras.get("monographs_linked", 0),
    ),
    (
        "type_proceedings_volumes",
        "monographies retypées (actes ou livre)",
        lambda m: m.extras.get("monographs_to_proceedings", 0),
    ),
)


def _assemble(metrics: PhaseMetrics, by_step: dict[str, PhaseMetrics]) -> None:
    """Reporte dans `metrics` les métriques des sous-étapes, dans l'ordre de leur exécution."""
    # Les compteurs et signaux des sous-étapes remontent à la phase : le log (`as_summary()`), l'observabilité (`to_payload()`) et le passage en avertissement sur circuit-breaker tripé en dépendent. Les `details` sur-mesure sont posés juste après.
    for sub in by_step.values():
        metrics.merge(sub)

    publishers = by_step["resolve_publishers"]
    metrics.details["table"] = {
        "rows": [
            {
                "key": key,
                "traités": by_step[champ].total,
                "identifiés": identifies(by_step[champ]),
                "créés": publishers.extras.get("publisher_created", 0)
                if champ == "resolve_publishers"
                else 0,
            }
            for champ, key, identifies in _TABLE
        ]
    }
    # DOAJ : ligne à part (sous-étape conditionnelle, métrique propre).
    metrics.details["summary"] = {
        "doaj_matched": by_step["enrich_journals_from_doaj"].extras.get("matched", 0)
    }
    # Chaque sous-étape a écrit sa ligne ; la table d'observabilité garde le détail.
    metrics.resume = ""
