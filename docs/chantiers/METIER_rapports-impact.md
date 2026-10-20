# Chantier — Indicateurs d'impact dans les rapports par laboratoire

## Contexte

Le script `data/reports/bibliometrie/structure_report.py` produit un rapport par laboratoire. Sa synthèse donne par année le nombre de publications, le nombre de publications où un auteur de l'unité tient un rôle clé et le nombre de publications dans le top 10 % des plus citées. Les rôles clés sont auteur correspondant, premier ou dernier auteur, selon l'unité.

Les destinataires des rapports demandent les indicateurs d'un tableau InCites. Ses lignes sont les articles originaux, les autres publications et les publications non anglophones. Ses colonnes :

- nombre de publications ;
- nombre de publications avec un auteur premier, dernier ou correspondant (« PDC ») ;
- total des citations ;
- indice de citation normalisé moyen, sur toutes les publications et sur les publications PDC ;
- nombre de publications dans le top 10 % des plus citées, sur toutes les publications et sur les publications PDC.

### Données disponibles

Mesures sur les publications du périmètre parues de 2022 à 2025, des types retenus par le rapport : 17 862 publications.

- **Citations.** `source_publications.impact->'cited_by_count'`, fourni par OpenAlex, Crossref, WoS, DataCite et une partie des notices ScanR. 17 471 publications ont au moins un compte. Somme des maxima par publication : 148 825. Somme des comptes OpenAlex : 141 068. Somme des comptes WoS : 101 756, sur 9 188 publications.
- **Indice normalisé.** Le FWCI d'OpenAlex (`impact->'fwci'`), présent pour 16 936 publications. 394 publications ont plusieurs notices OpenAlex aux FWCI différents.
- **Top 10 % et rôles clés.** Calculés par le rapport.
- **Langue.** `publications.language` : 11 845 publications en anglais, 5 689 en français, 46 sans langue.

### Écarts avec InCites

InCites compte les publications indexées dans le WoS et les citations du WoS. Son indice normalisé (CNCI) rapporte les citations à la moyenne mondiale par catégorie WoS. Le FWCI d'OpenAlex rapporte les citations à la moyenne par thématique OpenAlex. Les valeurs sont comparables sans être identiques.

## Décisions

- **Citations d'une publication.** Le maximum des `cited_by_count` de ses notices. Un écart suspect entre sources donne lieu à une vérification ciblée sur d'autres sources en ligne. 40 publications ont au moins 10 citations et un maximum supérieur au double du compte OpenAlex.
- **Calcul à la requête**, dans le script de rapport. La consolidation des indicateurs dans `publications.publications`, nécessaire aux filtres de l'interface, relève d'un chantier ultérieur.
- **Rôles clés.** Ceux du rapport, choisis par unité. Le tableau InCites vient de l'Inserm : ses rôles PDC conviennent à la médecine.
- **Présentation.** Lignes par année. La mise en forme PDF décide des agrégations éventuelles.

## Phasage

### Phase 1 — Requêtes

- [ ] Total des citations
- [ ] FWCI moyen, sur toutes les publications et sur les publications avec rôle clé
- [ ] Ventilation en articles, autres publications et publications non anglophones

### Phase 2 — Intégration aux rapports

- [ ] Présentation des indicateurs dans le rapport
- [ ] Comparaison du rapport d'un laboratoire avec son tableau InCites
- [ ] Vérification ciblée des écarts suspects entre sources

### Phase 3 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- **Articles originaux.** Type `article` seul, ou avec `review`. Le prototype retient `article` seul.
- **Publications non anglophones.** Le prototype les prend dans tous les types, langue renseignée.
- **FWCI d'une publication à plusieurs notices OpenAlex.** Maximum, moyenne ou notice unique. Le prototype retient le maximum, comme pour les citations et le top 10 %.
- **Publications sans FWCI** (926). Le prototype les exclut de la moyenne.
