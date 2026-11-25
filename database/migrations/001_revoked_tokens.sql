-- Apply to a database created from an older schema.sql (before login/logout existed).
-- New databases already get this table from database/schema.sql.
BEGIN;
CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti VARCHAR(64) PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS revoked_tokens_expires_at_idx ON revoked_tokens(expires_at);
CREATE INDEX IF NOT EXISTS revoked_tokens_member_idx ON revoked_tokens(member_id);
COMMIT;
