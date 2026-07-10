// Path A demo: round-trip a secret through hestia's encrypted vault into an
// Interchange-shaped credential resolution - proving plaintext never touches
// the "Postgres" row.
//
//   node demo.mjs
//
// Requires a running/initialized hestia on this machine (vault + passphrase).

import assert from "node:assert";
import {
  createHestiaVault,
  materializeSecret,
  toVaultRef,
  isVaultRef,
} from "./hestia-vault.mjs";

const NAME = "intx-path-a-demo";
const REAL_SECRET = "sk-live-DEMO-ONLY-9f2c1a7b-not-a-real-key";

const vault = createHestiaVault();

function log(step, msg) {
  console.log(`  [${step}] ${msg}`);
}

async function main() {
  console.log("\nPath A - hestia vault as Interchange credential backend\n");

  // 1. Operator seals the real secret in hestia's encrypted vault.
  await vault.remove(NAME).catch(() => {}); // idempotent
  await vault.add(NAME, REAL_SECRET, ["infer"]);
  log("1", `sealed "${NAME}" in hestia vault (Argon2id + ChaCha20-Poly1305)`);

  // 2. What Interchange stores in Postgres: a REFERENCE, not the secret.
  //    This is the row resolveCredentialRequirement() would return today, except
  //    `.secret` holds a hestia+vault:// ref instead of the plaintext key.
  const credentialRow = {
    id: "cred_demo",
    tenantId: "tnt_demo",
    providerId: "prov_openai",
    name: "openai-prod",
    type: "api_key",
    secret: toVaultRef(NAME), // <-- what lives in the DB column
    status: "active",
  };
  log("2", `Postgres credential.secret = ${JSON.stringify(credentialRow.secret)}`);
  assert.ok(isVaultRef(credentialRow.secret), "row should hold a vault ref");
  assert.ok(
    !credentialRow.secret.includes(REAL_SECRET),
    "plaintext must NOT be in the DB row",
  );
  log("2", "asserted: the real secret is NOT present anywhere in the DB row");

  // 3. At agent-launch materialization, the hub dereferences the ref.
  const materialized = await materializeSecret(credentialRow, vault);
  log("3", `materialized secret for the harness = "${materialized.secret}"`);

  // 4. Prove the round-trip is faithful and the row itself never mutated.
  assert.strictEqual(materialized.secret, REAL_SECRET, "resolved secret mismatch");
  assert.strictEqual(
    credentialRow.secret,
    toVaultRef(NAME),
    "original row must remain a reference",
  );
  log("4", "asserted: harness receives the true secret; DB still holds only the ref");

  // 5. Backward compatibility: a literal (legacy plaintext) secret passes through.
  const legacyRow = { id: "cred_legacy", secret: "literal-plaintext-key" };
  const legacyOut = await materializeSecret(legacyRow, vault);
  assert.strictEqual(legacyOut.secret, "literal-plaintext-key");
  log("5", "asserted: legacy plaintext secrets pass through unchanged (additive)");

  // cleanup
  await vault.remove(NAME).catch(() => {});
  console.log("\n  ✓ PASS - secret sealed at rest, referenced in DB, released only at launch.\n");
}

main().catch((err) => {
  console.error("\n  ✗ FAIL:", err.message, "\n");
  vault.remove(NAME).catch(() => {});
  process.exit(1);
});
