import { createConsola } from "consola";

const DEBUG = process.env.DEBUG === "true" || process.env.SPHERE_DEBUG === "true";

// Custom reporter that writes to stderr (keeps stdout clean for JSON-RPC MCP protocol)
const stderrReporter = {
  log(logObj: { args: unknown[]; type: string }, _ctx: unknown): void {
    const msg = logObj.args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ");
     
    console.error(msg);
  },
};

export const logger = createConsola({
  level: DEBUG ? 5 : 3,
  formatOptions: { date: false, compact: true },
  reporters: [stderrReporter],
});