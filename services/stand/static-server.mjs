// Статика для стендов.
//   node static-server.mjs <каталог> <порт>                  — один сайт (стенды вида static)
//   node static-server.mjs --hosts <каталог> <порт> <домен>   — артефакты: art-<имя>.<домен> → <каталог>/<имя>/site
// Без зависимостей, только чтение. Неизвестный путь без расширения → index.html (SPA).
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";

const multi = process.argv[2] === "--hosts";
const args = multi ? process.argv.slice(3) : process.argv.slice(2);
const base = resolve(args[0] ?? "/site");
const port = Number(args[1] ?? 3000);
const domain = (args[2] ?? "").toLowerCase();
const HOST_RE = /^(art-[a-z0-9][a-z0-9-]{0,62})$/;

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".jsx": "text/plain; charset=utf-8", ".tsx": "text/plain; charset=utf-8", ".ts": "text/plain; charset=utf-8",
  ".md": "text/plain; charset=utf-8", ".mmd": "text/plain; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
  ".ico": "image/x-icon", ".woff": "font/woff", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8",
  ".csv": "text/csv; charset=utf-8", ".map": "application/json", ".wasm": "application/wasm", ".pdf": "application/pdf",
};

async function file(p) {
  try {
    const s = await stat(p);
    if (s.isDirectory()) return file(join(p, "index.html"));
    return s.isFile() ? { path: p, size: s.size } : null;
  } catch {
    return null;
  }
}

function siteRoot(req) {
  if (!multi) return base;
  const host = String(req.headers.host ?? "").split(":")[0].toLowerCase();
  if (!host.endsWith("." + domain)) return null;
  const m = HOST_RE.exec(host.slice(0, -(domain.length + 1)));
  return m ? join(base, m[1], "site") : null;
}

createServer(async (req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405).end();
    return;
  }
  const root = siteRoot(req);
  if (!root) {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("not found");
    return;
  }
  let path;
  try {
    path = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
  } catch {
    res.writeHead(400).end();
    return;
  }
  const target = resolve(root, "." + normalize(path));
  if (target !== root && !target.startsWith(root + sep)) {
    res.writeHead(403).end();
    return;
  }
  let f = await file(target);
  if (!f && !extname(path)) f = await file(join(root, "index.html"));
  if (!f) {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("not found");
    return;
  }
  const html = f.path.endsWith(".html");
  res.writeHead(200, {
    "content-type": TYPES[extname(f.path).toLowerCase()] ?? "application/octet-stream",
    "content-length": f.size,
    "cache-control": html || multi ? "no-cache" : "public, max-age=300",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
  });
  if (req.method === "HEAD") res.end();
  else createReadStream(f.path).pipe(res);
}).listen(port, multi ? "127.0.0.1" : "0.0.0.0", () =>
  console.log(multi ? `artifacts: ${base} on 127.0.0.1:${port} for *.${domain}` : `static: ${base} on :${port}`));
