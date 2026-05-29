# Chantier — Qualité et cohérence des sujets

*Stub*. À instruire au démarrage du chantier.

## Contexte

Plusieurs problèmes connexes sur la couche `subjects` / `publication_subjects` repérés à l'usage :

1. **Sujets OpenAlex hors-sujet** : les sujets remontés par OpenAlex (`publication_subjects.source = 'openalex'`) sont fréquemment aberrants à l'inspection — bruit de l'algo OpenAlex sur les revues généralistes / pluridisciplinaires, ou attribution thématique de bas score retenue sans filtrage. Le champ `score` est stocké, mais aucun seuil n'est appliqué.

2. **Pas de circuit de curation manuelle** : la colonne `publication_subjects.rejected` existe (boolean default false) mais n'est pas exposée à l'admin. Aucune voie n'est ouverte pour marquer manuellement un sujet comme non pertinent.

3. **Couverture sujets variable** : certaines publis sont sans sujet (origines à inventorier — sources qui ne fournissent pas de sujets, ou rejet pipeline à un point qu'on n'a pas tracé).

4. **Sujets aberrants pour une revue** : signal de cohérence éditoriale non exploité. Une revue d'astronomie qui voit une publi taggée "Cardiologie" → soit le sujet est bruité, soit la publi est mal-attribuée à la revue. Importé de [METIER_publishers-journals 4d](METIER_publishers-journals.md#phase-4--contrôles-de-cohérence).

## Pistes à explorer

À matérialiser au démarrage, dans l'ordre que la user décidera :

- **Seuil de score OpenAlex** : à calibrer empiriquement sur un échantillon (Cf. mémoire de méthode : bottom-up, partir des cas observés). Risque : exclure des sujets légitimes de revues pluridisciplinaires.
- **UI admin curation** : surfacer `publication_subjects.rejected` côté admin (toggle sur la liste des sujets d'une publi). Possiblement étendre à une notion de « sujet manuel » (ajout par bibliothécaire).
- **Sujets attendus par revue** : distribution top-N des sujets observés sur les publis de chaque revue → vue admin signalant les outliers (sujet rarement vu pour cette revue).
- **Co-occurrences suspectes** : `subject_cooccurrences` déjà calculée — exploiter pour détecter des paires improbables sur une même publi.
- **NLP / embeddings** : matcher titre/abstract de la publi vs définition du sujet. Plus coûteux, à arbitrer après quick wins.

## Inputs

- Item TODO « sujets openalex souvent hors sujet » (curation, seuil, NLP).
- Item TODO « enrichissement sujets : audit des publis sans sujet ; sujets "attendus" par revue ».
- [METIER_publishers-journals 4d](METIER_publishers-journals.md) — sujets ↔ revue.

## Liens

- Table `publication_subjects` (`score`, `rejected`) — infrastructure partielle déjà en place.
- Table `subject_cooccurrences` — produit du chantier précédent « Exploiter sujets et mots-clés » (2026-04-30, cf. [0_INDEX](0_INDEX.md)).
