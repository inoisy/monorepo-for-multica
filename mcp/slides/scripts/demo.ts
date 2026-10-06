// Builds a sample deck covering every layout, runs the render check, and
// writes previews + exports. Usage:
//   pnpm demo [theme] [outDir]
// SLIDES_CHROMIUM_PATH points at a local Chromium if Playwright's own isn't installed.
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { DeckStore } from '../src/store.js';
import { lintDeck } from '../src/lint.js';
import { checkRender, closeBrowser, configureBrowser, screenshots } from '../src/browser.js';
import { exportDeck } from '../src/export.js';
import type { Deck } from '../src/schema.js';

const theme = (process.argv[2] ?? 'graphite') as Deck['theme'];
const out = path.resolve(process.argv[3] ?? './data/demo');
const proxy = process.env.HTTPS_PROXY;
if (proxy) configureBrowser({ proxy: { server: proxy } }, { ignoreHTTPSErrors: true });

const store = new DeckStore(path.join(out, 'decks'));

const art = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1200"><defs>
<radialGradient id="a" cx="30%" cy="30%" r="70%"><stop offset="0" stop-color="#8C7CFF"/><stop offset="1" stop-color="#0A0F1F"/></radialGradient>
<radialGradient id="b" cx="80%" cy="80%" r="50%"><stop offset="0" stop-color="#3DDCC8" stop-opacity=".9"/><stop offset="1" stop-color="#3DDCC8" stop-opacity="0"/></radialGradient></defs>
<rect width="1600" height="1200" fill="url(#a)"/><rect width="1600" height="1200" fill="url(#b)"/>
<g fill="none" stroke="#fff" stroke-opacity=".18">${Array.from({ length: 14 }, (_, i) => `<circle cx="1100" cy="400" r="${60 + i * 55}"/>`).join('')}</g></svg>`;

const slides: Deck['slides'] = [
  { layout: 'title', eyebrow: 'Обзор · Q3 2026', title: 'Платформа агентов: ==итоги квартала==', subtitle: 'Что выросло, что сломалось и куда идём дальше', meta: 'Команда платформы · 6 октября 2026' },
  { layout: 'statement', eyebrow: 'Главное', statement: 'Агенты закрыли ==41% задач== без участия человека.', support: 'Год назад было 6%. Дальше — качество, а не объём.' },
  {
    layout: 'bento', eyebrow: 'Q3 в цифрах', title: 'Рост по всем ключевым метрикам',
    grid: { cols: 4, rows: 3 },
    tiles: [
      { kind: 'stat', x: 0, y: 0, w: 2, h: 2, accent: 'accent', value: '+38%', label: 'Активные команды', caption: '1 240 → 1 712 за квартал' },
      { kind: 'chart', x: 2, y: 0, w: 2, h: 2, title: 'Задач в неделю, тыс.', chart: { type: 'area', labels: ['Июл', 'Авг', 'Сен', 'Окт'], series: [{ values: [12, 15, 19, 26] }], unit: 'k' } },
      { kind: 'stat', x: 0, y: 2, w: 1, h: 1, value: '4.7', label: 'Оценка агентов' },
      { kind: 'stat', x: 1, y: 2, w: 1, h: 1, accent: 'muted', value: '11 мин', label: 'Медиана задачи' },
      { kind: 'text', x: 2, y: 2, w: 2, h: 1, eyebrow: 'Новое', title: 'Skills и squads в проде', body: 'Каждый агент берёт навыки из общей библиотеки.' },
    ],
  },
  { layout: 'section', number: '01', title: 'Что сработало', subtitle: 'Три решения, которые дали основной рост' },
  { layout: 'bullets', eyebrow: 'Решения', title: 'Ставка на навыки окупилась', bullets: ['Общая библиотека skills вместо промптов в каждом агенте', 'Squads: лидер распределяет задачи по специализациям', 'Скриншот-проверка результата в каждом цикле'] },
  {
    layout: 'split', eyebrow: 'Качество', title: 'Самопроверка снизила возвраты вдвое',
    body: 'Агент смотрит на результат так же, как ревьюер, и исправляет до сдачи.',
    bullets: ['Возвраты: 22% → 9%', 'Время ревью: −35%'],
    visual: { kind: 'chart', chart: { type: 'bar', labels: ['Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен'], series: [{ values: [22, 20, 17, 14, 11, 9] }], unit: '%', highlight: 5 } },
  },
  { layout: 'stats', eyebrow: 'Эффект', title: 'Экономия на команду в месяц', stats: [{ value: '120 ч', label: 'Инженерного времени', caption: 'Медиана по 40 командам' }, { value: '−35%', label: 'Время ревью' }, { value: '3×', label: 'Скорость онбординга' }] },
  { layout: 'quote', quote: 'Впервые агент стал ==участником команды==, а не инструментом, который надо уговаривать.', author: 'Анна Петрова', role: 'тимлид, платформа' },
  { layout: 'timeline', eyebrow: 'Дорожная карта', title: 'Что дальше', steps: [{ label: 'Q4 2026', title: 'Слайды и документы', body: 'Агенты собирают деки по задаче' }, { label: 'Q1 2027', title: 'Мультимодальные ревью', body: 'Проверка UI по скриншотам' }, { label: 'Q2 2027', title: 'Автономные squads', body: 'Планирование спринта агентами' }, { label: 'Q3 2027', title: 'Маркетплейс skills' }] },
  { layout: 'compare', eyebrow: 'Решение', title: 'Self-hosted против облака', columns: [{ title: 'Облако', items: ['Быстрый старт', 'Данные у вендора', 'Оплата за место'] }, { title: 'Свой хост', highlight: true, items: ['Данные остаются у нас', 'Свои модели и MCP', 'Фиксированная стоимость', 'Своя дизайн-система слайдов'] }] },
  {
    layout: 'bento', title: 'Использование по командам',
    grid: { cols: 3, rows: 2 },
    tiles: [
      { kind: 'image', x: 0, y: 0, w: 1, h: 2, src: 'assets/art.svg', caption: 'Платформа' },
      { kind: 'chart', x: 1, y: 0, w: 2, h: 1, title: 'Доля задач по типу', chart: { type: 'progress', labels: ['Код', 'Ревью', 'Документы'], series: [{ values: [64, 22, 14] }], unit: '%', highlight: 0 } },
      { kind: 'chart', x: 1, y: 1, w: 1, h: 1, title: 'Модели', chart: { type: 'donut', labels: ['Claude', 'Codex', 'Другие'], series: [{ values: [71, 21, 8] }], unit: '%' } },
      { kind: 'quote', x: 2, y: 1, w: 1, h: 1, accent: 'accent2', quote: 'Слайды теперь делает агент.', author: 'Отдел продаж' },
    ],
  },
  { layout: 'image', src: 'assets/art.svg', title: 'Спасибо', caption: 'Вопросы — в канал #platform' },
];

const { id } = await store.create({ title: 'Q3 review', theme, footer: 'Платформа агентов · Q3 2026', slides: [] }, `demo-${theme}`);
await store.addAsset(id, 'art.svg', Buffer.from(art));
const deck = await store.save(id, { title: 'Q3 review', theme, footer: 'Платформа агентов · Q3 2026', slides });

console.log('lint:', lintDeck(deck));
const check = await checkRender(store.dir(id));
console.log('fonts loaded:', check.fontsLoaded);
for (const s of check.slides) if (s.overflow.length || s.shrunk.length || s.brokenImages.length) console.log('render:', JSON.stringify(s));

const shotsDir = path.join(out, `png-${theme}`);
await mkdir(shotsDir, { recursive: true });
for (const s of await screenshots(store.dir(id), undefined, 0.5)) {
  await writeFile(path.join(shotsDir, `${String(s.slide).padStart(2, '0')}.png`), s.png);
}
if (process.env.DEMO_EXPORT) {
  console.log(await exportDeck(store.dir(id), deck, 'pdf'));
  console.log(await exportDeck(store.dir(id), deck, 'pptx'));
}
console.log('deck dir:', store.dir(id), '\npreviews:', shotsDir);
await closeBrowser();
