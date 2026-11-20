import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LearningSection } from "./LearningSection";
import { API, requests } from "./test/server";

describe("LearningSection", () => {
  it("owns a BrowserRouter when the host has none, and uses the host's token provider", async () => {
    window.history.pushState({}, "", "/learning/minicodes/01MOCKBICEP");
    render(<LearningSection apiBaseUrl={API} basePath="/learning/" getAccessToken={async () => "portal-token"} />);

    expect(await screen.findByRole("heading", { level: 1, name: "Minicode: Bicep private registry" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← All minicodes" })).toHaveAttribute("href", "/learning");
    expect(requests.every((r) => r.headers.get("authorization") === "Bearer portal-token")).toBe(true);
    window.history.pushState({}, "", "/");
  });
});
