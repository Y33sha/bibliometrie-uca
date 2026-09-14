# Chantier — Identifiants d'auteur mal placés dans un enregistrement source

## Contexte

**Un identifiant partagé au sein d'un enregistrement est requalifié.** `mark_shared_identifiers_dubious` ([identifiers.py](../../domain/persons/identifiers.py)) s'applique au normalize, dans les six extracteurs. Une valeur portée par au moins deux positions d'auteur d'un même enregistrement est une corruption : un identifiant désigne une seule signature par document. Toute position portant une valeur partagée voit ses identifiants suffixés `_dubious`. Ils restent en base, invisibles au matching, qui lit les clés nues. Le rattachement par nom reste ouvert.

**Le consensus d'une valeur d'identifiant est le nom que portent le plus de signatures.** `fetch_identifier_consensus` ([matching.py](../../infrastructure/pipeline/persons/matching.py)) le calcule sur les clés nues, donc hors des `_dubious`. `resolve_identifier_transfers` s'en sert après la cascade personnes pour arbitrer à qui appartient une valeur disputée.

**Des identifiants isolés contredisent le nom qu'ils accompagnent.** Audit sur 3 486 317 positions de 126 226 enregistrements sources : 8 235 positions portent un identifiant dont le nom de consensus ne partage aucun mot avec le nom local, réparties sur 2 409 enregistrements. Par source : DataCite 3 660, HAL 2 137, OpenAlex 1 246, Crossref 1 152, ScanR 40. La contradiction est ponctuelle — 1 249 enregistrements n'en portent qu'une seule — et les enregistrements les plus touchés sont des articles de collaboration de deux à trois mille auteurs, avec 5 à 28 positions fausses.

Exemple : sur `10.1140/epjc/s10052-021-09775-5`, la signature « bogdan malaescu » porte l'ORCID de Stefan Raimund Maschek, que 56 autres signatures attestent.

**Aucun décalage d'indice systématique.** Sur les 54 087 enregistrements portant au moins trois ORCID, 10 sont majoritairement contradictoires, et aucun ne s'explique par un décalage uniforme de la suite des identifiants de −3 à +3 positions.

**Deux limites de la mesure.** 15 045 des 68 646 valeurs d'ORCID apparaissent dans un seul enregistrement source : leur consensus est leur propre nom local, donc une erreur y est invisible. Le test de compatibilité valide dès qu'un mot d'au moins trois lettres est commun, donc 8 235 est un minorant.

**L'effet sur le rattachement des personnes.** Une signature dont l'identifiant désigne quelqu'un d'autre attribue la publication à cette autre personne. Le rejet de la forme de nom, qui est le geste de correction disponible, écarte alors la forme pour la personne entière : le verdict `rejected` refuse même la corroboration par identifiant ([matching.py](../../domain/persons/matching.py)). Sur 8 348 paires (personne, publication) dont une signature détachée porte un ORCID enregistré pour cette personne, 2 325 ont perdu tout lien.

**La table des identités.** `author_identifying_keys` est unique sur `(author_name_normalized, person_identifiers)` et référencée par `source_authorships.identity_id`. Deux lignes de même nom, dont l'une porte le suffixe, sont deux identités distinctes.

## Décisions

À prendre.

## Questions ouvertes

- **Le recalcul du consensus inclut-il les identifiants requalifiés ?** Une valeur recopiée sur trois mille positions d'un même enregistrement pèse trois mille signatures et emporte le consensus ; une valeur isolée mal placée en pèse une et le laisse intact. La réponse dépend du motif de la requalification.
- **Un marqueur par motif ?** `shared` pour la valeur partagée entre positions d'un même enregistrement, `misplaced` pour la contradiction avec le consensus. Détermine la forme du suffixe, ce que le matching lit, et ce qu'une requête de diagnostic sait distinguer.
- **Lever le marqueur quand l'identifiant rejoint le consensus.** La signature retrouve alors son identité nue, ce qui fusionne deux lignes d'`author_identifying_keys` et repointe `source_authorships.identity_id`. À quelle fréquence réévaluer, et que faire de la ligne devenue orpheline ?
- **Où placer la requalification par consensus ?** Le consensus est un agrégat de tout le stock, incalculable au normalize, qui traite un enregistrement à la fois. La passe doit lire le consensus avant la cascade personnes.
- **Convergence.** Requalifier change le consensus, qui change la requalification. Une passe unique par exécution, ou une itération jusqu'au point fixe ?
- **Seuil d'autorité du consensus.** Une valeur attestée par une seule signature a pour consensus son propre nom. En dessous de combien de signatures le consensus ne tranche-t-il rien ?
- **Types d'identifiant concernés.** La règle du partage vaut pour tous les types. Celle du consensus vaut-elle pour `idref`, `hal_person_id` et `researcher_id` autant que pour l'ORCID ?
- **Reprise du stock.** Les identités déjà construites portent les erreurs. Faut-il une reprise, ou la requalification à l'exécution suivante suffit-elle ?

## Phasage

### 1. Cadrage

- [ ] Trancher les questions ouvertes.
- [ ] Mesurer la précision de la règle de consensus sur un échantillon relu.

### 2. Requalification

- [ ] Marqueur par motif.
- [ ] Passe de requalification par consensus, avant la cascade personnes.
- [ ] Levée du marqueur quand l'identifiant rejoint le consensus.

## Liens

- [Gestion des publications dans l'administration](METIER_gestion-admin-des-publications.md) — le volet qui confronte les enregistrements sources d'une publication.
- [Gestion et dédoublonnage assistés de la base personnes](DATA_personnes-dedoublonnage-assiste.md)
