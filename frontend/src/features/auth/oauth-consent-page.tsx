import { useEffect, useRef, useState } from "react";
import type { OAuthAuthorizationDetails } from "@supabase/supabase-js";
import { ArrowUpRight, LoaderCircle, ShieldCheck } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { BrandLockup } from "../../components/brand/brand-lockup";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { ErrorMessage, LoadingState } from "../../components/ui/feedback";
import { redirectToOAuthClient } from "../../lib/oauth-redirect";
import { supabase } from "../../lib/supabase";

type Decision = "approve" | "deny";

function describeScope(scope: string): string {
  switch (scope) {
    case "openid":
      return "Confirm your FinPilot identity";
    case "email":
      return "Share your email address";
    case "profile":
      return "Share your basic profile";
    case "phone":
      return "Share your phone number";
    default:
      return scope;
  }
}

export function OAuthConsentPage() {
  const [searchParams] = useSearchParams();
  const authorizationId = searchParams.get("authorization_id");
  const [details, setDetails] = useState<OAuthAuthorizationDetails | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pendingDecision, setPendingDecision] = useState<Decision | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const decisionPendingRef = useRef(false);

  useEffect(() => {
    let active = true;

    async function loadAuthorization() {
      if (!authorizationId) {
        setErrorMessage("This authorization link is missing its request ID. Start again from your AI app.");
        setIsLoading(false);
        return;
      }

      try {
        const { data, error } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId);
        if (!active) return;

        if (error || !data) {
          setErrorMessage("This authorization request is invalid or has expired. Start again from your AI app.");
          setIsLoading(false);
          return;
        }

        if ("authorization_id" in data) {
          setDetails(data);
          setIsLoading(false);
          return;
        }

        // Supabase returns this URL only when the request is already authorized.
        redirectToOAuthClient(data.redirect_url);
      } catch {
        if (!active) return;
        setErrorMessage("FinPilot could not load this authorization request. Try again from your AI app.");
        setIsLoading(false);
      }
    }

    void loadAuthorization();
    return () => {
      active = false;
    };
  }, [authorizationId]);

  async function decide(decision: Decision) {
    if (!authorizationId || decisionPendingRef.current) return;
    decisionPendingRef.current = true;
    setPendingDecision(decision);
    setErrorMessage("");

    try {
      const result = decision === "approve"
        ? await supabase.auth.oauth.approveAuthorization(authorizationId, { skipBrowserRedirect: true })
        : await supabase.auth.oauth.denyAuthorization(authorizationId, { skipBrowserRedirect: true });

      if (result.error || !result.data?.redirect_url) {
        setErrorMessage("FinPilot could not complete that choice. The request may have expired; start again from your AI app.");
        decisionPendingRef.current = false;
        setPendingDecision(null);
        return;
      }

      redirectToOAuthClient(result.data.redirect_url);
    } catch {
      setErrorMessage("FinPilot could not complete that choice. Check your connection and try again.");
      decisionPendingRef.current = false;
      setPendingDecision(null);
    }
  }

  if (isLoading) return <LoadingState label="Checking the authorization request" />;

  const requestedScopes = details?.scope.trim().split(/\s+/).filter(Boolean) ?? [];

  return (
    <main className="min-h-screen bg-background px-5 py-8 sm:px-8 sm:py-12">
      <div className="mx-auto w-full max-w-2xl">
        <Link aria-label="FinPilot home" className="inline-flex items-center" to="/">
          <BrandLockup className="text-pine" wordmarkClassName="text-lg" />
        </Link>

        <section className="mx-auto mt-10 max-w-xl" aria-labelledby="consent-title">
          <p className="fp-eyebrow">FinPilot connection</p>
          <h1 className="fp-page-title mt-3" id="consent-title">Review access</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            An AI application is asking to connect to your FinPilot account. Review what it can read before you continue.
          </p>

          {errorMessage && !details && (
            <div className="mt-6 space-y-4">
              <ErrorMessage>{errorMessage}</ErrorMessage>
              <Button asChild variant="secondary">
                <Link to="/">Return to FinPilot</Link>
              </Button>
            </div>
          )}

          {details && (
            <div className="mt-7 space-y-5">
              <Card>
                <CardHeader>
                  <p className="fp-label">Requesting application</p>
                  <CardTitle>{details.client.name}</CardTitle>
                  <p className="text-sm text-muted">FinPilot account: {details.user.email}</p>
                </CardHeader>
                <CardContent>
                  <dl className="grid gap-4 border-t border-line pt-4 text-sm sm:grid-cols-[140px_1fr]">
                    <dt className="font-semibold text-muted">Client website</dt>
                    <dd className="break-all text-foreground-body">{details.client.uri || "Not provided"}</dd>
                    <dt className="font-semibold text-muted">Return address</dt>
                    <dd className="break-all font-mono text-xs text-foreground-body">{details.redirect_uri}</dd>
                  </dl>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>FinPilot data this app can read</CardTitle>
                  <p className="text-sm leading-6 text-muted">
                    Approval allows this app to call FinPilot’s current read-only tools:
                  </p>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-3 text-sm text-foreground-body">
                    <li className="flex gap-3"><ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-positive" /><span>List your companies and your role in each one.</span></li>
                    <li className="flex gap-3"><ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-positive" /><span>Read cash-flow summaries for companies you belong to.</span></li>
                    <li className="flex gap-3"><ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-positive" /><span>Read monthly budget-versus-actual summaries for those companies.</span></li>
                  </ul>
                  <p className="mt-4 rounded-md border border-line bg-surface-raised px-4 py-3 text-sm leading-6 text-foreground-body">
                    This connection cannot create or change FinPilot records. Data returned to the AI app may be processed under that provider’s own privacy terms.
                  </p>
                </CardContent>
              </Card>

              {requestedScopes.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Identity details requested</CardTitle>
                    <p className="text-sm text-muted">These are the identity scopes requested by the application.</p>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2 text-sm text-foreground-body">
                      {requestedScopes.map((scope) => <li key={scope}>{describeScope(scope)}</li>)}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {errorMessage && <ErrorMessage>{errorMessage}</ErrorMessage>}

              <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                <Button
                  disabled={pendingDecision !== null}
                  onClick={() => void decide("deny")}
                  variant="secondary"
                >
                  {pendingDecision === "deny" ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
                  Deny
                </Button>
                <Button
                  disabled={pendingDecision !== null}
                  onClick={() => void decide("approve")}
                >
                  {pendingDecision === "approve" ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : <ArrowUpRight aria-hidden="true" className="size-4" />}
                  {pendingDecision === "approve" ? "Approving" : "Approve read-only access"}
                </Button>
              </div>

              <p className="text-center text-xs leading-5 text-muted">
                FinPilot checks your company membership every time the app requests company data.
              </p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
