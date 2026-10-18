-- ============================================================================
--  PROJECT RESILIENCE-ALPHA — Schéma du SI de paiement (fictif)
--  Contraintes portées par la base : FK, UNIQUE, CHECK (conventions PostgreSQL).
--  Aucune donnée bancaire réelle (sujet §1).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ------------------------------------------------------------- Utilisateurs
CREATE TABLE IF NOT EXISTS app_user (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      TEXT        NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    role          TEXT        NOT NULL DEFAULT 'customer'
                              CHECK (role IN ('customer', 'operator', 'admin')),
    locked        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------- Comptes
CREATE TABLE IF NOT EXISTS account (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_id   BIGINT      NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    iban_fake  TEXT        NOT NULL UNIQUE,
    balance    NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    currency   CHAR(3)     NOT NULL DEFAULT 'EUR',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_account_owner ON account(owner_id);

-- ------------------------------------------------------------- Transactions
CREATE TABLE IF NOT EXISTS payment_tx (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    src_account BIGINT        NOT NULL REFERENCES account(id),
    dst_account BIGINT        NOT NULL REFERENCES account(id),
    amount      NUMERIC(14,2) NOT NULL CHECK (amount > 0),
    status      TEXT          NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'settled', 'rejected')),
    reference   TEXT          NOT NULL UNIQUE,
    is_canary   BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK (src_account <> dst_account)
);
CREATE INDEX IF NOT EXISTS idx_tx_created ON payment_tx(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tx_status  ON payment_tx(status);
