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

- **Citations.** `source_records.impact->'cited_by_count'`, fourni par OpenAlex, Crossref, WoS, DataCite et une partie des notices ScanR. 17 471 publications ont au moins un compte. Somme des maxima par publication : 148 825. Somme des comptes OpenAlex : 141 068. Somme des comptes WoS : 101 756, sur 9 188 publications.
- **Indice normalisé.** Le FWCI d'OpenAlex (`impact->'fwci'`), présent pour 16 936 publications. 394 publications ont plusieurs notices OpenAlex aux FWCI différents.
- **Top 10 % et rôles clés.** Calculés par le rapport.
- **Langue.** `publications.language` : 11 845 publications en anglais, 5 689 en français, 46 sans langue.

### Écarts avec InCites

InCites compte les publications indexées dans le WoS et les citations du WoS. Son indice normalisé (CNCI) rapporte les citations à la moyenne mondiale par catégorie WoS. Le FWCI d'OpenAlex rapporte les citations à la moyenne par thématique OpenAlex. Les valeurs sont comparables sans être identiques.

## Décisions

- **Citations d'une publication.** Le maximum des `cited_by_count` de ses notices. Un écart suspect entre sources donne lieu à une vérification ciblée sur d'autres sources en ligne. 40 publications ont au moins 10 citations et un maximum supérieur au double du compte OpenAlex.
- **Calcul à la requête**, dans le script de rapport. La consolidation des indicateurs dans `publications.publications`, nécessaire aux filtres de l'interface, relève d'un chantier ultérieur.
- **FWCI et top 10 % d'OpenAlex conservés quand le compte OpenAlex est aberrant.** OpenAlex sous-compte les citations de certaines publications : 0 citation pour un article de la collaboration ATLAS cité 59 fois dans le WoS, avec la même valeur dans l'API. 68 publications ont un compte OpenAlex inférieur à la moitié du maximum des autres sources, ce maximum étant d'au moins 5 (0,38 %). Les écarter fait passer le FWCI moyen de 1,652 à 1,656 et la part dans le top 10 % de 16,48 % à 16,51 %. Le laboratoire le plus touché, de physique des particules, en compte 45 : son FWCI moyen passe de 2,16 à 2,21.
- **Groupes de publications.** Articles originaux : type `article`, qui comprend les short communications dans toutes les sources. Autres publications : articles de synthèse et conference papers. Publications non anglophones : publications des deux premiers groupes dont la langue est connue et autre que l'anglais.
- **Rôles clés.** Ceux du rapport, choisis par unité. Le tableau InCites vient de l'Inserm : ses rôles PDC conviennent à la médecine.
- **Période.** Années complètes, de 2020 à 2025.
- **Présentation.** Lignes par année. La mise en forme PDF décide des agrégations éventuelles.

## Phasage

### Phase 1 — Requêtes

- [x] Total des citations
- [x] FWCI moyen, sur toutes les publications et sur les publications avec rôle clé
- [x] Ventilation en articles, autres publications et publications non anglophones

### Phase 2 — Intégration aux rapports

- [x] Section « Impact » du rapport : un tableau par groupe de publications, en lignes par année
- [ ] Comparaison du rapport d'un laboratoire avec son tableau InCites
- [x] Vérification ciblée des écarts suspects entre sources

### Phase 3 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- **FWCI d'une publication à plusieurs notices OpenAlex.** Maximum, moyenne ou notice unique. Le prototype retient le maximum, comme pour les citations et le top 10 %.
- **Publications sans FWCI** (926). Le prototype les exclut de la moyenne.
