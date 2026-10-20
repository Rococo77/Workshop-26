-- ============================================================================
--  Validation faciale des virements (DeepFace).
--  Idempotent : rejouable sur une base existante sans `down -v` :
--    docker exec -i ra-postgres psql -U payuser -d paymentdb \
--      < services/payment-api/db/init/03_face_verification.sql
--
--  Minimisation (RGPD art. 9, donnée biométrique) : AUCUNE photo n'est
--  stockée, seulement le vecteur d'empreinte calculé par le modèle.
-- ============================================================================

-- ------------------------------------------------- Empreinte de référence
CREATE TABLE IF NOT EXISTS face_enrollment (
    user_id    BIGINT             PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
    model_name TEXT               NOT NULL,
    embedding  DOUBLE PRECISION[] NOT NULL CHECK (cardinality(embedding) > 0),
    created_at TIMESTAMPTZ        NOT NULL DEFAULT now()
);

-- ------------------------------------------- Virement en attente de visage
ALTER TABLE payment_tx ADD COLUMN IF NOT EXISTS expires_at       TIMESTAMPTZ;
ALTER TABLE payment_tx ADD COLUMN IF NOT EXISTS settled_at       TIMESTAMPTZ;
ALTER TABLE payment_tx ADD COLUMN IF NOT EXISTS confirm_attempts SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE payment_tx ADD COLUMN IF NOT EXISTS reject_reason    TEXT;

-- --------------------------------------- Journal d'audit des vérifications
-- Traçabilité (DORA) et base du verrouillage anti-force brute par utilisateur.
CREATE TABLE IF NOT EXISTS face_verification_log (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    tx_id      BIGINT      REFERENCES payment_tx(id),
    purpose    TEXT        NOT NULL CHECK (purpose IN ('enroll', 'confirm')),
    result     TEXT        NOT NULL,
    distance   REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_face_log_user ON face_verification_log(user_id, created_at DESC);
