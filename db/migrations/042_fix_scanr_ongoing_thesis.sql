-- Corriger les publications ScanR qui sont des thèses en cours
UPDATE publications p
SET doc_type = 'ongoing_thesis'
FROM source_documents sd
WHERE sd.publication_id = p.id
  AND sd.source = 'scanr'
  AND sd.doc_type = 'ongoing_thesis'
  AND p.doc_type = 'thesis';
