-- Ajout de nouveaux types de documents à l'enum doc_type
-- Types issus de l'audit croisé HAL / OpenAlex / WoS

ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'dataset';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'software';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'patent';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'hdr';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'memoir';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'poster';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'letter';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'erratum';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'retraction';
