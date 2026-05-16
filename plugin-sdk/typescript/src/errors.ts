/**
 * Hestia plugin SDK error types.
 *
 * Hestia-specific errors are raised by the SDK when the server returns a
 * JSON-RPC error with a `hestia.<code>` namespace. Plugin authors can
 * catch these and react appropriately.
 */

export class HestiaError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly data?: unknown,
  ) {
    super(message);
    this.name = "HestiaError";
  }
}

export class NotConnectedError extends HestiaError {
  constructor() {
    super(
      "hestia.not_connected",
      "Plugin must call connect() before invoking other methods.",
    );
    this.name = "NotConnectedError";
  }
}

export class SessionExpiredError extends HestiaError {
  constructor() {
    super(
      "hestia.session_expired",
      "Soft LCT expired. Call connect() again to renew the session.",
    );
    this.name = "SessionExpiredError";
  }
}

export class PolicyDeniedError extends HestiaError {
  constructor(reason: string, public readonly policyId?: string) {
    super("hestia.policy_denied", `Action denied by policy: ${reason}`, { policyId });
    this.name = "PolicyDeniedError";
  }
}

export class VaultDeniedError extends HestiaError {
  constructor(reason?: string) {
    super(
      "hestia.vault_denied",
      `User declined credential request${reason ? `: ${reason}` : ""}.`,
    );
    this.name = "VaultDeniedError";
  }
}

export class VaultNotFoundError extends HestiaError {
  constructor(name: string) {
    super("hestia.vault_not_found", `Credential '${name}' not found in vault.`, { name });
    this.name = "VaultNotFoundError";
  }
}

export class VaultScopeMismatchError extends HestiaError {
  constructor(name: string, requestedScope: string[]) {
    super(
      "hestia.vault_scope_mismatch",
      `Credential '${name}' is not allowed under scope [${requestedScope.join(", ")}] for this plugin.`,
      { name, requestedScope },
    );
    this.name = "VaultScopeMismatchError";
  }
}

export class ActionNotFoundError extends HestiaError {
  constructor(actionId: string) {
    super("hestia.action_not_found", `Action ${actionId} not found (begin_action required first).`, {
      actionId,
    });
    this.name = "ActionNotFoundError";
  }
}

export class InvalidRoleError extends HestiaError {
  constructor(role: string) {
    super("hestia.invalid_role", `Role '${role}' is not available to plugins.`, { role });
    this.name = "InvalidRoleError";
  }
}

/**
 * Map a Hestia error code (from JSON-RPC error data) to a typed error.
 * Falls back to a generic HestiaError if the code is unknown.
 */
export function mapHestiaError(code: string, message: string, data?: unknown): HestiaError {
  switch (code) {
    case "hestia.not_connected":
      return new NotConnectedError();
    case "hestia.session_expired":
      return new SessionExpiredError();
    case "hestia.policy_denied": {
      const policyId = typeof data === "object" && data && "policyId" in data
        ? (data as { policyId?: string }).policyId
        : undefined;
      return new PolicyDeniedError(message, policyId);
    }
    case "hestia.vault_denied":
      return new VaultDeniedError(message);
    case "hestia.vault_not_found": {
      const name = typeof data === "object" && data && "name" in data
        ? (data as { name?: string }).name ?? "?"
        : "?";
      return new VaultNotFoundError(name);
    }
    case "hestia.vault_scope_mismatch": {
      const name = typeof data === "object" && data && "name" in data
        ? (data as { name?: string }).name ?? "?"
        : "?";
      const scope = typeof data === "object" && data && "requestedScope" in data
        ? (data as { requestedScope?: string[] }).requestedScope ?? []
        : [];
      return new VaultScopeMismatchError(name, scope);
    }
    case "hestia.action_not_found": {
      const actionId = typeof data === "object" && data && "actionId" in data
        ? (data as { actionId?: string }).actionId ?? "?"
        : "?";
      return new ActionNotFoundError(actionId);
    }
    case "hestia.invalid_role": {
      const role = typeof data === "object" && data && "role" in data
        ? (data as { role?: string }).role ?? "?"
        : "?";
      return new InvalidRoleError(role);
    }
    default:
      return new HestiaError(code, message, data);
  }
}
