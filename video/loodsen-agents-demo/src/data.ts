// Everything the film says about a viewer comes from here. The numbers are
// demo values: replace them with real ones from Sphere before showing.
export type Persona = {
  id: string;
  name: string;
  dept: string;
  hoursSaved: number; // hours of manual work returned per month
  docs: number; // documents handled by agents per month
  monthly: number[]; // manual hours per month, May..October
};

export type FilmProps = Persona & {
  version: number;
  versions: number;
  names: string[];
};

export const personas: Persona[] = [
  {id: 'anna', name: 'Анна', dept: 'Бухгалтерия', hoursSaved: 37, docs: 412, monthly: [62, 58, 55, 31, 18, 9]},
  {id: 'olga', name: 'Ольга', dept: 'Административный отдел', hoursSaved: 29, docs: 356, monthly: [48, 51, 44, 27, 15, 8]},
  {id: 'irina', name: 'Ирина', dept: 'Отдел кадров', hoursSaved: 24, docs: 198, monthly: [40, 38, 36, 22, 13, 7]},
  {id: 'sergey', name: 'Сергей', dept: 'Офис-менеджмент', hoursSaved: 31, docs: 287, monthly: [52, 49, 47, 30, 17, 10]},
];

export const propsFor = (p: Persona): FilmProps => ({
  ...p,
  version: personas.indexOf(p) + 1,
  versions: personas.length,
  names: personas.map((x) => x.name),
});

// Shown in the "editor" reveal at the end. Edit to match the real run.
export const agentLog = [
  'сценарий написан: 5 сцен, 90 секунд',
  'данные из Сферы загружены: 48 документов',
  'фирменный стиль Лоции применён',
  '2 700 кадров отрисовано',
  `${personas.length} персональные версии готовы`,
];
export const agentStats = 'монтажёров: 0';
