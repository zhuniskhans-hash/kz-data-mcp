# kz-data-mcp

**An MCP server giving any AI agent access to Kazakhstan reference data: official National Bank exchange rates, and ИИН/БИН validation.**

[Русская версия ниже](#kz-data-mcp--ru)

Zero dependencies, standard library only. The Model Context Protocol is implemented directly against the specification rather than through an SDK — roughly 150 lines, and the wire format stays visible.

```bash
git clone https://github.com/zhuniskhans-hash/kz-data-mcp.git
cd kz-data-mcp
python3 -m unittest discover -s tests      # 24 tests, no network needed
python3 -m kz_data_mcp                     # speaks MCP on stdin/stdout
```

Python 3.10+.

---

## Tools

### `kz_exchange_rate`

Official National Bank of Kazakhstan rate against the tenge.

```json
{ "currency": "USD" }
{ "currency": "CNY", "date": "2026-09-01" }
{ }                                          // every published currency
```

**The reason this needs a wrapper.** The Bank quotes some currencies per 10 or 100 units, not per unit. The Armenian dram is published as `12.55` with `quant: 10` — one dram is 1.255 ₸. Read `description` alone and you are off by a factor of ten:

```json
{
  "code": "AMD", "quote": 12.55, "quant": 10,
  "per_unit": 1.255,
  "change": -0.1, "direction": "DOWN", "date": "08.09.2026"
}
```

`per_unit` is always the normalised figure. The raw quote is kept alongside it so nothing is hidden.

Rates publish on business days. A weekend or holiday returns an explicit "nothing published for that date" rather than silently substituting a nearby day.

### `kz_validate_id`

Validates a 12-digit ИИН (individual) or БИН (legal entity) and decodes what it can:

```json
{
  "value": "900101300126", "valid": true, "kind": "iin",
  "birth_date": "1990-01-01", "sex": "male",
  "reason": "checksum valid; well-formed, existence in the state registry not checked"
}
```

---

## What the check digit actually guarantees

Both identifiers use a weighted sum mod 11 over the first 11 digits, weights `1..11`. If that yields 10, the number is re-scored with a second sequence, `3,4,5,6,7,8,9,10,11,1,2`. If that also yields 10, no valid check digit exists and the number is never issued.

**It is a typo guard, not proof of authenticity — and it has two structural blind spots:**

1. **The 11th digit is unprotected.** Its weight is 11, and `11 ≡ 0 (mod 11)`, so it contributes nothing to the sum. Any change to that digit passes. The second sequence has the same blind spot on the 9th digit.
2. **The fallback leaks.** A corruption that pushes the first sum to exactly 10 gets judged by the second weight sequence, which can coincidentally reproduce the original check digit.

Measured across every single-digit corruption of a valid number, about **9% survive**. `tests/test_identifiers.py` asserts that each surviving case is explained by one of those two causes, so a genuine regression cannot hide behind "well, checksums are imperfect".

This is why the tool's `reason` field always says the registry was not checked. Only the tax authority can confirm a number exists.

БИН structure is deliberately **not** decoded. Its digits do encode registration data, but the meaning could not be confirmed against a source, and a plausible-looking guess about a company's type is worse than no answer.

---

## Protocol notes

Implemented from the [MCP specification](https://modelcontextprotocol.io). Three details that are easy to get wrong:

**Version negotiation is an echo, not a constant.** The server replies with the client's requested version when it speaks it, and its own latest otherwise — the spec puts the burden on the client to disconnect if it can't continue. Supported: `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`.

**Notifications get no reply.** A message without an `id` — `notifications/initialized` and friends — must not be answered. Answering one is a protocol violation, and some clients hang on the unexpected response.

**Two error channels that are not interchangeable:**

| Situation | Channel |
|---|---|
| Unknown method, malformed request, unknown tool | JSON-RPC `error` |
| A tool that ran and failed — bad currency code, unreachable endpoint | Successful response with `isError: true` |

The spec is explicit about the second row: a tool failure returned as a protocol error is invisible to the model, which then cannot correct itself. The tests assert both paths.

---

## Connecting it

Claude Code:

```bash
claude mcp add kz-data -- python3 -m kz_data_mcp
```

Or in a client's config file:

```json
{
  "mcpServers": {
    "kz-data": {
      "command": "python3",
      "args": ["-m", "kz_data_mcp"],
      "cwd": "/path/to/kz-data-mcp"
    }
  }
}
```

Verify it by hand — the server is just line-delimited JSON on stdio:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kz_exchange_rate","arguments":{"currency":"USD"}}}' \
  | python3 -m kz_data_mcp
```

## Layout

```
kz_data_mcp/
  server.py       MCP over JSON-RPC on stdio
  nbrk.py         National Bank rate client
  identifiers.py  ИИН / БИН validation
tests/
  test_protocol.py     handshake, dispatch, error channels, robustness
  test_identifiers.py  check digit, decoding, the known blind spots
```

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with the National Bank of Kazakhstan. Uses its public XML endpoints.

---
---

# kz-data-mcp — RU

**MCP-сервер, дающий любому AI-агенту доступ к казахстанским справочным данным: официальные курсы Нацбанка и проверка ИИН/БИН.**

Без единой зависимости, только стандартная библиотека. Протокол MCP реализован напрямую по спецификации, а не через SDK — это около 150 строк, зато формат обмена остаётся на виду.

```bash
git clone https://github.com/zhuniskhans-hash/kz-data-mcp.git
cd kz-data-mcp
python3 -m unittest discover -s tests      # 24 теста, сеть не нужна
python3 -m kz_data_mcp                     # говорит по MCP через stdin/stdout
```

Нужен Python 3.10+.

## Инструменты

### `kz_exchange_rate`

Официальный курс Нацбанка РК к тенге.

```json
{ "currency": "USD" }
{ "currency": "CNY", "date": "2026-09-01" }
{ }                                          // все опубликованные валюты
```

**Зачем это вообще оборачивать.** Нацбанк публикует часть валют за 10 или 100 единиц, а не за одну. Армянский драм идёт как `12.55` при `quant: 10` — то есть один драм стоит 1,255 ₸. Если читать поле `description` напрямую, ошибка будет ровно в десять раз:

```json
{
  "code": "AMD", "quote": 12.55, "quant": 10,
  "per_unit": 1.255,
  "change": -0.1, "direction": "DOWN", "date": "08.09.2026"
}
```

`per_unit` — всегда приведённое значение за единицу. Исходная котировка остаётся рядом, чтобы ничего не пряталось.

Курсы публикуются по рабочим дням. На выходной или праздник сервер честно отвечает «на эту дату публикации не было», а не подставляет молча соседний день.

### `kz_validate_id`

Проверяет 12-значный ИИН (физлицо) или БИН (юрлицо) и разбирает то, что поддаётся разбору:

```json
{
  "value": "900101300126", "valid": true, "kind": "iin",
  "birth_date": "1990-01-01", "sex": "male",
  "reason": "checksum valid; well-formed, existence in the state registry not checked"
}
```

## Что контрольная сумма на самом деле гарантирует

Оба идентификатора используют взвешенную сумму первых 11 цифр по модулю 11, веса `1..11`. Если результат равен 10, номер пересчитывается по второй серии весов: `3,4,5,6,7,8,9,10,11,1,2`. Если и она даёт 10 — валидной контрольной цифры не существует, такой номер не выдаётся.

**Это защита от опечатки, а не доказательство подлинности — и у неё две структурные дыры:**

1. **Одиннадцатая цифра не защищена вообще.** Её вес равен 11, а `11 ≡ 0 (mod 11)`, поэтому она не вносит в сумму ничего. Любое её изменение проходит проверку. У второй серии такая же слепая зона на девятой цифре.
2. **Течёт запасной вариант.** Искажение, которое сдвигает первую сумму ровно к 10, начинает оцениваться по второй серии весов — а она может случайно дать ту же контрольную цифру.

Если перебрать все одиночные искажения валидного номера, проверку проходят примерно **9 %**. Файл `tests/test_identifiers.py` требует, чтобы каждый такой случай объяснялся одной из этих двух причин, — тогда настоящая регрессия не спрячется за фразой «ну, контрольные суммы несовершенны».

Именно поэтому в поле `reason` всегда сказано, что реестр не проверялся. Подтвердить существование номера может только налоговая.

Структуру БИН я намеренно **не разбираю**. Его цифры действительно кодируют регистрационные данные, но подтвердить их значение по источнику не удалось, а правдоподобная догадка о типе компании хуже, чем честное отсутствие ответа.

## Про протокол

Реализовано по [спецификации MCP](https://modelcontextprotocol.io). Три места, где легко ошибиться:

**Версия протокола — это эхо, а не константа.** Сервер отвечает той версией, которую запросил клиент, если умеет её, и своей последней в противном случае: по спецификации решение отключаться принимает клиент. Поддерживаются `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`.

**На уведомления не отвечают.** Сообщение без `id` — `notifications/initialized` и подобные — отвечать нельзя. Ответ на него это нарушение протокола, и часть клиентов на неожиданном ответе зависает.

**Два канала ошибок, и они не взаимозаменяемы:**

| Ситуация | Канал |
|---|---|
| Неизвестный метод, битый запрос, неизвестный инструмент | JSON-RPC `error` |
| Инструмент отработал и упал — неверный код валюты, недоступный источник | Успешный ответ с `isError: true` |

Спецификация про вторую строку говорит прямо: сбой инструмента, отданный как протокольная ошибка, модель не увидит и не сможет исправиться. Оба пути покрыты тестами.

## Как подключить

В Claude Code:

```bash
claude mcp add kz-data -- python3 -m kz_data_mcp
```

Или в конфиге клиента:

```json
{
  "mcpServers": {
    "kz-data": {
      "command": "python3",
      "args": ["-m", "kz_data_mcp"],
      "cwd": "/path/to/kz-data-mcp"
    }
  }
}
```

Проверить руками — сервер это просто построчный JSON на stdio:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kz_exchange_rate","arguments":{"currency":"USD"}}}' \
  | python3 -m kz_data_mcp
```

## Лицензия

MIT — см. [LICENSE](LICENSE).

Проект не связан с Национальным Банком РК. Используются его публичные XML-эндпоинты.
