// 10_devices.m — справочник устройств.
// Символ «;» в Delimiter и Encoding = 65001 обязательны: файлы выгружены в UTF-8 с BOM.
let
    Источник = Csv.Document(
        File.Contents(DataRoot & "\devices.csv"),
        [Delimiter = ";", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    СЗаголовками = Table.PromoteHeaders(Источник, [PromoteAllScalars = true]),
    Типизировано = Table.TransformColumnTypes(
        СЗаголовками,
        {
            {"device_id", type text},
            {"serial", type text},
            {"vendor", type text},
            {"model", type text},
            {"device_type", type text},
            {"partner_id", type text},
            {"partner_name", type text},
            {"region", type text},
            {"city", type text},
            {"install_date", type date},
            {"status", type text},
            {"sw_version", type text}
        },
        "ru-RU"
    ),
    УбранМусор = Table.SelectRows(Типизировано, each [device_id] <> null and [device_id] <> "")
in
    УбранМусор
