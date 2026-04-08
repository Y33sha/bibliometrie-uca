ALTER TABLE hal_authorships
    ADD COLUMN IF NOT EXISTS is_corresponding boolean DEFAULT false,
    ADD COLUMN IF NOT EXISTS role text;
