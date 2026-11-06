// 30_acquiring_settlement.m — проводки со стороны процессинга/эквайринга.
let
    Источник = Csv.Document(
        File.Contents(DataRoot & "\acquiring_settlement.csv"),
        [Delimiter = ";", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    СЗаголовками = Table.PromoteHeaders(Источник, [PromoteAllScalars = true]),
    Типизировано = Table.TransformColumnTypes(
        СЗаголовками,
        {
            {"rrn", type text},
            {"device_id", type text},
            {"device_type", type text},
            {"partner_id", type text},
            {"merchant_id", type text},
            {"txn_ts", type datetime},
            {"op_type", type text},
            {"amount_kop", Int64.Type},
            {"currency", type text},
            {"status", type text},
            {"auth_code", type text},
            {"error_code", type text},
            {"settlement_date", type date}
        },
        "ru-RU"
    ),
    ССуммой = Table.AddColumn(Типизировано, "amount_rub", each [amount_kop] / 100, type number),
    // Дедупликация без потери информации: количество повторов остаётся в отдельном запросе 45_duplicates.m
    Дедуплицировано = Table.Distinct(ССуммой)
in
    Дедуплицировано
