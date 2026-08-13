import { fetchMyTasksViaApi } from "../api/task-fetcher-api.js";
import { logger } from "../utils/logger.js";
import { env, initStages } from "../config.js";
import { getArg, printSummary } from "./utils.js";

export async function cmdFetchMyTasksApi(args: string[]): Promise<void> {
  if (!env.webhookUrl) {
    logger.error("B24_WEBHOOK_URL not set in .env — required for API mode");
    process.exit(1);
  }

  await initStages();

  const withContext = !args.includes("--no-context");
  const withSiblings = args.includes("--with-siblings");
  const allStages = args.includes("--all-stages");
  const stageArg = getArg(args, "--stage");
  const tagArg = getArg(args, "--tag");

  let stages: number[] | undefined;
  if (allStages) {
    stages = [];
  } else if (stageArg) {
    const stageIds = stageArg.split(",").map((s) => parseInt(s.trim(), 10));
    if (stageIds.some(isNaN)) {
      logger.error("Invalid --stage values. Use comma-separated numeric IDs.");
      process.exit(1);
    }
    stages = stageIds;
  }

  const results = await fetchMyTasksViaApi({
    withContext,
    withSiblings,
    stages,
    tag: tagArg ?? undefined,
  });

  printSummary(results);
}
