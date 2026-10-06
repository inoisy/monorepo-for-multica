# Layouts

Every slide also accepts `notes` (speaker notes, not rendered). Inline text
supports `**bold**`, `*italic*`, `` `code` ``, `==accent highlight==` and `\n`.

## title — opening (and optionally closing)

Big headline anchored bottom-left, ambient glow. Put the takeaway or the event
in `title`, and audience/date in `meta`.

```json
{ "layout": "title", "eyebrow": "Обзор · Q3 2026", "title": "Платформа агентов: ==итоги квартала==",
  "subtitle": "Что выросло, что сломалось и куда идём дальше", "meta": "Команда платформы · 6 октября 2026" }
```

## statement — one sentence that must land

Use it for the main takeaway (slide 2), a turning point, or the closing ask.
Keep it to 20 words or fewer. `==highlight==` the key phrase.

```json
{ "layout": "statement", "eyebrow": "Главное", "statement": "Агенты закрыли ==41% задач== без участия человека.",
  "support": "Год назад было 6%." }
```

## section — act divider

Use it in decks longer than 10 slides. `number` renders as a pill ("01").

```json
{ "layout": "section", "number": "02", "title": "Что не сработало", "subtitle": "И что мы поменяли" }
```

## bullets — a short argument

Three bullets or fewer render large, in the display face. With 4–5 bullets
the list switches to a numbered layout. Each bullet should be a full, short
claim. If the bullets are numbers, use `stats`. If they are steps in time,
use `timeline`.

```json
{ "layout": "bullets", "eyebrow": "Решения", "title": "Ставка на навыки окупилась",
  "bullets": ["Общая библиотека skills вместо промптов в каждом агенте", "Squads распределяют задачи по специализациям", "Скриншот-проверка в каждом цикле"] }
```

## stats — 2–4 headline numbers

The first stat is colored accent, so lead with the most important. Values
should be short ("120 ч", "−35%", "3×"). Use a real minus sign "−" for
negatives.

```json
{ "layout": "stats", "eyebrow": "Эффект", "title": "Экономия на команду в месяц",
  "stats": [{ "value": "120 ч", "label": "Инженерного времени", "caption": "Медиана по 40 командам" },
            { "value": "−35%", "label": "Время ревью" }, { "value": "3×", "label": "Скорость онбординга" }] }
```

## bento — several facts with a hierarchy

See `bento.md`. Use it for "quarter at a glance", feature overviews, KPI
dashboards, and team/product summaries.

## split — claim plus evidence

Text on one side, a visual on the other: `chart`, `image` (full-bleed panel)
or `stat` (accent panel with one huge number). `side: "left"` puts the visual
on the left. Use either `body` or `bullets`, not both at length.

```json
{ "layout": "split", "eyebrow": "Качество", "title": "Самопроверка снизила возвраты вдвое",
  "body": "Агент смотрит на результат так же, как ревьюер.", "bullets": ["Возвраты: 22% → 9%"],
  "visual": { "kind": "chart", "chart": { "type": "bar", "labels": ["Апр","Май","Июн","Июл","Авг","Сен"],
    "series": [{ "values": [22,20,17,14,11,9] }], "unit": "%", "highlight": 5 } } }
```

## quote — a voice from outside the team

Customer, user, or leader. Keep it to 40 words or fewer, and trim to the
strongest sentence. Put the attribution in `author` and `role`.

```json
{ "layout": "quote", "quote": "Впервые агент стал ==участником команды==.", "author": "Анна Петрова", "role": "тимлид" }
```

## timeline — roadmap, process, history

2–6 steps. Give each step a short `label` (date or phase), a `title`, and an
optional one-line `body`. The first step is filled.

```json
{ "layout": "timeline", "eyebrow": "Дорожная карта", "title": "Что дальше",
  "steps": [{ "label": "Q4 2026", "title": "Слайды и документы", "body": "Агенты собирают деки" },
            { "label": "Q1 2027", "title": "Мультимодальные ревью" }, { "label": "Q2 2027", "title": "Автономные squads" }] }
```

## compare — two options, one recommendation

Exactly two columns. Always set `highlight: true` on the recommended column
(it gets the accent border and check marks). Put the recommendation in the
title.

```json
{ "layout": "compare", "eyebrow": "Решение", "title": "Свой хост выигрывает по данным и цене",
  "columns": [{ "title": "Облако", "items": ["Быстрый старт", "Данные у вендора"] },
              { "title": "Свой хост", "highlight": true, "items": ["Данные остаются у нас", "Фиксированная стоимость"] }] }
```

## image — full-bleed photo or screenshot

Optional `title` and `caption` sit over a bottom gradient. Only use it for
images worth a full slide.

```json
{ "layout": "image", "src": "assets/product.png", "title": "Новый интерфейс", "caption": "Релиз 14 октября" }
```

## Charts (bento `chart` tiles and `split` visuals)

| type | use for | notes |
|---|---|---|
| `bar` | comparing categories or periods | 12 bars or fewer; `highlight` the one the story is about |
| `line` | trend over time | the last value is labeled automatically |
| `area` | trend with emphasis on volume | same as line |
| `donut` | share of a whole | 5 segments or fewer; the center shows the `highlight` (or first) segment's % |
| `progress` | shares or completion per item | `unit: "%"` scales to 100 |

`series` takes up to 3 `{label, values}`. With more than one series the chart
shows a legend. Keep a single series unless the comparison is the point.
