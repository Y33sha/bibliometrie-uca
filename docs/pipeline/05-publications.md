#  Création et dédoublonnage des publications

```mermaid
flowchart LR
    A[source_publications]-->B[publications]
    classDef new  fill:#bbf
    class B new;
```

Phase `publications`: les publications sources sont rattachées aux publications canoniques:
- par **DOI** (même DOI = même publi, sauf cas particuliers).
- par **NNT** (numéro national de thèse)
- par **hal-id** (un document OpenAlex ou ScanR qui référence un document HAL)

Les cas douteux (métadonnées identiques ou similaires) sont préservés et sont fusionnés manuellement via la page admin/duplicates.

## Découpage en deux phases

La phase traite les `source_publications` orphelins (sans `publication_id`) en deux temps successifs.

**Phase A — orphelins in_perimeter** (boucle Python). Ne charge que les SP avec au moins une `source_authorship` `in_perimeter = TRUE` (typiquement 1-2 % du pool d'orphelins, soit quelques milliers). Pour chaque SP : cascade `decide_publication_match` (DOI → NNT → hal_id → métadonnées thèse) ; si match, rattachement ; sinon, **création** d'une nouvelle publication canonique. Seules les SP in_perimeter peuvent déclencher une création — c'est le périmètre métier UCA qui gate l'entrée dans le référentiel.

**Phase B — orphelins restants** (3 UPDATEs SQL set-based). Tous les SP qui n'ont pas été rattachés en Phase A (essentiellement les hors-périmètre, qui représentent ~98 % du pool d'orphelins) sont matchés en bulk par DOI, NNT et hal_id contre les publications canoniques. Pas de création (le gate `in_perimeter` exclut ces SP par construction). Bénéficie des publications créées en Phase A — un orphelin OpenAlex hors-périmètre dont le DOI matche une publi tout juste créée en Phase A est rattaché à elle.

**Pourquoi cette séparation** :
- La cascade Python a un coût non-trivial par row (prefetches, résolution de conflits DOI, refresh). L'appliquer à 175k orphans hors-périmètre dont presque tous se réduisent à un simple match-par-clé est gaspillé. Le bulk SQL fait la même chose en quelques secondes.
- L'ordre Phase A → Phase B garantit qu'un orphan hors-périmètre dont la publi cible vient d'être créée par un orphan in_perimeter dans le même run sera bien rattaché à elle (avant la séparation, l'ordre des SP dans la boucle unique pouvait laisser certains orphans non-matchés alors qu'ils auraient dû l'être).

**Refresh des métadonnées canoniques**. Après les deux phases, `fetch_stale_publication_ids` identifie les publications dont au moins un `source_publication` a été modifié depuis le dernier refresh (insertion en Phase A/B incluse, mais aussi re-normalisations en amont). `refresh_from_sources` re-agrège les méta (DOI promu par priorité de source, oa_status, abstract, biblio, etc.).

> **Evolutions envisagées**
> - Ajouter de nouveaux identifiants pouvant servir de clé de déduplication: pmid (Pubmed)...
> - Affiner la détection de DOI faussement distincts référençant le même document (DOI versionnés, concept DOI...)
> - Développer un algorithme de déduplication par identité de métadonnées. Piégeux: beaucoup de cas limites ou difficiles. Logique à soigner.
> - Une cascade de matching par métadonnées en complément du matching par identifiants amènerait à réinterroger le découpage Phase A / Phase B (la Phase B pourrait avoir besoin d'autre chose qu'un simple UPDATE SQL).
