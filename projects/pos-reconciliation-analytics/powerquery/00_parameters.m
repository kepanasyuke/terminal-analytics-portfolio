// 00_parameters.m — общие параметры для всех запросов.
// В Power BI: "Главная" → "Управление параметрами" → "Создать параметр"
// Имя: DataRoot, тип: Text, текущее значение: <путь к папке проекта>\data\raw
// Здесь параметр описан как запрос, чтобы файл можно было вставить целиком.
let
    DataRoot = "C:\Projects\pos-reconciliation-analytics\data\raw"
in
    DataRoot
