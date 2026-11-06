// 45_duplicates.m — повторные проводки одного и того же RRN в процессинге.
let
    Процессинг = Процессинг_проводки,
    Сгруппировано = Table.Group(
        Процессинг,
        {"rrn"},
        {
            {"rows_cnt", each Table.RowCount(_), Int64.Type},
            {"amount_max_kop", each List.Max([amount_kop]), Int64.Type},
            {"amount_min_kop", each List.Min([amount_kop]), Int64.Type},
            {"first_ts", each List.Min([txn_ts]), type datetime},
            {"last_ts", each List.Max([txn_ts]), type datetime},
            {"device_id", each List.First([device_id]), type text}
        }
    ),
    ТолькоДубли = Table.SelectRows(Сгруппировано, each [rows_cnt] > 1),
    СРазбросом = Table.AddColumn(
        ТолькоДубли, "amount_spread_kop", each [amount_max_kop] - [amount_min_kop], Int64.Type
    )
in
    СРазбросом
