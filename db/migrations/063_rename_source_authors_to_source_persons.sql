-- Migration 063 : Renommer source_authors → source_persons
-- Et source_authorships.source_author_id → source_person_id

-- 1. Renommer la table
ALTER TABLE source_authors RENAME TO source_persons;

-- 2. Renommer la séquence
ALTER SEQUENCE source_authors_id_seq RENAME TO source_persons_id_seq;

-- 3. Renommer la colonne FK sur source_authorships
ALTER TABLE source_authorships RENAME COLUMN source_author_id TO source_person_id;

-- 4. Renommer les contraintes sur source_persons
ALTER TABLE source_persons RENAME CONSTRAINT source_authors_pkey TO source_persons_pkey;
ALTER TABLE source_persons RENAME CONSTRAINT source_authors_source_source_id_key TO source_persons_source_source_id_key;
ALTER TABLE source_persons RENAME CONSTRAINT source_authors_id_not_null TO source_persons_id_not_null;
ALTER TABLE source_persons RENAME CONSTRAINT source_authors_source_not_null TO source_persons_source_not_null;
ALTER TABLE source_persons RENAME CONSTRAINT source_authors_source_id_not_null TO source_persons_source_id_not_null;
ALTER TABLE source_persons RENAME CONSTRAINT source_authors_full_name_not_null TO source_persons_full_name_not_null;
ALTER TABLE source_persons RENAME CONSTRAINT source_authors_person_id_fkey TO source_persons_person_id_fkey;

-- 5. Renommer les index
ALTER INDEX idx_source_authors_person RENAME TO idx_source_persons_person;
ALTER INDEX idx_source_authors_orcid RENAME TO idx_source_persons_orcid;
ALTER INDEX idx_source_authors_idref RENAME TO idx_source_persons_idref;

-- 6. Renommer la FK sur source_authorships
ALTER TABLE source_authorships RENAME CONSTRAINT source_authorships_source_author_id_fkey TO source_authorships_source_person_id_fkey;

-- 7. Renommer l'index et contrainte unique sur source_authorships
ALTER TABLE source_authorships RENAME CONSTRAINT source_authorships_source_document_id_source_author_id_key TO source_authorships_source_document_id_source_person_id_key;
ALTER INDEX idx_sa_source_author RENAME TO idx_sa_source_person;
