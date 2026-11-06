-- 04_control_totals.sql
-- Контрольные суммы: сверка итогов «в разрезе партнёр × день».
-- Даже если поштучная сверка по RRN не сходится, итоги по дню должны совпадать
-- с точностью до расхождений из recon_exceptions — это проверка полноты выгрузки.

DROP TABLE IF EXISTS control_totals;
CREATE TABLE control_totals AS
WITH t AS (
    SELECT partner_id,
           substr(txn_ts, 1, 10) AS txn_date,
           COUNT(*)              AS terminal_cnt,
           SUM(amount_kop)       AS terminal_amount_kop
    FROM stg_terminal_clean
    GROUP BY partner_id, substr(txn_ts, 1, 10)
),
a AS (
    SELECT partner_id,
           substr(txn_ts, 1, 10) AS txn_date,
           COUNT(*)              AS acquiring_cnt,
           SUM(amount_kop)       AS acquiring_amount_kop
    FROM stg_acquiring_clean
    GROUP BY partner_id, substr(txn_ts, 1, 10)
)
SELECT COALESCE(t.partner_id, a.partner_id)             AS partner_id,
       COALESCE(t.txn_date, a.txn_date)                 AS txn_date,
       COALESCE(t.terminal_cnt, 0)                      AS terminal_cnt,
       COALESCE(a.acquiring_cnt, 0)                     AS acquiring_cnt,
       COALESCE(a.acquiring_cnt, 0) - COALESCE(t.terminal_cnt, 0) AS cnt_diff,
       COALESCE(t.terminal_amount_kop, 0)               AS terminal_amount_kop,
       COALESCE(a.acquiring_amount_kop, 0)              AS acquiring_amount_kop,
       COALESCE(a.acquiring_amount_kop, 0) - COALESCE(t.terminal_amount_kop, 0)
                                                        AS amount_diff_kop
FROM t
FULL OUTER JOIN a ON a.partner_id = t.partner_id AND a.txn_date = t.txn_date
ORDER BY partner_id, txn_date;
