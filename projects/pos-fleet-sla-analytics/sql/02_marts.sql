-- 02_marts.sql — расчёт SLA, доступности, неустоек и плана замены оборудования

-- Пересекающиеся инциденты схлопываются: начало каждого сдвигается до конца предыдущего.
DROP TABLE IF EXISTS fact_incident_effective;
CREATE TABLE fact_incident_effective AS
WITH base AS (
    SELECT i.*,
           MAX(COALESCE(i.closed_at, p.period_end || ' 23:59:59'))
               OVER (PARTITION BY i.device_id ORDER BY i.opened_at
                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_closed_at,
           p.period_start || ' 00:00:00' AS period_start,
           p.period_end || ' 23:59:59'   AS period_end
    FROM fact_incident i
    CROSS JOIN dim_period p
)
SELECT incident_id, device_id, contract_id, severity, channel, error_code, error_text,
       family, sla_hours, opened_at, first_response_at,
       COALESCE(closed_at, period_end)                AS closed_at,
       closed_at IS NULL                              AS is_open,
       MAX(opened_at, COALESCE(prev_closed_at, opened_at)) AS effective_start,
       MIN(COALESCE(closed_at, period_end), period_end)    AS effective_end,
       MAX(0.0, (julianday(MIN(COALESCE(closed_at, period_end), period_end))
                 - julianday(MAX(opened_at, COALESCE(prev_closed_at, opened_at)))) * 24.0)
                                                      AS downtime_hours,
       (julianday(first_response_at) - julianday(opened_at)) * 24.0 AS response_hours,
       (julianday(COALESCE(closed_at, period_end)) - julianday(opened_at)) * 24.0
                                                      AS resolution_hours,
       substr(opened_at, 1, 7)                        AS month
FROM base;

-- Расчёт по каждому инциденту: просрочка реакции и решения, штраф.
DROP TABLE IF EXISTS fact_incident_sla;
CREATE TABLE fact_incident_sla AS
WITH calc AS (
    SELECT e.*,
           c.monthly_fee_kop,
           c.penalty_per_hour_pct,
           MAX(0.0, e.response_hours - e.sla_hours * 0.25) AS response_overdue_h,
           MAX(0.0, e.resolution_hours - e.sla_hours)     AS resolution_overdue_h
    FROM fact_incident_effective e
    JOIN dim_contract c ON c.contract_id = e.contract_id
)
SELECT calc.*,
       response_overdue_h > 0 OR resolution_overdue_h > 0 AS sla_breach,
       CAST(MAX(0.0, resolution_overdue_h + 0.999999) AS INTEGER) AS overdue_full_hours,
       CAST(ROUND(monthly_fee_kop * penalty_per_hour_pct / 100.0
                  * CAST(MAX(0.0, resolution_overdue_h + 0.999999) AS INTEGER)) AS INTEGER)
                                                       AS penalty_kop
FROM calc;

-- 1. Устройства: доступность, MTTR, нарушения, штраф.
DROP TABLE IF EXISTS mart_device;
CREATE TABLE mart_device AS
WITH agg AS (
    SELECT device_id,
           COUNT(*)                                          AS incidents_cnt,
           SUM(CASE WHEN severity = 1 THEN 1 ELSE 0 END)     AS p1_cnt,
           SUM(CASE WHEN is_open THEN 1 ELSE 0 END)          AS open_cnt,
           SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END)       AS sla_breach_cnt,
           ROUND(SUM(downtime_hours), 2)                     AS downtime_hours,
           ROUND(AVG(CASE WHEN is_open THEN NULL ELSE resolution_hours END), 2) AS mttr_hours,
           ROUND(AVG(response_hours), 2)                     AS avg_response_hours,
           SUM(penalty_kop)                                  AS penalty_kop
    FROM fact_incident_sla
    GROUP BY device_id
)
SELECT d.device_id, d.device_type, d.vendor, d.model, d.partner_id, d.partner_name,
       d.contract_id, d.city, d.region, d.status, d.install_date,
       COALESCE(a.incidents_cnt, 0)                          AS incidents_cnt,
       COALESCE(a.p1_cnt, 0)                                 AS p1_cnt,
       COALESCE(a.open_cnt, 0)                               AS open_cnt,
       COALESCE(a.sla_breach_cnt, 0)                         AS sla_breach_cnt,
       COALESCE(a.downtime_hours, 0)                         AS downtime_hours,
       COALESCE(a.mttr_hours, 0)                             AS mttr_hours,
       COALESCE(a.avg_response_hours, 0)                     AS avg_response_hours,
       COALESCE(a.penalty_kop, 0)                            AS penalty_kop,
       ROUND(100.0 * (1 - COALESCE(a.downtime_hours, 0) / (p.period_days * 24.0)), 2)
                                                             AS availability_pct,
       ROUND(100.0 * COALESCE(a.sla_breach_cnt, 0) / NULLIF(a.incidents_cnt, 0), 1)
                                                             AS sla_breach_pct
FROM dim_device d
CROSS JOIN dim_period p
LEFT JOIN agg a ON a.device_id = d.device_id;

-- 2. Партнёры и договоры.
DROP TABLE IF EXISTS mart_contract;
CREATE TABLE mart_contract AS
SELECT c.contract_id, c.partner_name, c.monthly_fee_kop,
       COUNT(DISTINCT d.device_id)                          AS devices_cnt,
       COALESCE(SUM(m.incidents_cnt), 0)                    AS incidents_cnt,
       COALESCE(SUM(m.sla_breach_cnt), 0)                   AS sla_breach_cnt,
       ROUND(100.0 * COALESCE(SUM(m.sla_breach_cnt), 0)
             / NULLIF(SUM(m.incidents_cnt), 0), 1)          AS breach_rate_pct,
       ROUND(AVG(m.availability_pct), 2)                    AS avg_availability_pct,
       ROUND(AVG(NULLIF(m.mttr_hours, 0)), 2)               AS avg_mttr_hours,
       COALESCE(SUM(m.penalty_kop), 0)                       AS raw_penalty_kop,
       CAST(c.monthly_fee_kop * c.penalty_cap_pct / 100.0 AS INTEGER) AS penalty_cap_kop,
       MIN(COALESCE(SUM(m.penalty_kop), 0),
           CAST(c.monthly_fee_kop * c.penalty_cap_pct / 100.0 AS INTEGER)) AS billed_penalty_kop
FROM dim_contract c
LEFT JOIN dim_device d ON d.contract_id = c.contract_id
LEFT JOIN mart_device m ON m.device_id = d.device_id
GROUP BY c.contract_id;

-- 3. Неустойка по месяцам с учётом лимита по договору.
DROP TABLE IF EXISTS mart_penalty_month;
CREATE TABLE mart_penalty_month AS
WITH agg AS (
    SELECT contract_id, month,
           COUNT(*)                                          AS incidents_cnt,
           SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END)        AS breaches_cnt,
           SUM(penalty_kop)                                   AS raw_penalty_kop
    FROM fact_incident_sla
    GROUP BY contract_id, month
)
SELECT a.contract_id, c.partner_name, a.month,
       a.incidents_cnt, a.breaches_cnt, a.raw_penalty_kop,
       CAST(c.monthly_fee_kop * c.penalty_cap_pct / 100.0 AS INTEGER) AS penalty_cap_kop,
       MIN(a.raw_penalty_kop,
           CAST(c.monthly_fee_kop * c.penalty_cap_pct / 100.0 AS INTEGER)) AS billed_penalty_kop,
       a.raw_penalty_kop > CAST(c.monthly_fee_kop * c.penalty_cap_pct / 100.0 AS INTEGER)
                                                             AS cap_reached
FROM agg a
JOIN dim_contract c ON c.contract_id = a.contract_id
ORDER BY a.month, a.raw_penalty_kop DESC;

-- 4. Недельная динамика.
DROP TABLE IF EXISTS mart_weekly;
CREATE TABLE mart_weekly AS
SELECT date(opened_at, 'weekday 1', '-7 days')               AS week_start,
       COUNT(*)                                              AS incidents_cnt,
       SUM(CASE WHEN severity = 1 THEN 1 ELSE 0 END)          AS p1_cnt,
       SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END)            AS sla_breach_cnt,
       ROUND(AVG(response_hours), 2)                          AS avg_response_hours,
       ROUND(AVG(CASE WHEN is_open THEN NULL ELSE resolution_hours END), 2) AS avg_resolution_hours,
       ROUND(SUM(downtime_hours), 1)                          AS downtime_hours
FROM fact_incident_sla
GROUP BY 1
ORDER BY 1;

-- 5. Ошибки: семейство и код.
DROP TABLE IF EXISTS mart_error_family;
CREATE TABLE mart_error_family AS
SELECT family,
       COUNT(*)                                              AS incidents_cnt,
       COUNT(DISTINCT device_id)                             AS devices_cnt,
       ROUND(SUM(downtime_hours), 1)                         AS downtime_hours,
       SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END)            AS sla_breach_cnt,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM fact_incident_sla), 1) AS share_pct,
       SUM(penalty_kop)                                      AS penalty_kop
FROM fact_incident_sla
GROUP BY family
ORDER BY incidents_cnt DESC;

DROP TABLE IF EXISTS mart_error_code;
CREATE TABLE mart_error_code AS
SELECT error_code, MAX(error_text) AS error_text,
       COUNT(*)                                              AS incidents_cnt,
       SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END)            AS sla_breach_cnt,
       ROUND(AVG(resolution_hours), 1)                       AS avg_resolution_hours
FROM fact_incident_sla
GROUP BY error_code
ORDER BY incidents_cnt DESC;

-- 6. Кандидаты на замену: 3+ инцидента P1, доступность ниже 95% или 5+ инцидентов.
DROP TABLE IF EXISTS mart_replacement;
CREATE TABLE mart_replacement AS
SELECT device_id, device_type, vendor, model, partner_name, city, install_date,
       incidents_cnt, p1_cnt, sla_breach_cnt, availability_pct, mttr_hours, penalty_kop,
       CASE
           WHEN availability_pct < 90 OR p1_cnt >= 4 THEN 'ВЫСОКИЙ'
           WHEN availability_pct < 95 OR p1_cnt >= 3 OR incidents_cnt >= 8 THEN 'СРЕДНИЙ'
           ELSE 'НАБЛЮДАТЬ'
       END                                                   AS priority,
       CASE
           WHEN availability_pct < 95 AND incidents_cnt >= 5 THEN 'Хронические отказы, износ'
           WHEN p1_cnt >= 3 THEN 'Повторные критичные инциденты'
           WHEN install_date < '2023-06-01' THEN 'Выработан ресурс'
           ELSE 'Следить за динамикой'
       END                                                   AS reason
FROM mart_device
WHERE status <> 'DECOMMISSIONED'
  AND (p1_cnt >= 3 OR availability_pct < 95 OR incidents_cnt >= 5)
ORDER BY p1_cnt DESC, availability_pct ASC;

-- 7. Каналы обращений.
DROP TABLE IF EXISTS mart_channel;
CREATE TABLE mart_channel AS
SELECT channel,
       COUNT(*)                                              AS incidents_cnt,
       ROUND(AVG(response_hours), 2)                          AS avg_response_hours,
       SUM(CASE WHEN severity <= 2 THEN 1 ELSE 0 END)         AS critical_cnt,
       ROUND(100.0 * SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END) / COUNT(*), 1) AS breach_rate_pct
FROM fact_incident_sla
GROUP BY channel
ORDER BY incidents_cnt DESC;

-- 8. KPI одной строкой.
DROP TABLE IF EXISTS mart_kpi;
CREATE TABLE mart_kpi AS
SELECT (SELECT period_start FROM dim_period)                   AS period_start,
       (SELECT period_end FROM dim_period)                     AS period_end,
       (SELECT period_days FROM dim_period)                    AS period_days,
       (SELECT COUNT(*) FROM dim_device)                       AS devices_cnt,
       (SELECT COUNT(*) FROM dim_device WHERE status = 'ACTIVE') AS active_devices_cnt,
       (SELECT COUNT(*) FROM fact_incident_sla)                AS incidents_cnt,
       (SELECT SUM(CASE WHEN severity = 1 THEN 1 ELSE 0 END) FROM fact_incident_sla) AS p1_cnt,
       (SELECT SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END) FROM fact_incident_sla)   AS sla_breach_cnt,
       (SELECT ROUND(100.0 * SUM(CASE WHEN sla_breach THEN 1 ELSE 0 END) / COUNT(*), 1)
          FROM fact_incident_sla)                              AS breach_rate_pct,
       (SELECT ROUND(AVG(availability_pct), 2) FROM mart_device
          WHERE status <> 'DECOMMISSIONED')                    AS avg_availability_pct,
       (SELECT ROUND(AVG(NULLIF(mttr_hours, 0)), 2) FROM mart_device) AS avg_mttr_hours,
       (SELECT ROUND(AVG(response_hours), 2) FROM fact_incident_sla)  AS avg_response_hours,
       (SELECT SUM(raw_penalty_kop) FROM mart_penalty_month)          AS raw_penalty_kop,
       (SELECT SUM(billed_penalty_kop) FROM mart_penalty_month)       AS billed_penalty_kop,
       (SELECT COUNT(*) FROM mart_replacement WHERE priority = 'ВЫСОКИЙ') AS high_priority_replacements;
