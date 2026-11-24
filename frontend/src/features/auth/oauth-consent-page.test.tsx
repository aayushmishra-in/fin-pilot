import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthError } from "@supabase/supabase-js";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../app/app";
import { AuthProvider } from "../../app/auth-context";
import { queryClient } from "../../app/query-client";
import { setAuthSession } from "../../test/auth-session";
import { supabase } from "../../lib/supabase";
import { redirectToOAuthClient } from "../../lib/oauth-redirect";

vi.mock("../../lib/oauth-redirect", () => ({ redirectToOAuthClient: vi.fn() }));

const authorizationDetails = {
  authorization_id: "authorization-1",
  redirect_uri: "http://localhost:6274/oauth/callback",
  client: {
    id: "client-1",
    name: "FinPilot Inspector",
    uri: "https://example.test",
    logo_uri: "",
  },
  user: { id: "user-1", email: "owner@example.com" },
  scope: "openid email",
};

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("FinPilot OAuth consent", () => {
  beforeEach(() => {
    vi.mocked(supabase.auth.oauth.getAuthorizationDetails).mockReset();
    vi.mocked(supabase.auth.oauth.approveAuthorization).mockReset();
    vi.mocked(supabase.auth.oauth.denyAuthorization).mockReset();
    vi.mocked(redirectToOAuthClient).mockReset();
  });

  it("preserves the authorization request through sign-in", async () => {
    const user = userEvent.setup();
    vi.mocked(supabase.auth.oauth.getAuthorizationDetails).mockResolvedValue({
      data: authorizationDetails,
      error: null,
    });

    renderAt("/oauth/consent?authorization_id=authorization-1");

    await user.type(await screen.findByLabelText("Email address"), "owner@example.com");
    await user.type(screen.getByLabelText("Password"), "safe-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Review access" })).toBeInTheDocument();
    expect(await screen.findByText("FinPilot Inspector")).toBeInTheDocument();
    expect(screen.getByText("List your companies and your role in each one.")).toBeInTheDocument();
    expect(screen.getByText("Share your email address")).toBeInTheDocument();
    expect(supabase.auth.oauth.getAuthorizationDetails).toHaveBeenCalledWith("authorization-1");
  });

  it("redirects to the AI app after approval", async () => {
    const user = userEvent.setup();
    setAuthSession("mock-session-token");
    vi.mocked(supabase.auth.oauth.getAuthorizationDetails).mockResolvedValue({
      data: authorizationDetails,
      error: null,
    });
    vi.mocked(supabase.auth.oauth.approveAuthorization).mockResolvedValue({
      data: { redirect_url: "http://localhost:6274/oauth/callback?code=test-code" },
      error: null,
    });
    renderAt("/oauth/consent?authorization_id=authorization-1");
    await user.click(await screen.findByRole("button", { name: "Approve read-only access" }));

    await waitFor(() => {
      expect(supabase.auth.oauth.approveAuthorization).toHaveBeenCalledWith(
        "authorization-1",
        { skipBrowserRedirect: true },
      );
      expect(redirectToOAuthClient).toHaveBeenCalledWith("http://localhost:6274/oauth/callback?code=test-code");
    });
  });

  it("returns to the AI app after the user denies access", async () => {
    const user = userEvent.setup();
    setAuthSession("mock-session-token");
    vi.mocked(supabase.auth.oauth.getAuthorizationDetails).mockResolvedValue({
      data: authorizationDetails,
      error: null,
    });
    vi.mocked(supabase.auth.oauth.denyAuthorization).mockResolvedValue({
      data: { redirect_url: "http://localhost:6274/oauth/callback?error=access_denied" },
      error: null,
    });
    renderAt("/oauth/consent?authorization_id=authorization-1");
    await user.click(await screen.findByRole("button", { name: "Deny" }));

    await waitFor(() => {
      expect(supabase.auth.oauth.denyAuthorization).toHaveBeenCalledWith(
        "authorization-1",
        { skipBrowserRedirect: true },
      );
      expect(redirectToOAuthClient).toHaveBeenCalledWith("http://localhost:6274/oauth/callback?error=access_denied");
    });
  });

  it("skips the consent screen when Supabase says the user already authorized the app", async () => {
    setAuthSession("mock-session-token");
    vi.mocked(supabase.auth.oauth.getAuthorizationDetails).mockResolvedValue({
      data: { redirect_url: "http://localhost:6274/oauth/callback?code=existing-grant" },
      error: null,
    });

    renderAt("/oauth/consent?authorization_id=authorization-1");

    await waitFor(() => {
      expect(redirectToOAuthClient).toHaveBeenCalledWith(
        "http://localhost:6274/oauth/callback?code=existing-grant",
      );
    });
    expect(screen.queryByRole("heading", { name: "Review access" })).not.toBeInTheDocument();
  });

  it("shows a bounded message when the request is expired", async () => {
    setAuthSession("mock-session-token");
    vi.mocked(supabase.auth.oauth.getAuthorizationDetails).mockResolvedValue({
      data: null,
      error: new AuthError("raw authorization service detail", 400, "bad_request"),
    });

    renderAt("/oauth/consent?authorization_id=expired");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This authorization request is invalid or has expired. Start again from your AI app.",
    );
    expect(screen.queryByText("raw authorization service detail")).not.toBeInTheDocument();
  });
});
