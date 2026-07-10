// Path A prototype (runnable): hestia vault as Interchange's credential backend.
//
// The seam: today Interchange stores a credential's secret as plaintext in the
// `credential.secret` Postgres column (packages/db/src/schema/credentials.ts) and
// reads it verbatim in resolveCredentialRequirement (packages/db/src/credential-
// resolution.ts). This backend lets that column hold a *reference* instead:
//
//     hestia+vault://<name>
//
// dereferenced to the real secret only at materialization time, from hestia's
// encrypted vault (Argon2id + ChaCha20-Poly1305, SQLCipher at rest). Plaintext
// never lands in Postgres. Non-reference secrets pass through unchanged, so this
// is strictly additive and backward compatible.
//
// This .mjs is the runnable prototype; hestia-vault-backend.ts is the same logic
// typed to slot into packages/db. Node 20+ (no bun needed to demo).

import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileP = promisify(execFile);

export const VAULT_SCHEME = "hestia+vault://";

/** Is this stored secret a hestia vault reference rather than a literal secret? */
export function isVaultRef(secret) {
  return typeof secret === "string" && secret.startsWith(VAULT_SCHEME);
}

/** hestia+vault://openai-prod -> "openai-prod" */
export function vaultRefName(secret) {
  if (!isVaultRef(secret)) throw new Error("not a hestia vault reference");
  return secret.slice(VAULT_SCHEME.length);
}

/** Build a reference for storing in the credential row. */
export function toVaultRef(name) {
  return `${VAULT_SCHEME}${name}`;
}

/**
 * Minimal hestia vault client. The control plane (operator context) holds the
 * passphrase and dereferences at agent-launch time - exactly where Interchange
 * reads the plaintext column today. Secrets live only in memory here.
 */
export function createHestiaVault(opts = {}) {
  const bin = opts.bin ?? join(homedir(), ".local", "bin", "hestia");
  const home = opts.home; // optional --home override (default ~/.hestia)
  const passphrase =
    opts.passphrase ??
    (() => {
      try {
        return readFileSync(join(homedir(), ".hestia", ".passphrase"), "utf8").trim();
      } catch {
        return process.env.HESTIA_PASSPHRASE ?? "";
      }
    })();

  const baseArgs = home ? ["--home", home] : [];
  const env = { ...process.env, HESTIA_PASSPHRASE: passphrase };

  async function run(args, extraEnv) {
    const { stdout } = await execFileP(bin, [...baseArgs, ...args], {
      env: { ...env, ...extraEnv },
      maxBuffer: 4 * 1024 * 1024,
    });
    return stdout;
  }

  return {
    async get(name) {
      // `hestia vault get <name>` prints the value to stdout.
      const out = await run(["vault", "get", name]);
      return out.replace(/\n$/, "");
    },
    async add(name, value, scope = []) {
      // HESTIA_SECRET drives the value non-interactively (cli.rs prompt_secret).
      const args = ["vault", "add", name];
      for (const s of scope) args.push("--scope", s);
      await run(args, { HESTIA_SECRET: value });
    },
    async remove(name) {
      await run(["vault", "remove", name]);
    },
    async list() {
      const out = await run(["vault", "list"]);
      return out.split("\n").map((l) => l.trim()).filter(Boolean);
    },
  };
}

/**
 * The drop-in. Given a resolved credential row (whatever resolveCredentialRequirement
 * returned), return the same row with `.secret` dereferenced if it is a vault ref.
 * This is the single call site Interchange would add where it materializes a secret
 * into HarnessConfig (packages/hub-sessions/src/credential-push.ts).
 */
export async function materializeSecret(row, vault = createHestiaVault()) {
  if (!row || !isVaultRef(row.secret)) return row;
  const secret = await vault.get(vaultRefName(row.secret));
  return { ...row, secret };
}
