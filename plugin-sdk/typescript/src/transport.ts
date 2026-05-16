/**
 * Hestia endpoint discovery.
 *
 * Plugins connect to a user-level Hestia daemon. The SDK auto-discovers
 * where Hestia is running in this order:
 * 1. Explicit `hestiaEndpoint` in client config
 * 2. `HESTIA_ENDPOINT` env var
 * 3. `~/.hestia/endpoint` file (written by the Hestia daemon on startup)
 * 4. `http://127.0.0.1:7711` (default fallback)
 */

import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export const DEFAULT_HESTIA_ENDPOINT = "http://127.0.0.1:7711";

export async function discoverHestiaEndpoint(override?: string): Promise<string> {
  if (override) return override;

  const envEndpoint = process.env.HESTIA_ENDPOINT;
  if (envEndpoint) return envEndpoint;

  try {
    const filePath = join(homedir(), ".hestia", "endpoint");
    const fileEndpoint = (await readFile(filePath, "utf-8")).trim();
    if (fileEndpoint) return fileEndpoint;
  } catch {
    // file doesn't exist or unreadable; fall through to default
  }

  return DEFAULT_HESTIA_ENDPOINT;
}
