-- Migration 015 : compteur d'occurrences sur subjects + table de co-occurrences.
--
-- Phase 5 du chantier sujets / mots-clés (cf docs/chantiers/sujets-mots-cles.md).
-- Prérequis pour la page sujets et l'exploration en graphe : on a besoin
-- d'une métrique de fréquence (taille des nœuds) et d'une matrice de
-- co-occurrences (arêtes du graphe).
--
-- Stratégie de recalcul : phase pipeline `cooccurrences` qui recompute tout
-- en SQL (UPDATE subjects + TRUNCATE+INSERT subject_cooccurrences). Idempotent.

ALTER TABLE subjects ADD COLUMN usage_count INT NOT NULL DEFAULT 0;

-- Index pour l'ordre par fréquence (page liste, top sujets).
CREATE INDEX subjects_usage_count_idx ON subjects (usage_count DESC);

CREATE TABLE subject_cooccurrences (
    subject_a_id INT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    subject_b_id INT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    count INT NOT NULL,

    PRIMARY KEY (subject_a_id, subject_b_id),

    -- On ne stocke qu'une orientation (a < b) pour éviter de dupliquer
    -- (a,b) et (b,a). Les queries de voisinage matchent les deux colonnes.
    CONSTRAINT subject_cooccurrences_ordered CHECK (subject_a_id < subject_b_id)
);

-- Index pour la recherche bidirectionnelle des voisins d'un sujet.
CREATE INDEX subject_cooccurrences_b_idx ON subject_cooccurrences (subject_b_id);

-- Index pour le tri par poids (top voisins).
CREATE INDEX subject_cooccurrences_count_idx ON subject_cooccurrences (count DESC);
