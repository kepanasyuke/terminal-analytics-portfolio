# Словарь данных

Все файлы в `data/raw/` и `data/processed/` — CSV с разделителем `;`, кодировка UTF-8 с BOM,
десятичный разделитель не используется: деньги хранятся целыми числами в копейках.

## Сырые выгрузки (`data/raw/`)

### devices.csv — справочник устройств

| Поле | Тип | Описание |
| --- | --- | --- |
| `device_id` | text | Идентификатор устройства в парке, `PO-/KI-/AT-` + номер |
| `serial` | text | Серийный номер; при передаче заказчику маскируется |
| `vendor`, `model` | text | Производитель и модель |
| `device_type` | text | `POS`, `KIOSK` (киоск самообслуживания), `ATM` |
| `partner_id`, `partner_name` | text | Партнёр — владелец парка |
| `region`, `city` | text | География |
| `install_date` | date | Дата установки |
| `status` | text | `ACTIVE`, `SERVICE`, `DECOMMISSIONED` |
| `sw_version` | text | Версия ПО терминала |

### merchants.csv — торговые точки

| Поле | Тип | Описание |
| --- | --- | --- |
| `merchant_id` | text | Идентификатор точки (`MID…`) |
| `partner_id`, `partner_name` | text | Партнёр |
| `segment` | text | `retail`, `telecom`, `transport`, `bank`, `fuel` |
| `merchant_name` | text | Название точки |

### incidents.csv — инциденты по устройствам

| Поле | Тип | Описание |
| --- | --- | --- |
| `incident_id` | text | `INC-…` |
| `device_id` | text | Устройство |
| `opened_at` | datetime | Начало инцидента |
| `closed_at` | datetime | Закрытие; пусто — инцидент ещё открыт |
| `severity` | int | 1 — критичный … 4 — незначительный |
| `error_code`, `error_text` | text | Код и краткое описание |
| `symptom` | text | Описание симптома |
| `source_system` | text | `TMS` или `SERVICE_DESK` |

### terminal_journal.csv — операции со стороны терминальной сети

| Поле | Тип | Описание |
| --- | --- | --- |
| `rrn` | text | Уникальный идентификатор операции, ключ сверки |
| `device_id`, `device_type` | text | Устройство |
| `partner_id`, `merchant_id` | text | Партнёр и точка |
| `txn_ts` | datetime | Время операции по терминалу |
| `op_type` | text | `PURCHASE`, `PAYMENT`, `CASHOUT`, `REFUND` |
| `amount_kop` | int | Сумма в копейках; для возвратов отрицательная |
| `currency` | text | `RUB` |
| `status` | text | `APPROVED`, `DECLINED`, `REVERSED` |
| `auth_code` | text | Код авторизации |
| `error_code` | text | Код ошибки для отказов и реверсов |

### acquiring_settlement.csv — проводки процессинга

Те же поля плюс `settlement_date` — дата расчёта. Отличия от журнала терминалов
(пропуски, суммы, статусы, время, дубликаты) — это и есть предмет сверки.

## Витрины (`data/processed/`)

| Таблица | Гранулярность | Ключевые поля |
| --- | --- | --- |
| `mart_kpi` | одна строка за период | `devices_cnt`, `txns_cnt`, `amount_kop`, `approval_rate_pct`, `avg_availability_pct`, `avg_mttr_hours`, `exceptions_cnt`, `amount_at_risk_kop`, `exception_rate_pct` |
| `mart_recon_summary` | класс расхождения | `exception_type`, `severity`, `exceptions_cnt`, `amount_at_risk_kop`, `devices_cnt` |
| `mart_partner_daily` | партнёр × день | `txns_cnt`, `amount_kop`, `approval_rate_pct`, `exceptions_cnt`, `amount_at_risk_kop` |
| `mart_device_sla` | устройство | `availability_pct`, `incidents_cnt`, `downtime_hours`, `mttr_hours`, `sla_breach_cnt` |
| `mart_fleet_summary` | тип устройства × партнёр | `devices_cnt`, `avg_availability_pct`, `devices_below_97` |
| `mart_error_codes` | код ошибки | `incidents_cnt`, `downtime_hours`, `sla_breach_cnt`, `share_pct` |
| `control_totals` | партнёр × день | `terminal_cnt`, `acquiring_cnt`, `cnt_diff`, `terminal_amount_kop`, `acquiring_amount_kop`, `amount_diff_kop` |

## Построчные исключения (`reports/recon_exceptions.csv`)

| Поле | Описание |
| --- | --- |
| `exception_type` | `MISSING_IN_ACQUIRING`, `MISSING_IN_TERMINAL`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `TIMESTAMP_DRIFT`, `DUPLICATE_IN_ACQUIRING` |
| `severity` | 1 — деньги, 2 — статус, 3 — время, 4 — прочее |
| `rrn` | Ключ операции |
| `device_id`, `partner_id`, `merchant_id`, `device_type`, `op_type` | Атрибуты операции |
| `txn_date` | Дата операции (по той стороне, где она есть) |
| `terminal_ts`, `acquiring_ts` | Время в каждой системе |
| `ts_delta_min` | Разница во времени, минуты |
| `terminal_amount_kop`, `acquiring_amount_kop` | Суммы в каждой системе |
| `amount_diff_kop` | Процессинг минус терминал |
| `amount_at_risk_kop` | Сумма под риском по правилам класса |
| `terminal_status`, `acquiring_status` | Статусы в каждой системе |

## Служебный файл

`data/raw/_injected_defects.json` — эталон заложенных расхождений: сколько и какие RRN
испорчены. Используется только тестами; в отчётные выгрузки не попадает.
