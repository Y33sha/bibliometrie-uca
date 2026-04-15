-- Migration 062 : Ajouter resolved_at sur addresses
--
-- Permet à resolve_addresses.py de ne traiter que les nouvelles adresses
-- en mode incrémental (daily). Le backfill marque les adresses existantes
-- comme déjà résolues.

ALTER TABLE addresses ADD COLUMN IF NOT EXISTS resolved_at timestamptz;

-- Backfill : marquer les adresses existantes comme résolues
UPDATE addresses SET resolved_at = created_at WHERE resolved_at IS NULL;
