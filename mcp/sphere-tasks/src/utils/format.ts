/* eslint-disable no-useless-escape */
export function stripBBCode(text: string): string {
  if (!text) return "";
  return text
    .replace(/\[USER=\d+\]([^\[]*)\[\/USER\]/gi, "@$1")
    .replace(/\[URL=[^\]]*\]([^\[]*)\[\/URL\]/gi, "$1")
    .replace(/\[DISK FILE ID=[^\]]+\]/gi, "")
    .replace(/\[(?:B|I|U|S|QUOTE|CODE|SPOILER)(?:=[^\]]*)?\]([\s\S]*?)\[\/(?:B|I|U|S|QUOTE|CODE|SPOILER)\]/gi, "$1")
    .replace(/\[(?:SIZE|COLOR|FONT|BGCOLOR)=[^\]]*\]([\s\S]*?)\[\/(?:SIZE|COLOR|FONT|BGCOLOR)\]/gi, "$1")
    .replace(/\[IMG\][^\[]*\[\/IMG\]/gi, "[изображение]")
    .replace(/\[(?:BR|HR|\/?\s*\w+(?:=[^\]]*)?)\]/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function formatSeconds(secs: number): string {
  if (!secs || isNaN(secs)) return "";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h > 0 ? `${h}ч ${m}м` : `${m}м`;
}
