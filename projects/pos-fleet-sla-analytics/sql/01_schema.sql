-- 01_schema.sql — схема хранилища SLA-аналитики
-- Суммы в копейках (INTEGER). Время — ISO-строки «YYYY-MM-DD HH:MM:SS».

DROP TABLE IF EXISTS dim_contract;
CREATE TABLE dim_contract (
    contract_id          TEXT PRIMARY KEY,
    partner_id           TEXT NOT NULL,
    partner_name         TEXT NOT NULL,
    monthly_fee_kop      INTEGER NOT NULL,
    p1_hours             INTEGER NOT NULL,
    p2_hours             INTEGER NOT NULL,
    p3_hours             INTEGER NOT NULL,
    penalty_per_hour_pct REAL    NOT NULL,
    penalty_cap_pct      REAL    NOT NULL,
    period_from          TEXT    NOT NULL,
    period_to            TEXT    NOT NULL
);

DROP TABLE IF EXISTS dim_device;
CREATE TABLE dim_device (
    device_id   TEXT PRIMARY KEY,
    serial      TEXT NOT NULL,
    vendor      TEXT NOT NULL,
    model       TEXT NOT NULL,
    device_type TEXT NOT NULL CHECK (device_type IN ('POS', 'KIOSK', 'ATM')),
    partner_id  TEXT NOT NULL,
    partner_name TEXT NOT NULL,
    contract_id TEXT NOT NULL REFERENCES dim_contract (contract_id),
    region      TEXT NOT NULL,
    city        TEXT NOT NULL,
    install_date TEXT NOT NULL,
    status      TEXT NOT NULL
);

DROP TABLE IF EXISTS fact_incident;
CREATE TABLE fact_incident (
    incident_id       TEXT PRIMARY KEY,
    device_id         TEXT NOT NULL REFERENCES dim_device (device_id),
    contract_id       TEXT NOT NULL,
    opened_at         TEXT NOT NULL,
    first_response_at TEXT NOT NULL,
    closed_at         TEXT,
    severity          INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 4),
    channel           TEXT NOT NULL,
    error_code        TEXT NOT NULL,
    error_text        TEXT NOT NULL,
    family            TEXT NOT NULL,
    sla_hours         INTEGER NOT NULL
);

CREATE INDEX idx_incident_device ON fact_incident (device_id, opened_at);
CREATE INDEX idx_incident_contract ON fact_incident (contract_id, opened_at);

-- Период наблюдения задаётся выгрузкой, а не диапазоном инцидентов:
-- устройство могло не сломаться ни разу, но всё равно входит в знаменатель.
DROP TABLE IF EXISTS dim_period;
CREATE TABLE dim_period (
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    period_days  INTEGER NOT NULL
);
