// 40_reconciliation.m — сверка двух источников по RRN внутри Power Query.
// Тот же алгоритм, что в sql/03_reconciliation.sql, но без БД: полезно, когда
// заказчик отдаёт только выгрузки, а доступа к хранилищу нет.
let
    Терминал = Table.Buffer(Терминал_журнал),
    Процессинг = Table.Buffer(Процессинг_проводки),

    Слито = Table.NestedJoin(
        Терминал, {"rrn"},
        Процессинг, {"rrn"},
        "процессинг", JoinKind.FullOuter
    ),
    Развёрнуто = Table.ExpandTableColumn(
        Слито, "процессинг",
        {"rrn", "txn_ts", "amount_kop", "status", "device_id"},
        {"acq_rrn", "acq_ts", "acq_amount_kop", "acq_status", "acq_device_id"}
    ),

    Классифицировано = Table.AddColumn(
        Развёрнуто, "exception_type",
        each
            if [acq_rrn] = null then "MISSING_IN_ACQUIRING"
            else if [rrn] = null then "MISSING_IN_TERMINAL"
            else if [amount_kop] <> [acq_amount_kop] then "AMOUNT_MISMATCH"
            else if [status] <> [acq_status] then "STATUS_MISMATCH"
            else if Number.Abs(Duration.TotalMinutes([acq_ts] - [txn_ts])) > 10 then "TIMESTAMP_DRIFT"
            else "MATCH",
        type text
    ),

    КлючОперации = Table.AddColumn(
        Классифицировано, "rrn_key", each if [rrn] = null then [acq_rrn] else [rrn], type text
    ),
    Устройство = Table.AddColumn(
        КлючОперации, "device_id_key",
        each if [device_id] = null then [acq_device_id] else [device_id], type text
    ),
    РазницаСумм = Table.AddColumn(
        Устройство, "amount_diff_kop",
        each (if [acq_amount_kop] = null then 0 else [acq_amount_kop])
             - (if [amount_kop] = null then 0 else [amount_kop]),
        Int64.Type
    ),

    ТолькоРасхождения = Table.SelectRows(РазницаСумм, each [exception_type] <> "MATCH"),
    Отсортировано = Table.Sort(ТолькоРасхождения, {{"exception_type", Order.Ascending}, {"device_id_key", Order.Ascending}})
in
    Отсортировано
