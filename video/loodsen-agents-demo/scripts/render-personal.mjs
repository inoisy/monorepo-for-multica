// Renders one personal version of the film per persona in src/data.ts.
// Usage: node scripts/render-personal.mjs [id ...]
import {execFileSync} from 'node:child_process';
import {mkdirSync, writeFileSync} from 'node:fs';

const personas = [
  // Keep in sync with src/data.ts (ids only; props are resolved there).
  'anna',
  'olga',
  'irina',
  'sergey',
];

const wanted = process.argv.slice(2);
const ids = wanted.length ? personas.filter((id) => wanted.includes(id)) : personas;
mkdirSync('out', {recursive: true});

for (const id of ids) {
  writeFileSync('out/.props.json', JSON.stringify({persona: id}));
  console.log(`> rendering ${id}`);
  execFileSync('npx', ['remotion', 'render', 'Personal', `out/loodsen-agents-${id}.mp4`, '--props=out/.props.json'], {stdio: 'inherit'});
}
