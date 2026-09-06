---
name: doc-style
description: >
  Relit et resserre la documentation, les commentaires et les docstrings : supprime le métadiscours, les périphrases, les doubles négations, les redites du code et les formules d'auto-justification. Lance Vale avec le style maison, puis corrige. Sert aussi à enrichir le style maison quand une tournure est signalée. À utiliser dès qu'on demande de relire ou corriger de la doc, un README, des commentaires ou des docstrings — et aussi juste après avoir écrit ou modifié de la documentation, même sans demande explicite.
allowed-tools: Read, Edit, Bash, Grep, Glob
---

# Relecture de documentation

## Procédure

1. Lire `reference.md` (paires avant/après) avant toute correction.
2. `vale <chemin>` sur les fichiers visés. Si Vale est absent, le dire et continuer sur les seuls contrôles manuels ci-dessous.
3. Traiter chaque alerte.
4. Passer le contrôle "paragraphe amovible".
5. Montrer le diff. Ne rien committer.

## Règle de réparation

**Supprimer, pas reformuler.** Une reformulation conserve le volume, or c'est le volume le problème. Devant une alerte : retirer la phrase entière, puis vérifier ce que le texte a perdu. Ne reformuler que s'il a perdu quelque chose d'utile.

## Contrôle hors Vale

- **Le paragraphe amovible.** Au moment de retoucher un paragraphe, commencer par le supprimer. Se demander ce dont le lecteur a **besoin** pour que le texte reste intelligible et n'induise pas en erreur. N'écrire que ce qui est strictement nécessaire.

## Contraintes de forme

- Docstring de fonction simple : 4 lignes maximum. Une ligne de résumé à l'indicatif présent, puis les seuls paramètres non évidents.
- Une idée par phrase. 28 mots maximum.
- Aucun adjectif d'éloge, aucun titre décoratif en commentaire.

## Contenus indésirables

- **Une affirmation fausse est d'abord une candidate à la suppression.** Avant de la rectifier, se demander si le lecteur a besoin du fait.
- **Redondances.** Quand une phrase a deux parties séparées par deux-points, supprimer une des deux si l'une ne fait que redire l'autre.
- **Détails superflus.** Supprimer les détails ou explications dont un nouveau venu n'a pas besoin à cet endroit.
- **Plaidoyers.** Supprimer les phrases qui semblent répondre à une objection que personne n'a faite. La documentation ne doit pas plaider ni argumenter.
- **Références au passé.** Relire la prose du point de vue d'un nouveau venu qui ne connaît ni l'état antérieur du code, ni le contexte de la conversation. Bannir tout vocabulaire ancré temporellement (`nouveau`, `désormais`, `ne plus`...). Ne jamais renvoyer à des fichiers transitoires (todo, roadmaps).

## Style

- **Jargon.** Le jargon technique usuel est normal. Eviter le jargon interne au projet et les abréviations maison qu'un nouveau venu ne peut pas comprendre sans traduction (`SP` pour source_publication, `pub` pour publication...).
- **Anglicismes.** Toujours utiliser les termes les plus usuels, anglais ou français. Ne pas sur-franciser par purisme (on dit *repository* et non "dépôt" quand on parle des classes d'accès aux données).
- **Pronoms « y » et « en ».** Ne les employer que si l'antécédent est le groupe nominal qui précède immédiatement, dans la même phrase. Sinon, répéter le nom.
- **Phrases négatives.** Les remplacer chaque fois que possible par des phrases positives. Si une phrase décrit ce que le code ne fait pas ou plus, la supprimer. Eviter les négations multiples.
- **Un mot par notion.** Ne pas chercher l'élégance littéraire. Ne pas varier le vocabulaire pour éviter une répétition : en documentation technique, répéter le même mot est un service rendu au lecteur, pas une faiblesse de style.
- **Simplicité et précision.** Remplacer les mots vagues par des équivalents précis ("la source atteste d'un document" => "le document est présent dans la source"; "la source ignore le document" => "le document est absent de la source").

## Alimentation

Quand l'utilisatrice signale une tournure qui l'agace, la classer :

- Expression figée remplaçable mot à mot → ajouter au `swap` de `styles/Maison/Periphrases.yml`, avec le substitut qu'elle propose. Si elle n'en propose pas, en suggérer un et le lui faire valider.
- Défaut de structure (redite, remplissage, longueur, ton) → ajouter une paire AVANT / APRÈS dans `reference.md`, en gardant son texte exact en AVANT.
- Motif récurrent qui n'est pas une expression figée → proposer une nouvelle règle `existence` dans `styles/Maison/`, et la lui soumettre avant de l'écrire.

Après tout ajout au style Vale : lancer `vale .` et rapporter le nombre de déclenchements. Au-delà d'une dizaine sur du texte déjà relu, la règle est trop large — la restreindre avant de la garder.
