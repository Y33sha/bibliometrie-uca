-- Migration 014 : tables `subjects` et `publication_subjects`.
--
-- Phase 1 du chantier sujets/mots-clés (cf docs/chantiers/sujets-mots-cles.md).
-- Modélisation : table unique `subjects` avec discriminant `kind`
-- ('free' = mot-clé libre, 'concept' = terme contrôlé d'une ontologie).
-- Pas d'ontologie pivot ; chaque ontologie cohabite via la colonne `ontology`.
-- Liaison `publication_subjects` qui garde la trace de la source d'origine
-- pour que l'agrégation côté API puisse dédupliquer ou exposer la provenance.

CREATE TABLE subjects (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('free', 'concept')),
    label TEXT NOT NULL,
    language TEXT,
    ontology TEXT,
    ontology_id TEXT,
    parent_id INT REFERENCES subjects(id) ON DELETE SET NULL,
    level INT,
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Cohérence kind/ontology : ontology obligatoire pour les concepts,
    -- absente pour les libres.
    CONSTRAINT subjects_concept_has_ontology
        CHECK (
            (kind = 'concept' AND ontology IS NOT NULL AND ontology_id IS NOT NULL)
            OR (kind = 'free' AND ontology IS NULL AND ontology_id IS NULL)
        )
);

-- Unicité des concepts par (ontology, ontology_id).
CREATE UNIQUE INDEX subjects_concept_key
    ON subjects (ontology, ontology_id)
    WHERE kind = 'concept';

-- Unicité des libres par (lower(label), language). On normalise NULL→''
-- pour que les libres sans langue identifiée soient bien dédupliqués.
CREATE UNIQUE INDEX subjects_free_key
    ON subjects (lower(label), COALESCE(language, ''))
    WHERE kind = 'free';

-- Index pour les recherches par label (Phase 6 — recherche par sujet).
CREATE INDEX subjects_label_lower_idx ON subjects (lower(label));

-- Liaison publications ↔ subjects.
CREATE TABLE publication_subjects (
    publication_id INT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    subject_id INT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    source source_type NOT NULL,
    score REAL,
    created_at TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (publication_id, subject_id, source)
);

CREATE INDEX publication_subjects_subject_idx
    ON publication_subjects (subject_id);
