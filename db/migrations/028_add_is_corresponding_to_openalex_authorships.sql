ALTER TABLE openalex_authorships
    ADD COLUMN IF NOT EXISTS is_corresponding boolean DEFAULT false;
