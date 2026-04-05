-- Migration 009 : vue des publications actives (exclut peer_review)
-- 2026-04-05

CREATE OR REPLACE VIEW v_active_publications AS
SELECT id FROM publications WHERE doc_type != 'peer_review';
