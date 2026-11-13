import { Link } from "react-router";
import { useDashboard } from "../hooks/useDashboard";
import { blocksRoutes } from "../lib/compat";

export type FirstRunState = "incompatible" | "ready" | "sign-in" | "offline" | "checking";

/** A failure to read is never evidence that there are no agents or pending decisions. */
export function firstRunState(input: {
  online: boolean;
  signedIn: boolean;
  hasSnapshot: boolean;
  incompatible: boolean;
  error: string | null;
}): FirstRunState {
  if (input.incompatible) return "incompatible";
  if (input.hasSnapshot) return "ready";
  if (!input.signedIn && input.online) return "sign-in";
  if (!input.online && input.error) return "offline";
  return "checking";
}

/**
 * A first-use route over existing, real daemon and app capabilities.
 * Never grants access, registers agents, or joins communities implicitly.
 */
export function Start() {
  const { data, online, signedIn, error, handshake, refresh } = useDashboard(5000);
  const state = firstRunState({
    online, signedIn, hasSnapshot: data !== null,
    incompatible: blocksRoutes(handshake),
    error,
  });

  return (
    <div className="page" data-first-run={state}>
      <header className="page-header">
        <h1>Get started with Hestia</h1>
      </header>
      <p>See which agents are governed, decide what they may do, and inspect the record of what happened. Hestia keeps the governing rules on your machine.</p>
      <section className="section" aria-live="polite">
        <h2>Your connection</h2>
        {state === "ready" && <p>Connected and signed in. Your local governance record is available.</p>}
        {state === "sign-in" && <p>Hestia is reachable, but you need to sign in using the sidebar before viewing your agents or decisions. No private data has been loaded.</p>}
        {state === "offline" && <p>The daemon could not be reached. Open Dashboard to check the configured daemon URL or connect to an existing installation. This does not mean your agents are governed.</p>}
        {state === "incompatible" && <p>The daemon is reachable but incompatible with this app. Update the app and daemon as a compatible pair before using governance controls. {handshake?.message}</p>}
        {state === "checking" && <p>Checking your Hestia daemon. No governance status has been established yet.</p>}
        {error && state !== "ready" && <p className="error-banner">{error}</p>}
        <button type="button" onClick={() => refresh()}>Check again</button>
      </section>
      <section className="section">
        <h2>Three things you can do</h2>
        <ol>
          <li><strong>Check your agents.</strong> <Link to="/agents">Open Agents</Link> to see what is installed, what is actually governed, and why anything is not governed. An empty list without a successful inventory is not a clean bill of health.</li>
          <li><strong>Make a decision.</strong> <Link to="/decide">Open Decide</Link> to review requests requiring your authority. Approving an action permits it under the applicable law; it does not prove that the action succeeded.</li>
          <li><strong>Inspect the evidence.</strong> <Link to="/chain">Open Activity</Link> to see witnessed actions and recorded outcomes. Missing outcome evidence is not evidence of success.</li>
        </ol>
      </section>
      <section className="section">
        <h2>Communities and identity</h2>
        <p><Link to="/hubs">Open Hubs</Link> for the currently supported connection controls. A public community website should be viewable without installing Hestia; browser-first joining is being built and is not claimed available here.</p>
        <p>Hestia currently provides cooperative, tamper-evident A1 governance. It is not an adversary-proof sandbox. Advanced controls remain accessible in the sidebar.</p>
      </section>
      <p><Link to="/">Go to the operator dashboard</Link></p>
    </div>
  );
}
