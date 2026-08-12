import { checkNetwork } from "./config.js";
import { logger } from "./utils/logger.js";
import { cmdFetchMyTasksApi } from "./commands/fetch-my-tasks-api.js";
import { runSync } from "./commands/sync.js";
import { printHelp } from "./commands/utils.js";
import { makeSyncCliCommand } from "./commands/sync-cli.js";
import { Command } from "commander";

const command = process.argv[2];
const args = process.argv.slice(3);

const NEEDS_NETWORK = new Set(["fetch-my-tasks-api", "sync", "sprint-sync"]);

async function main(): Promise<void> {
  if (NEEDS_NETWORK.has(command)) {
    logger.info("Checking network...");
    await checkNetwork();
    logger.success("Network OK");
  }

  switch (command) {
    case "fetch-my-tasks-api":
      await cmdFetchMyTasksApi(args);
      break;
    case "sync":
      await runSync(args[0]);
      break;
    case "webhook":
      await import("./webhook-server.js");
      break;
    case "sprint-sync":
      const program = new Command();
      program.addCommand(makeSyncCliCommand());
      await program.parseAsync(process.argv);
      break;
    default:
      printHelp();
      break;
  }
}

main().catch((err) => {
  logger.error(err.message);
  process.exit(1);
});