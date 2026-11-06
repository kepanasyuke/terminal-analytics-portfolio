-- 03_reconciliation.sql
-- Сверка двух систем: журнал терминальной сети (TMS) против процессинга/эквайринга.
-- Ключ сопоставления — RRN (уникальный идентификатор операции).
--
-- Классы расхождений и приоритет (первое совпадение выигрывает, чтобы одна операция
-- не попадала в отчёт дважды):
--   1 DUPLICATE_IN_ACQUIRING — RRN встречается в процессинге более одного раза
--   2 MISSING_IN_ACQUIRING   — операция есть на терминале, но не дошла до процессинга
--   3 MISSING_IN_TERMINAL    — операция есть в процессинге, но нет в журнале терминала
--   4 AMOUNT_MISMATCH        — расходится сумма
--   5 STATUS_MISMATCH        — расходится статус (APPROVED/DECLINED/REVERSED)
--   6 TIMESTAMP_DRIFT        — время операции расходится больше чем на 10 минут
--
-- Полное внешнее соединение реализовано через LEFT JOIN + правую анти-выборку:
-- так запрос переносится между SQLite, PostgreSQL и MS SQL без FULL OUTER JOIN.

DROP TABLE IF EXISTS recon_joined;
CREATE TABLE recon_joined AS
SELECT COALESCE(t.rrn, a.rrn)             AS rrn,
       COALESCE(t.device_id, a.device_id) AS device_id,
       COALESCE(t.partner_id, a.partner_id) AS partner_id,
       COALESCE(t.merchant_id, a.merchant_id) AS merchant_id,
       COALESCE(t.device_type, a.device_type) AS device_type,
       COALESCE(t.op_type, a.op_type)     AS op_type,
       substr(COALESCE(t.txn_ts, a.txn_ts), 1, 10) AS txn_date,
       t.txn_ts                           AS terminal_ts,
       a.txn_ts                           AS acquiring_ts,
       t.amount_kop                       AS terminal_amount_kop,
       a.amount_kop                       AS acquiring_amount_kop,
       t.status                           AS terminal_status,
       a.status                           AS acquiring_status,
       t.rrn                              AS terminal_rrn,
       a.rrn                              AS acquiring_rrn
FROM stg_terminal_clean t
LEFT JOIN stg_acquiring_clean a ON a.rrn = t.rrn
UNION ALL
SELECT a.rrn, a.device_id, a.partner_id, a.merchant_id, a.device_type, a.op_type,
       substr(a.txn_ts, 1, 10), NULL, a.txn_ts, NULL, a.amount_kop, NULL, a.status, NULL, a.rrn
FROM stg_acquiring_clean a
WHERE NOT EXISTS (SELECT 1 FROM stg_terminal_clean t WHERE t.rrn = a.rrn);

DROP TABLE IF EXISTS recon_exceptions;
CREATE TABLE recon_exceptions AS
WITH classified AS (
    SELECT j.*,
           CASE
               WHEN j.terminal_rrn IS NULL THEN 'MISSING_IN_TERMINAL'
               WHEN j.acquiring_rrn IS NULL THEN 'MISSING_IN_ACQUIRING'
               WHEN j.terminal_amount_kop <> j.acquiring_amount_kop THEN 'AMOUNT_MISMATCH'
               WHEN j.terminal_status <> j.acquiring_status THEN 'STATUS_MISMATCH'
               WHEN ABS((julianday(j.acquiring_ts) - julianday(j.terminal_ts)) * 1440) > 10
                   THEN 'TIMESTAMP_DRIFT'
               ELSE 'MATCH'
           END AS exception_type,
           CAST(ROUND((julianday(j.acquiring_ts) - julianday(j.terminal_ts)) * 1440) AS INTEGER)
               AS ts_delta_min
    FROM recon_joined j
    WHERE j.rrn NOT IN (SELECT rrn FROM stg_acquiring_duplicates)
)
SELECT c.exception_type,
       CASE c.exception_type
           WHEN 'MISSING_IN_ACQUIRING' THEN 1
           WHEN 'MISSING_IN_TERMINAL'  THEN 1
           WHEN 'AMOUNT_MISMATCH'      THEN 1
           WHEN 'STATUS_MISMATCH'      THEN 2
           WHEN 'TIMESTAMP_DRIFT'      THEN 3
           ELSE 4
       END                                              AS severity,
       c.rrn,
       c.device_id,
       c.partner_id,
       c.merchant_id,
       c.device_type,
       c.op_type,
       c.txn_date,
       c.terminal_ts,
       c.acquiring_ts,
       c.ts_delta_min,
       c.terminal_amount_kop,
       c.acquiring_amount_kop,
       COALESCE(c.acquiring_amount_kop, 0) - COALESCE(c.terminal_amount_kop, 0)
                                                        AS amount_diff_kop,
       CASE c.exception_type
           WHEN 'MISSING_IN_ACQUIRING' THEN ABS(COALESCE(c.terminal_amount_kop, 0))
           WHEN 'MISSING_IN_TERMINAL'  THEN ABS(COALESCE(c.acquiring_amount_kop, 0))
           WHEN 'AMOUNT_MISMATCH'      THEN ABS(c.acquiring_amount_kop - c.terminal_amount_kop)
           WHEN 'STATUS_MISMATCH'      THEN ABS(COALESCE(c.terminal_amount_kop, 0))
           ELSE 0
       END                                              AS amount_at_risk_kop,
       c.terminal_status,
       c.acquiring_status
FROM classified c
WHERE c.exception_type <> 'MATCH'
UNION ALL
SELECT 'DUPLICATE_IN_ACQUIRING', 1, d.rrn, d.device_id, d.partner_id, NULL, NULL, NULL,
       substr(d.first_ts, 1, 10), NULL, d.first_ts, NULL, NULL, NULL,
       d.amount_spread_kop, ABS(COALESCE(d.amount_spread_kop, 0)), NULL, NULL
FROM stg_acquiring_duplicates d;

CREATE INDEX idx_recon_type ON recon_exceptions (exception_type);
CREATE INDEX idx_recon_date ON recon_exceptions (txn_date);

-- Итог по классам расхождений: с этим срезом работают в Power BI и в Excel.
DROP TABLE IF EXISTS mart_recon_summary;
CREATE TABLE mart_recon_summary AS
SELECT exception_type,
       severity,
       COUNT(*)                          AS exceptions_cnt,
       SUM(amount_at_risk_kop)           AS amount_at_risk_kop,
       COUNT(DISTINCT device_id)         AS devices_cnt,
       COUNT(DISTINCT partner_id)        AS partners_cnt,
       MIN(txn_date)                     AS first_date,
       MAX(txn_date)                     AS last_date
FROM recon_exceptions
GROUP BY exception_type, severity
ORDER BY severity, exceptions_cnt DESC;
