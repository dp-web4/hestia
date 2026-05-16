// Hestia consumer demo — end-to-end through the OpenClaw plugin against the
// real Rust daemon.
//
// Walks through a realistic agent session:
//   1. Spin up the daemon on a sandbox HOME
//   2. Pre-seed credentials in the vault
//   3. Connect the OpenClaw plugin
//   4. Run a sequence of tool calls: Read, vault_get, Bash, Write, Bash failure
//   5. Print the witness chain + final trust state
//
// Run with: node demo/consumer/run.mjs
//
// No globals to clean up — uses a tmp HESTIA_HOME and tears the daemon down
// on exit.

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";

import { createHestiaClient } from "@hestia/plugin-sdk";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "../..");
const HESTIA_BIN = join(REPO_ROOT, "core/target/debug/hestia");

if (!existsSync(HESTIA_BIN)) {
  console.error(`✗ hestia binary not found at ${HESTIA_BIN}`);
  console.error(`  Build first:  cd core && cargo build`);
  process.exit(1);
}

const PORT = 7714;
const ENDPOINT = `http://127.0.0.1:${PORT}/mcp`;
const PASSPHRASE = "demo-pass";

const home = mkdtempSync(join(tmpdir(), "hestia-demo-"));

function h1(text) {
  console.log(`\n\x1b[1;36m━━━ ${text} ━━━\x1b[0m`);
}
function h2(text) {
  console.log(`\n\x1b[1;33m▸ ${text}\x1b[0m`);
}
function step(label, ...rest) {
  console.log(`  \x1b[2m·\x1b[0m ${label}`, ...rest);
}
function ok(label, ...rest) {
  console.log(`  \x1b[32m✓\x1b[0m ${label}`, ...rest);
}
function warn(label, ...rest) {
  console.log(`  \x1b[33m!\x1b[0m ${label}`, ...rest);
}

async function runCli(args, env = {}) {
  return new Promise((resolveP, reject) => {
    const proc = spawn(HESTIA_BIN, args, {
      env: { ...process.env, HESTIA_HOME: home, ...env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.stderr.on("data", (d) => (err += d.toString()));
    proc.on("close", (code) => {
      if (code !== 0) reject(new Error(`hestia ${args.join(" ")} failed (${code}): ${err}`));
      else resolveP(out.trim());
    });
  });
}

async function startDaemon() {
  return new Promise((resolveP, reject) => {
    const proc = spawn(
      HESTIA_BIN,
      ["serve", "--bind", `127.0.0.1:${PORT}`],
      {
        env: { ...process.env, HESTIA_HOME: home, HESTIA_PASSPHRASE: PASSPHRASE, RUST_LOG: "warn" },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let resolved = false;
    proc.stdout.on("data", (d) => {
      const s = d.toString();
      if (!resolved && s.includes("MCP server")) {
        resolved = true;
        resolveP(proc);
      }
    });
    proc.stderr.on("data", (d) => {
      const s = d.toString();
      if (!resolved && s.includes("listening on")) {
        resolved = true;
        resolveP(proc);
      }
    });
    proc.on("error", reject);
    // Fallback: just wait a bit and assume it's up.
    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        resolveP(proc);
      }
    }, 2500);
  });
}

async function runDemo() {
  let daemon;
  let hestia;
  try {
    h1("Hestia consumer demo");
    console.log(`  HOME: ${home}`);
    console.log(`  daemon: ${HESTIA_BIN}`);

    h2("1. Initialize Hestia (vault + identity)");
    await runCli(["init"], { HESTIA_PASSPHRASE: PASSPHRASE });
    ok(`Vault created at ${home}/vault.enc`);

    h2("2. Seed credentials");
    await runCli(
      ["vault", "add", "anthropic_key", "--scope", "infer", "--tag", "llm", "--consumer", "openclaw"],
      { HESTIA_PASSPHRASE: PASSPHRASE, HESTIA_SECRET: "sk-ant-demo-12345" },
    );
    ok("Added anthropic_key (scope=[infer], consumer=[openclaw])");
    await runCli(
      ["vault", "add", "github_pat", "--scope", "git", "--scope", "publish", "--tag", "vcs", "--consumer", "openclaw"],
      { HESTIA_PASSPHRASE: PASSPHRASE, HESTIA_SECRET: "ghp_demo-67890" },
    );
    ok("Added github_pat (scope=[git, publish], consumer=[openclaw])");

    h2("3. Start the Hestia daemon");
    daemon = await startDaemon();
    await sleep(500);
    ok(`Daemon listening on ${ENDPOINT}`);

    h2("4. OpenClaw plugin connects to Hestia");
    hestia = createHestiaClient({
      pluginId: "openclaw",
      pluginVersion: "0.0.1",
      hostAgent: "openclaw",
      hostAgentVersion: "demo",
      hestiaEndpoint: ENDPOINT,
      requestedRole: "citizen",
    });
    const session = await hestia.connect();
    ok(`session_id=${session.sessionId}`);
    ok(`soft_lct=${session.softLct}`);
    ok(`role=${session.assignedRole}`);

    h2("5. Run a realistic agent action sequence");

    // 5a — Read action (low magnitude)
    step("[Read /etc/hostname]  (low magnitude, read-only)");
    let action = await hestia.beginAction({ toolName: "Read", target: "/etc/hostname" });
    let policy = await hestia.queryPolicy(action);
    ok(`policy = ${policy.decision} (${policy.reason})`);
    await hestia.recordOutcome(action, { success: true, magnitude: 0.2 });

    // 5b — vault_get for an allowed credential
    step("[vault_get anthropic_key]  (scoped to infer)");
    const v1 = await hestia.vaultGet("anthropic_key", { scope: ["infer"] });
    ok(`secret retrieved: ${v1.value.slice(0, 8)}...`);

    // 5c — try to retrieve github_pat with the WRONG scope; expect typed error
    step("[vault_get github_pat under infer scope]  (should be DENIED)");
    try {
      await hestia.vaultGet("github_pat", { scope: ["infer"] });
      warn("UNEXPECTED: vault_get succeeded");
    } catch (err) {
      ok(`denied: code=${err.code} (${err.message})`);
    }

    // 5d — Bash (high magnitude)
    step("[Bash 'echo hello']  (high magnitude)");
    action = await hestia.beginAction({ toolName: "Bash", target: "echo" });
    policy = await hestia.queryPolicy(action);
    ok(`policy = ${policy.decision}`);
    await hestia.recordOutcome(action, { success: true, magnitude: 0.8 });

    // 5e — Write action that fails
    step("[Write /tmp/demo.txt]  (mutating, simulated failure)");
    action = await hestia.beginAction({ toolName: "Write", target: "/tmp/demo.txt" });
    await hestia.queryPolicy(action);
    await hestia.recordOutcome(action, {
      success: false,
      magnitude: 0.6,
      error: "permission denied",
    });
    warn("recorded as FAILURE (trust takes a hit)");

    // 5f — Two more successful Read actions
    for (const path of ["/tmp/a", "/tmp/b"]) {
      action = await hestia.beginAction({ toolName: "Read", target: path });
      await hestia.recordOutcome(action, { success: true, magnitude: 0.2 });
    }
    ok("recorded 2 more Read successes");

    h2("6. Final state");

    const history = await hestia.queryHistory({ limit: 50 });
    console.log(`  witness chain: ${history.entries.length} entries`);
    console.log(`  ${"─".repeat(78)}`);
    console.log(`  ${"pos".padEnd(4)} ${"event_type".padEnd(18)} ${"detail".padEnd(40)} ${"hash"}`);
    console.log(`  ${"─".repeat(78)}`);
    for (const e of [...history.entries].reverse()) {
      const detail =
        e.eventType === "outcome"
          ? `${e.eventData.tool_name ?? "?"} → ${e.eventData.success ? "success" : "FAILURE"}`
          : e.eventType === "session_started"
            ? `plugin=${e.eventData.plugin_id} role=${e.eventData.assigned_role}`
            : e.eventType === "vault_set"
              ? `name=${e.eventData.name}`
              : "";
      console.log(
        `  ${String(e.chainPosition).padEnd(4)} ${e.eventType.padEnd(18)} ${detail.padEnd(40)} ${e.hash.slice(0, 12)}...`,
      );
    }

    h2("7. Trust state for the openclaw plugin");
    const trustState = await hestia.getOwnTrustState();
    console.log(`  ${JSON.stringify(trustState, null, 2).replace(/\n/g, "\n  ")}`);

    h2("8. Cross-agent shared context");
    const shared = await hestia.getSharedContext();
    console.log(`  ${JSON.stringify(shared)}`);

    console.log("\n\x1b[1;32m✓ Demo complete\x1b[0m");
    console.log(`  Persistent state at ${home}/`);
    console.log(`  (witness.db is a vanilla sqlite file — open it with any sqlite tool)`);
  } finally {
    try {
      await hestia?.disconnect();
    } catch {}
    if (daemon) {
      daemon.kill("SIGINT");
      await sleep(200);
    }
    if (process.env.KEEP_HOME !== "1") {
      rmSync(home, { recursive: true, force: true });
    } else {
      console.log(`\n  KEEP_HOME=1 — left HOME at ${home}`);
    }
  }
}

runDemo().catch((err) => {
  console.error("\n\x1b[31m✗ Demo failed:\x1b[0m", err);
  process.exit(1);
});
