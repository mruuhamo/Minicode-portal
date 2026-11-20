import { InteractionStatus } from "@azure/msal-browser";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import type { ReactNode } from "react";

/** Renders children once a user is signed in; otherwise a sign-in prompt (redirect flow). */
export function AuthGate({ scopes, children }: { scopes: string[]; children: ReactNode }) {
  const { instance, inProgress } = useMsal();
  const signedIn = useIsAuthenticated();

  if (signedIn) return <>{children}</>;
  if (inProgress !== InteractionStatus.None) {
    return (
      <p className="mcl-status" role="status">
        Signing in...
      </p>
    );
  }
  return (
    <div className="mcl-signin">
      <h1>Minicodes</h1>
      <p>Sign in with your work account to browse and search minicode recordings.</p>
      <button type="button" className="mcl-button mcl-button--primary" onClick={() => instance.loginRedirect({ scopes })}>
        Sign in
      </button>
    </div>
  );
}
