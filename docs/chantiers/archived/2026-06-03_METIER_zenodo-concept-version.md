# Chantier — Zenodo : dédup concept/version en matching, pas en normalize

Commencé et terminé le 2026-06-03

## Contexte

Les normalizers **HAL et OpenAlex** font une déduplication Zenodo *par éviction*, à la normalisation : quand le record courant a un DOI **concept** Zenodo dont la **version** est déjà présente en staging, le record est **jeté** (`mark_done` + `return None`, **aucune source_publication créée**).

Le resolver ([`infrastructure/sources/zenodo.py`](../../infrastructure/sources/zenodo.py)) ne fait que `concept → version` (`resolve(version) → None`). Donc `if version_doi:` n'est vrai que pour un record **concept**, et c'est lui qu'on jette : **concept jeté, version gardée.**

C'est faux sur deux plans :

1. **Mauvais étage.** Une dédup par éviction en normalize :
   - **perd la trace HAL/OA** (le record n'a plus de source_publication — viole l'invariant « un record source → une source_publication ») ;
   - **met un appel HTTP dans le chemin chaud** de normalize (diagnostiqué : les `SLOW publisher+journal:1.4s` étaient cet appel) ;
   - est **incomplète** : ne marche que si concept et version sont en staging *au même moment*. Si la version arrive à un import ultérieur, le concept a déjà sa source_publication → pas d'éviction → le doublon existe quand même.

2. **Mauvais choix.** Le **concept** est l'identifiant stable, agnostique aux versions (il pointe toujours vers la dernière). Le jeter pour garder une **version** (un snapshot) est à l'envers. Et en multi-versions c'est contre-productif : pour un dépôt avec concept C + versions v1/v2/v3 tous en HAL, `resolve(vN) → None` (gardés) et `resolve(C) → v3` présent → **C jeté**. On conserve les 3 snapshots (les vrais doublons) et on supprime **l'unificateur**.

Volume : ~0,14 % des HAL à normaliser portent un DOI Zenodo (85 / 61 491). Marginal, mais la perte de records est un bug de correction, pas de perf.

## Décisions

1. **normalize ne déduplique plus et n'appelle plus Zenodo.** Tout record → une source_publication, avec son DOI tel quel. Suppression du bloc Zenodo de `process_work` (HAL + OpenAlex) et du code mort associé (`staging_has_hal_doi` / `staging_has_openalex_doi`, l'injection `zenodo_resolver` dans les normalizers).
2. **La relation concept↔version est un fait de déduplication**, traité à la phase **matching** : un DOI concept et ses DOI versions désignent une même œuvre → **une publication canonique, canonicalisée sur le DOI concept** (stable). Toutes les source_publications (concept + versions) rattachées dessus — mécanisme standard multi-source → une publication.
3. **Résolution du concept hors du chemin chaud.** Le mapping version→concept (champ `conceptdoi` de l'API Zenodo) est résolu par une **étape dédiée** (batchable, backoff, idempotente) qui le stocke sur `source_publications.external_ids` (`zenodo_concept`). Le matching lit ce champ, ne tape jamais l'API.

## Phasage

- [x] **Phase 1 (urgent) — retirer l'éviction de normalize.** (763e0e3b) Supprimer le bloc Zenodo de `process_work` HAL + OpenAlex (plus de skip, plus de `resolve()`), retirer `zenodo_resolver` de la DI des deux normalizers (CLI + run_pipeline), supprimer le code mort `staging_has_hal_doi` / `staging_has_openalex_doi`. Tout record Zenodo obtient sa source_publication. (`HttpZenodoResolver` / `resolve_zenodo_doi` restent — réutilisés en Phase 2.)
- [x] **Phase 2 — résolution concept DOI hors hot path.** (066e8b20) Étape qui, pour les source_publications au DOI Zenodo sans `external_ids.zenodo_concept_doi`, résout le concept DOI (`conceptdoi` via l'API) et le stocke. Backoff/idempotent, relançable.
- [x] **Phase 3 — dédup sur le concept au matching.** (e6cf81f3) `match_or_create_publications` canonicalise les œuvres Zenodo sur le DOI concept : concept + versions → une publication (DOI = concept). Métadonnées arbitrées par le `refresh_from_sources` existant.
