# Plan de rationalisation du pipeline — Bibliométrie UCA

## 1. Problèmes identifiés

### 1.1 Personnes et authorships : le gros sujet

#### 1.1.1 Trois modèles de liaison personne différents selon la source

- **HAL** : `hal_authors.person_id` — un `hal_author` = un compte HAL = une entité persistante. Le `person_id` est sur l'auteur, pas sur l'authorship. Conséquence : quand on lie un `hal_author` à une personne, toutes ses authorships sont couvertes.
- **WoS** : `wos_authors.person_id` — même modèle que HAL. Un `wos_author` = une entité algorithmique (nom normalisé). Le `person_id` est sur l'auteur.
- **OpenAlex** : `openalex_authorships.person_id` — le `person_id` est sur **l'authorship**, pas sur l'auteur. Les entités `openalex_authors` sont non fiables et ne portent plus de `person_id` (colonne supprimée).

Ce modèle asymétrique crée plusieurs problèmes :
- Les scripts doivent gérer 3 logiques différentes pour lier une personne.
- La fusion de personnes doit mettre à jour 3 tables différentes (`hal_authors`, `wos_authors`, `openalex_authorships`).
- Le re-matching après création de nouvelles personnes ne couvre que HAL et WoS (via `create_persons`), pas les `wos_authors` créés avant la personne.

#### 1.1.2 Trou dans le re-matching WoS

Cas concret : Callyane Seve (personne 31824). Créée par la phase B (OA) car ses authorships OA sont dans le périmètre CHU. Mais les `wos_authors` correspondants, créés par `normalize_wos.py` **avant** la personne, gardent `person_id = NULL`. Aucun script ne revient les matcher.

**Solution proposée** : ajouter une passe de re-matching WoS dans `create_persons_from_authorships.py` (après la phase B), ou dans une étape séparée. Cette passe cherche les `wos_authors` sans `person_id` dont le nom normalisé correspond à une personne existante via `person_name_forms`.

#### 1.1.3 Propagation UCA dupliquée et incomplète

Trois chemins propagent `is_uca` et `structure_ids` vers la table `authorships` (vérité) :

1. `populate_uca_flags.sql` — calcule `is_uca`/`structure_ids` sur les authorships **source** (HAL, OA, WoS). N'écrit PAS dans `authorships` (vérité).
2. `create_persons_from_authorships.py` (passe 4) — propage `is_uca`/`structure_ids` depuis les sources vers les `authorships` existantes.
3. `rebuild_authorships.py` — crée de nouvelles lignes `authorships` mais **ne propage PAS** `is_uca`/`structure_ids`.

Conséquence : après `rebuild_authorships`, il faut relancer `populate_uca_flags.sql` ou `create_persons` passe 4 pour que les nouvelles lignes aient `is_uca` correct.

**Solution proposée** : intégrer la propagation (passe 4) directement dans `rebuild_authorships.py`. Le script crée les lignes ET propage les flags en une seule passe. Plus besoin de la double exécution de `populate_uca_flags.sql`.

#### 1.1.4 `rebuild_authorships.py` ne crée des lignes que pour les `person_id` non NULL

Si une authorship source a `person_id = NULL`, elle n'apparaît pas dans la table de vérité. C'est par design (seules les personnes identifiées sont dans la vérité). Mais ça signifie que les authorships orphelines (détachées manuellement, par ex.) disparaissent de la vérité sans laisser de trace.

**Question à trancher** : faut-il garder dans la vérité les authorships sans `person_id` ? Probablement non (ça dupliquerait les sources), mais il faut un mécanisme pour les retrouver facilement (page admin/authorships).

### 1.2 Synchronisation des données dérivées

#### 1.2.1 Pays des publications

`publications.countries` est calculé par `db/refresh_publication_countries.sql` — un script séparé, non intégré aux normalisations.

Chaîne de propagation actuelle :
```
adresses (table addresses.countries)
  ↓ (non automatisé - seulement pour WoS via backfill_wos_addresses)
openalex_authorships.countries / wos_authorships.countries
  ↓ (non automatisé)
openalex_documents.countries / hal_documents.countries / wos_documents.countries
  ↓ (refresh_publication_countries.sql)
publications.countries
```

Problèmes :
- Quand on change le pays d'une adresse dans l'admin, rien ne propage vers les authorships/documents/publications.
- `hal_documents.countries` vient de `hal_structures.country` (pas des adresses).
- `openalex_documents.countries` vient du staging (champ `authorships[].countries`), pas des adresses.
- Seul WoS pourrait utiliser la chaîne adresses → authorships → documents, mais même là c'est un backfill one-shot.

**Solution proposée** : Pour l'instant, garder le script `refresh_publication_countries.sql` dans le pipeline. À terme, il faudrait que l'API "set country on address" propage automatiquement aux documents concernés, mais c'est complexe (une adresse peut être liée à des milliers d'authorships). Plus réaliste : un script de propagation périodique (intégré au pipeline).

#### 1.2.2 Formes de noms des personnes

`person_name_forms` est peuplé par `populate_person_name_forms.py`, qui scanne les authorships sources et enregistre les formes observées. Ce script est dans le pipeline mais la colonne `name_form_normalized` n'est pas recalculée automatiquement quand une personne est fusionnée.

Le merge de personnes (API `/api/persons/{id}/merge`) met à jour les `person_ids` dans `person_name_forms` mais ne supprime pas les doublons ni ne recalcule les normalisations.

**Solution proposée** : la fonction `merge_person()` dans `utils/merge_persons.py` devrait consolider les `person_name_forms` : fusionner les listes `person_ids`, supprimer les entrées de la personne absorbée, dédupliquer.

### 1.3 Scripts morts et confusion

**Fait** : 18 scripts archivés dans `archive/` (migrations et debug). Le dossier `processing/` est propre.

### 1.4 Absence d'audit trail

Les fusions de personnes ne laissent aucune trace exploitable (pas de table d'historique). Quand une fusion est mauvaise, il faut utiliser `split_bad_merges.py` qui nécessite de deviner quelles authorships ré-attribuer.

**Solution proposée** : table `person_merge_log` :
```sql
CREATE TABLE person_merge_log (
    id SERIAL PRIMARY KEY,
    source_person_id INT,
    target_person_id INT,
    source_name TEXT,
    target_name TEXT,
    reason TEXT,  -- 'manual', 'auto_name_conflict', 'auto_lab_duplicate'
    merged_at TIMESTAMPTZ DEFAULT now(),
    merged_by TEXT  -- 'admin', 'script:auto_merge', etc.
);
```

---

## 2. Plan d'action par priorité

### Priorité 1 : Fiabiliser le pipeline existant

#### Action 1.1 : Intégrer la propagation UCA dans `rebuild_authorships.py`
- Après l'INSERT des nouvelles lignes et le peuplement des FK, exécuter la logique de la passe 4 (propagation `is_uca`/`structure_ids` depuis les sources).
- Supprimer la nécessité de relancer `populate_uca_flags.sql` après `rebuild_authorships`.
- **Effort** : 1 jour.

#### Action 1.2 : Ajouter le re-matching WoS
- Nouvelle passe dans `create_persons_from_authorships.py` (entre phase B et passe 4) : pour chaque `wos_authors` avec `person_id IS NULL`, chercher dans `person_name_forms` une correspondance unique.
- Même logique que la phase B (lookup par `name_form_normalized`).
- **Effort** : 0.5 jour.

#### Action 1.3 : Propager les changements de pays d'adresses
- Ajouter dans `refresh_publication_countries.sql` une section qui recalcule `wos_documents.countries` depuis les adresses (via `wos_authorship_addresses` → `addresses.countries`), et `wos_authorships.countries` idem.
- Pour OpenAlex, le pays vient du staging (pas des adresses), donc pas de propagation nécessaire.
- Pour HAL, le pays vient de `hal_structures.country`, pas des adresses non plus.
- **Effort** : 0.5 jour.

### Priorité 2 : Consolider la gestion des personnes

#### Action 2.1 : Audit trail des fusions
- Créer la table `person_merge_log`.
- Modifier `utils/merge_persons.py` pour y écrire à chaque fusion.
- Modifier l'API merge pour logger `merged_by = 'admin'`.
- Modifier les scripts auto (`auto_merge_name_conflict_pairs.py`, `merge_lab_duplicates.py`) pour logger aussi.
- **Effort** : 1 jour.

#### Action 2.2 : Consolider `person_name_forms` lors des fusions
- Dans `merge_person()` : fusionner les `person_ids` des formes de la personne absorbée vers la personne cible.
- Supprimer les formes devenues identiques (même `name_form_normalized` + même `person_ids`).
- **Effort** : 0.5 jour.

#### Action 2.3 : Recréer la page admin/authorships
- Page listant les authorships (vérité) avec filtres : par publication, par personne, par labo, par source, orphelines (person_id IS NULL).
- Permet de réattribuer manuellement une authorship orpheline à une personne.
- **Effort** : 1 jour.

### Priorité 3 : Automatisation

#### Action 3.1 : Mode weekly dans l'orchestrateur
- Extraction des 6 derniers mois uniquement (paramètre `--years` ou filtre date dans les scripts d'extraction).
- Pas de cross-imports ni d'enrichissements.
- Pas de `merge_lab_duplicates.py` (interactif).
- **Effort** : 0.5 jour (les scripts sont déjà idempotents).

#### Action 3.2 : Mode monthly
- Pipeline complet + cross-imports + enrichissements.
- Nettoyage des orphelins (personnes sans authorships, publications sans sources).
- **Effort** : 0.5 jour.

#### Action 3.3 : Programmation cron
- Weekly : dimanche soir.
- Monthly : 1er du mois.
- Via crontab ou systemd timer.
- Notification par email en cas d'erreur.
- **Effort** : 0.5 jour.

---

## 3. Ordre de réalisation recommandé

| Étape | Action | Prérequis | Effort |
|-------|--------|-----------|--------|
| 1 | Propagation UCA dans rebuild_authorships (1.1) | — | 1j |
| 2 | Re-matching WoS (1.2) | — | 0.5j |
| 3 | Audit trail fusions (2.1) | — | 1j |
| 4 | Consolider person_name_forms (2.2) | 2.1 | 0.5j |
| 5 | Propagation pays adresses (1.3) | — | 0.5j |
| 6 | Page admin/authorships (2.3) | — | 1j |
| 7 | Mode weekly/monthly (3.1, 3.2) | — | 1j |
| 8 | Cron (3.3) | 3.1 | 0.5j |

**Total estimé** : 6 jours de développement.

---

## 4. Points en suspens (à décider)

1. **Périmètre élargi (CHU/INP)** : faut-il continuer à créer des personnes pour les authorships CHU/INP non-UCA ? Ça gonfle la base de personnes mais permet de traquer les co-publications.

2. **Entités `openalex_authors`** : la table existe toujours, sans `person_id`. Faut-il la garder (référence pour les openalex_id) ou la supprimer à terme ?

3. **Réimport complet vs incrémental** : quand on relance `normalize_openalex.py`, les records déjà normalisés ne sont pas re-traités (flag `processed`). Si les métadonnées ont changé côté OpenAlex (nouveau DOI, nouveau type), on ne le voit pas. Faut-il un mode `--force-reprocess` ?

4. **Gestion des suppressions** : si un document est retiré de HAL ou rétracté d'OpenAlex, rien ne le détecte. Les données restent en base indéfiniment.
