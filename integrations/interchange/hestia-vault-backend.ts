// hestia-vault-backend.ts - conforming TypeScript version of the Path A prototype,
// shaped to slot into Interchange's packages/db tree. This is the handoff artifact;
// hestia-vault.mjs is the same logic in runnable form (see demo.mjs).
//
// Integration point: Interchange stores credential secrets as plaintext in the
// `credential.secret` column (packages/db/src/schema/credentials.ts) and reads
// them verbatim in resolveCredentialRequirement (packages/db/src/credential-
// resolution.ts). CREDENTIALS.md notes encryption-at-rest is deferred as "a
// separate concern to be addressed independently." This backend is that concern:
// the column holds a `hestia+vault://<name>` reference; the real secret lives in
// hestia's encrypted vault (Argon2id + ChaCha20-Poly1305, SQLCipher at rest) and
// is dereferenced only at materialization time, in the control-plane process that
// already assembles HarnessConfig (packages/hub-sessions/src/credential-push.ts).
//
// Strictly additive: literal (legacy plaintext) secrets pass through unchanged.

import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileP = promisify(execFile);

export const VAULT_SCHEME = "hestia+vault://" as const;

/** A credential row as far as this backend cares - only `secret` is read. */
export type SecretBearing = { secret: string };

export function isVaultRef(secret: string): boolean {
  return typeof secret === "string" && secret.startsWith(VAULT_SCHEME);
}

export function vaultRefName(secret: string): string {
  if (!isVaultRef(secret)) throw new Error("not a hestia vault reference");
  return secret.slice(VAULT_SCHEME.length);
}

export function toVaultRef(name: string): string {
  return `${VAULT_SCHEME}${name}`;
}

export type HestiaVaultOptions = {
  /** Path to the hestia binary. Default: ~/.local/bin/hestia */
  bin?: string;
  /** Override hestia home (maps to --home). Default: ~/.hestia */
  home?: string;
  /** Vault passphrase. Default: ~/.hestia/.passphrase, else $HESTIA_PASSPHRASE */
  passphrase?: string;
};

export interface HestiaVault {
  get(name: string): Promise<string>;
  add(name: string, value: string, scope?: string[]): Promise<void>;
  remove(name: string): Promise<void>;
  list(): Promise<string[]>;
}

export function createHestiaVault(opts: HestiaVaultOptions = {}): HestiaVault {
  const bin = opts.bin ?? join(homedir(), ".local", "bin", "hestia");
  const home = opts.home;
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
  const env: NodeJS.ProcessEnv = { ...process.env, HESTIA_PASSPHRASE: passphrase };

  async function run(args: string[], extraEnv?: NodeJS.ProcessEnv): Promise<string> {
    const { stdout } = await execFileP(bin, [...baseArgs, ...args], {
      env: { ...env, ...extraEnv },
      maxBuffer: 4 * 1024 * 1024,
    });
    return stdout;
  }

  return {
    async get(name) {
      return (await run(["vault", "get", name])).replace(/\n$/, "");
    },
    async add(name, value, scope = []) {
      const args = ["vault", "add", name];
      for (const s of scope) args.push("--scope", s);
      await run(args, { HESTIA_SECRET: value });
    },
    async remove(name) {
      await run(["vault", "remove", name]);
    },
    async list() {
      return (await run(["vault", "list"])).split("\n").map((l) => l.trim()).filter(Boolean);
    },
  };
}

/**
 * The single drop-in call. Wrap the result of resolveCredentialRequirement (or
 * apply just before pushing a secret into HarnessConfig): a vault-ref secret is
 * dereferenced from hestia; a literal secret is returned unchanged.
 */
export async function materializeSecret<T extends SecretBearing>(
  row: T | null,
  vault: HestiaVault = createHestiaVault(),
): Promise<T | null> {
  if (!row || !isVaultRef(row.secret)) return row;
  const secret = await vault.get(vaultRefName(row.secret));
  return { ...row, secret };
}
