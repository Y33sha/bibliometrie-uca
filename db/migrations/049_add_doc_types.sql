-- Nouveaux types de documents
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'book_review';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'data_paper';
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'proceedings';
