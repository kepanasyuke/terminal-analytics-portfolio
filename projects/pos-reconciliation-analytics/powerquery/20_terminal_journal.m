// 20_terminal_journal.m — журнал операций со стороны терминальной сети (TMS).
// Суммы в источнике в копейках; рубли считаются отдельным столбцом, чтобы не терять точность.
let
    Источник = Csv.Document(
        File.Contents(DataRoot & "\terminal_journal.csv"),
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
            {"error_code", type text}
        },
        "ru-RU"
    ),
    СДатой = Table.AddColumn(Типизировано, "txn_date", each Date.From([txn_ts]), type date),
    ССуммой = Table.AddColumn(СДатой, "amount_rub", each [amount_kop] / 100, type number),
    БезОшибок = Table.ReplaceErrorValues(
        ССуммой, {{"amount_rub", null}, {"error_code", null}}
    )
in
    БезОшибок
