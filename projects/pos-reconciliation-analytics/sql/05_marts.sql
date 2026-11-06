-- 05_marts.sql
-- Витрины для отчётности: доступность парка, SLA инцидентов, операционные показатели.

-- 1. Доступность и SLA по каждому устройству.
-- Пересекающиеся инциденты схлопываются в непересекающиеся интервалы: для каждого
-- инцидента начало сдвигается до конца предыдущего простоя по этому устройству.
DROP TABLE IF EXISTS fact_incident_effective;
CREATE TABLE fact_incident_effective AS
WITH base AS (
    SELECT i.incident_id,
           i.device_id,
           i.opened_at,
           i.closed_at,
           i.severity,
           i.error_code,
           i.source_system,
           MAX(COALESCE(i.closed_at, (SELECT period_end || ' 23:59:59' FROM dim_period)))
               OVER (PARTITION BY i.device_id ORDER BY i.opened_at
                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_closed_at
    FROM fact_incident i
),
bounded AS (
    SELECT b.*,
           (SELECT period_start || ' 00:00:00' FROM dim_period) AS period_start,
           (SELECT period_end || ' 23:59:59' FROM dim_period)   AS period_end
    FROM base b
)
SELECT incident_id,
       device_id,
       opened_at,
       COALESCE(closed_at, period_end)                                  AS closed_at,
       closed_at IS NULL                                                AS is_open,
       severity,
       error_code,
       source_system,
       MAX(opened_at, COALESCE(prev_closed_at, opened_at))              AS effective_start,
       MIN(COALESCE(closed_at, period_end), period_end)                 AS effective_end,
       MAX(0.0, (julianday(MIN(COALESCE(closed_at, period_end), period_end))
                 - julianday(MAX(opened_at, COALESCE(prev_closed_at, opened_at)))) * 24.0)
                                                                        AS downtime_hours,
       (julianday(COALESCE(closed_at, period_end)) - julianday(opened_at)) * 24.0
                                                                        AS total_open_hours,
       CASE severity WHEN 1 THEN 4 WHEN 2 THEN 8 WHEN 3 THEN 24 ELSE 72 END AS sla_hours
FROM bounded;

DROP TABLE IF EXISTS mart_device_sla;
CREATE TABLE mart_device_sla AS
WITH period AS (SELECT period_days * 24.0 AS period_hours FROM dim_period),
agg AS (
    SELECT e.device_id,
           COUNT(*)                                                       AS incidents_cnt,
           SUM(CASE WHEN e.severity = 1 THEN 1 ELSE 0 END)                AS p1_cnt,
           SUM(CASE WHEN e.is_open THEN 1 ELSE 0 END)                     AS open_cnt,
           ROUND(SUM(e.downtime_hours), 2)                                AS downtime_hours,
           ROUND(AVG(CASE WHEN e.is_open THEN NULL ELSE e.total_open_hours END), 2) AS mttr_hours,
           SUM(CASE WHEN e.total_open_hours > e.sla_hours THEN 1 ELSE 0 END) AS sla_breach_cnt
    FROM fact_incident_effective e
    GROUP BY e.device_id
)
SELECT d.device_id,
       d.device_type,
       d.vendor,
       d.model,
       d.partner_id,
       d.partner_name,
       d.region,
       d.city,
       d.status,
       COALESCE(a.incidents_cnt, 0)                                       AS incidents_cnt,
       COALESCE(a.p1_cnt, 0)                                              AS p1_cnt,
       COALESCE(a.open_cnt, 0)                                            AS open_cnt,
       COALESCE(a.downtime_hours, 0)                                      AS downtime_hours,
       COALESCE(a.mttr_hours, 0)                                          AS mttr_hours,
       COALESCE(a.sla_breach_cnt, 0)                                      AS sla_breach_cnt,
       ROUND(100.0 * (1 - COALESCE(a.downtime_hours, 0) / p.period_hours), 2) AS availability_pct,
       ROUND(100.0 * COALESCE(a.sla_breach_cnt, 0) / NULLIF(a.incidents_cnt, 0), 2) AS sla_breach_pct
FROM dim_device d
CROSS JOIN period p
LEFT JOIN agg a ON a.device_id = d.device_id;

-- 2. Сводка по парку: тип устройства и партнёр.
DROP TABLE IF EXISTS mart_fleet_summary;
CREATE TABLE mart_fleet_summary AS
SELECT device_type,
       partner_name,
       COUNT(*)                                                AS devices_cnt,
       ROUND(AVG(availability_pct), 2)                         AS avg_availability_pct,
       MIN(availability_pct)                                   AS worst_availability_pct,
       SUM(incidents_cnt)                                      AS incidents_cnt,
       SUM(sla_breach_cnt)                                     AS sla_breach_cnt,
       ROUND(SUM(downtime_hours), 1)                           AS downtime_hours,
       ROUND(AVG(NULLIF(mttr_hours, 0)), 2)                    AS avg_mttr_hours,
       SUM(CASE WHEN availability_pct < 97 THEN 1 ELSE 0 END)  AS devices_below_97
FROM mart_device_sla
WHERE status <> 'DECOMMISSIONED'
GROUP BY device_type, partner_name
ORDER BY avg_availability_pct;

-- 3. Операционные показатели партнёра по дням (объединяет сверку, инциденты и потоки).
DROP TABLE IF EXISTS mart_partner_daily;
CREATE TABLE mart_partner_daily AS
WITH tx AS (
    SELECT partner_id,
           substr(txn_ts, 1, 10) AS txn_date,
           COUNT(*)                                             AS txns_cnt,
           SUM(amount_kop)                                      AS amount_kop,
           SUM(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) AS approved_cnt,
           SUM(CASE WHEN status = 'DECLINED' THEN 1 ELSE 0 END) AS declined_cnt,
           SUM(CASE WHEN status = 'REVERSED' THEN 1 ELSE 0 END) AS reversed_cnt
    FROM stg_terminal_clean
    GROUP BY partner_id, substr(txn_ts, 1, 10)
),
exc AS (
    SELECT partner_id, txn_date,
           COUNT(*)                  AS exceptions_cnt,
           SUM(amount_at_risk_kop)   AS amount_at_risk_kop
    FROM recon_exceptions
    GROUP BY partner_id, txn_date
)
SELECT t.partner_id,
       t.txn_date,
       t.txns_cnt,
       t.amount_kop,
       t.approved_cnt,
       t.declined_cnt,
       t.reversed_cnt,
       ROUND(100.0 * t.approved_cnt / t.txns_cnt, 2)        AS approval_rate_pct,
       ROUND(100.0 * t.declined_cnt / t.txns_cnt, 2)        AS decline_rate_pct,
       COALESCE(e.exceptions_cnt, 0)                        AS exceptions_cnt,
       COALESCE(e.amount_at_risk_kop, 0)                    AS amount_at_risk_kop,
       ROUND(100.0 * COALESCE(e.exceptions_cnt, 0) / t.txns_cnt, 3) AS exception_rate_pct
FROM tx t
LEFT JOIN exc e ON e.partner_id = t.partner_id AND e.txn_date = t.txn_date;

-- 4. Ошибки и простои по кодам.
DROP TABLE IF EXISTS mart_error_codes;
CREATE TABLE mart_error_codes AS
SELECT e.error_code,
       MAX(i.error_text)                                  AS error_text,
       COUNT(*)                                           AS incidents_cnt,
       COUNT(DISTINCT e.device_id)                        AS devices_cnt,
       ROUND(SUM(e.downtime_hours), 1)                    AS downtime_hours,
       ROUND(AVG(e.total_open_hours), 2)                  AS avg_open_hours,
       SUM(CASE WHEN e.total_open_hours > e.sla_hours THEN 1 ELSE 0 END) AS sla_breach_cnt,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM fact_incident_effective), 2) AS share_pct
FROM fact_incident_effective e
LEFT JOIN fact_incident i ON i.incident_id = e.incident_id
GROUP BY e.error_code
ORDER BY incidents_cnt DESC;

-- 5. Одна таблица KPI для титульного блока дашборда.
DROP TABLE IF EXISTS mart_kpi;
CREATE TABLE mart_kpi AS
SELECT (SELECT period_start FROM dim_period)                            AS period_start,
       (SELECT period_end FROM dim_period)                              AS period_end,
       (SELECT period_days FROM dim_period)                             AS period_days,
       (SELECT COUNT(*) FROM dim_device)                                AS devices_cnt,
       (SELECT COUNT(*) FROM dim_device WHERE status = 'ACTIVE')        AS active_devices_cnt,
       (SELECT COUNT(*) FROM stg_terminal_clean)                        AS txns_cnt,
       (SELECT SUM(amount_kop) FROM stg_terminal_clean)                 AS amount_kop,
       (SELECT ROUND(100.0 * SUM(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) / COUNT(*), 2)
          FROM stg_terminal_clean)                                      AS approval_rate_pct,
       (SELECT COUNT(*) FROM fact_incident)                             AS incidents_cnt,
       (SELECT ROUND(AVG(availability_pct), 2) FROM mart_device_sla WHERE status <> 'DECOMMISSIONED')
                                                                        AS avg_availability_pct,
       (SELECT ROUND(AVG(NULLIF(mttr_hours, 0)), 2) FROM mart_device_sla) AS avg_mttr_hours,
       (SELECT COUNT(*) FROM recon_exceptions)                          AS exceptions_cnt,
       (SELECT SUM(amount_at_risk_kop) FROM recon_exceptions)           AS amount_at_risk_kop,
       (SELECT ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM stg_terminal_clean), 3)
          FROM recon_exceptions)                                        AS exception_rate_pct;
