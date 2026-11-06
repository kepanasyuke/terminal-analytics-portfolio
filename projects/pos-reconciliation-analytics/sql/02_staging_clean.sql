-- 02_staging_clean.sql
-- Очистка staging: выявление полных дублей и дедупликация перед сверкой.
-- Дубликаты не выбрасываются молча — они фиксируются в stg_acquiring_duplicates
-- и попадают в отчёт как отдельный класс расхождений.

DROP TABLE IF EXISTS stg_terminal_clean;
CREATE TABLE stg_terminal_clean AS
SELECT rrn, device_id, device_type, partner_id, merchant_id, txn_ts, op_type,
       amount_kop, currency, status, auth_code, error_code
FROM (
    SELECT s.*,
           ROW_NUMBER() OVER (PARTITION BY rrn ORDER BY txn_ts, amount_kop, status) AS rn
    FROM stg_terminal s
)
WHERE rn = 1;

DROP TABLE IF EXISTS stg_acquiring_duplicates;
CREATE TABLE stg_acquiring_duplicates AS
SELECT rrn,
       COUNT(*)                     AS rows_cnt,
       COUNT(*) - 1                 AS extra_rows,
       MAX(amount_kop) - MIN(amount_kop) AS amount_spread_kop,
       MIN(txn_ts)                  AS first_ts,
       MAX(txn_ts)                  AS last_ts,
       MIN(device_id)               AS device_id,
       MIN(partner_id)              AS partner_id
FROM stg_acquiring
GROUP BY rrn
HAVING COUNT(*) > 1;

DROP TABLE IF EXISTS stg_acquiring_clean;
CREATE TABLE stg_acquiring_clean AS
SELECT rrn, device_id, device_type, partner_id, merchant_id, txn_ts, op_type,
       amount_kop, currency, status, auth_code, error_code, settlement_date
FROM (
    SELECT s.*,
           ROW_NUMBER() OVER (PARTITION BY rrn ORDER BY txn_ts, amount_kop, status) AS rn
    FROM stg_acquiring s
)
WHERE rn = 1;

-- Индексы по ключу сопоставления: без них соединение 180k x 180k уходит в квадратичный план.
CREATE INDEX idx_term_clean_rrn ON stg_terminal_clean (rrn);
CREATE INDEX idx_term_clean_ts ON stg_terminal_clean (txn_ts, partner_id);
CREATE INDEX idx_acq_clean_rrn ON stg_acquiring_clean (rrn);
CREATE INDEX idx_acq_clean_ts ON stg_acquiring_clean (txn_ts, partner_id);
CREATE INDEX idx_dup_rrn ON stg_acquiring_duplicates (rrn);

-- Границы периода наблюдения: используются для открытых инцидентов и для знаменателя SLA.
DROP TABLE IF EXISTS dim_period;
CREATE TABLE dim_period AS
SELECT MIN(substr(txn_ts, 1, 10)) AS period_start,
       MAX(substr(txn_ts, 1, 10)) AS period_end,
       CAST(julianday(MAX(substr(txn_ts, 1, 10)))
            - julianday(MIN(substr(txn_ts, 1, 10))) + 1 AS INTEGER) AS period_days
FROM stg_terminal;
