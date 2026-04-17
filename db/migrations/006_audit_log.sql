-- Migration 006 : table audit_log — traçabilité des opérations destructives
-- déclenchées depuis l'admin HTTP (fusions, suppressions, décisions).
--
-- Le pipeline n'est PAS audité ici (volumétrie trop forte, déjà tracé par
-- les rapports pipeline et les colonnes created_at/updated_at par ligne).

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type     TEXT        NOT NULL,
    aggregate_type TEXT        NOT NULL,
    aggregate_id   INTEGER,
    payload        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    user_id        TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Historique d'une entité : "toutes les opérations sur la personne #1234"
CREATE INDEX IF NOT EXISTS audit_log_aggregate_idx
    ON audit_log (aggregate_type, aggregate_id);

-- Toutes les occurrences d'un type d'événement sur une période
CREATE INDEX IF NOT EXISTS audit_log_event_type_idx
    ON audit_log (event_type, created_at DESC);

-- Timeline globale (dernière activité admin)
CREATE INDEX IF NOT EXISTS audit_log_created_at_idx
    ON audit_log (created_at DESC);

COMMENT ON TABLE audit_log IS
    'Trace des opérations destructives/décisionnelles déclenchées via l''admin HTTP. Les opérations du pipeline ne sont pas auditées.';
COMMENT ON COLUMN audit_log.event_type IS
    'Type d''événement, notation pointée : person.merged, publication.excluded, structure.deleted, etc.';
COMMENT ON COLUMN audit_log.aggregate_type IS
    'Type de l''entité affectée : person, publication, structure, journal, publisher, authorship.';
COMMENT ON COLUMN audit_log.aggregate_id IS
    'ID de l''entité affectée, NULL si l''entité a été supprimée et n''a pas d''équivalent survivant.';
COMMENT ON COLUMN audit_log.payload IS
    'Données utiles pour l''audit : source_id d''une fusion, champs modifiés, raison, etc.';
COMMENT ON COLUMN audit_log.user_id IS
    'Utilisateur admin authentifié ayant déclenché l''opération (middleware auth). NULL théoriquement impossible quand l''entrée est écrite.';
