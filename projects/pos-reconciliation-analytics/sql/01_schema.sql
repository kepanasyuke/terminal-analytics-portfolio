-- 01_schema.sql
-- Схема хранилища: staging-слой (как пришло из источников) + измерения + факты.
-- Все суммы — в копейках (INTEGER), чтобы не ловить погрешность плавающей точки на деньгах.

DROP TABLE IF EXISTS dim_device;
CREATE TABLE dim_device (
    device_id    TEXT PRIMARY KEY,
    serial       TEXT NOT NULL,
    vendor       TEXT NOT NULL,
    model        TEXT NOT NULL,
    device_type  TEXT NOT NULL CHECK (device_type IN ('POS', 'KIOSK', 'ATM')),
    partner_id   TEXT NOT NULL,
    partner_name TEXT NOT NULL,
    region       TEXT NOT NULL,
    city         TEXT NOT NULL,
    install_date TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('ACTIVE', 'SERVICE', 'DECOMMISSIONED')),
    sw_version   TEXT
);

DROP TABLE IF EXISTS dim_merchant;
CREATE TABLE dim_merchant (
    merchant_id   TEXT PRIMARY KEY,
    partner_id    TEXT NOT NULL,
    partner_name  TEXT NOT NULL,
    segment       TEXT NOT NULL,
    merchant_name TEXT NOT NULL
);

DROP TABLE IF EXISTS fact_incident;
CREATE TABLE fact_incident (
    incident_id   TEXT PRIMARY KEY,
    device_id     TEXT NOT NULL REFERENCES dim_device (device_id),
    opened_at     TEXT NOT NULL,
    closed_at     TEXT,
    severity      INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 4),
    error_code    TEXT NOT NULL,
    error_text    TEXT,
    symptom       TEXT,
    source_system TEXT NOT NULL
);

DROP TABLE IF EXISTS stg_terminal;
CREATE TABLE stg_terminal (
    rrn         TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    device_type TEXT,
    partner_id  TEXT,
    merchant_id TEXT,
    txn_ts      TEXT NOT NULL,
    op_type     TEXT NOT NULL,
    amount_kop  INTEGER NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'RUB',
    status      TEXT NOT NULL,
    auth_code   TEXT,
    error_code  TEXT
);

DROP TABLE IF EXISTS stg_acquiring;
CREATE TABLE stg_acquiring (
    rrn             TEXT NOT NULL,
    device_id       TEXT NOT NULL,
    device_type     TEXT,
    partner_id      TEXT,
    merchant_id     TEXT,
    txn_ts          TEXT NOT NULL,
    op_type         TEXT NOT NULL,
    amount_kop      INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'RUB',
    status          TEXT NOT NULL,
    auth_code       TEXT,
    error_code      TEXT,
    settlement_date TEXT
);

CREATE INDEX idx_terminal_rrn ON stg_terminal (rrn);
CREATE INDEX idx_acquiring_rrn ON stg_acquiring (rrn);
CREATE INDEX idx_terminal_ts ON stg_terminal (txn_ts);
CREATE INDEX idx_acquiring_ts ON stg_acquiring (txn_ts);
CREATE INDEX idx_incident_device ON fact_incident (device_id, opened_at);
