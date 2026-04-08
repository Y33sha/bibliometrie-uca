ALTER TABLE wos_authorships
    ADD COLUMN IF NOT EXISTS role text;
