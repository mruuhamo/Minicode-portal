import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { lastRequest } from "../test/server";
import { renderSection } from "../test/render";

describe("ListingPage", () => {
  it("lists minicodes with facet counts and taxonomy labels", async () => {
    renderSection("/learning");

    expect(await screen.findByRole("heading", { name: "2 minicodes" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Minicode: Bicep private registry" })).toHaveAttribute(
      "href",
      "/learning/minicodes/01MOCKBICEP",
    );
    const topic = within(screen.getByRole("group", { name: "Topic" }));
    expect(await topic.findByRole("checkbox", { name: "DevOps & Infrastructure as Code, 1 minicode" })).toBeInTheDocument();
    const level = within(screen.getByRole("group", { name: "Level" }));
    expect(level.getByRole("checkbox", { name: /300 Advanced/ })).toBeInTheDocument();
  });

  it("keeps filter state in the URL and sends it to the API", async () => {
    const user = userEvent.setup();
    renderSection("/learning?tags=ai-genai");
    const presenter = within(await screen.findByRole("group", { name: "Presenter" }));

    await user.click(presenter.getByRole("checkbox", { name: /Aino Virtanen/ }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/learning?tags=ai-genai&presenter=Aino+Virtanen"),
    );
    await waitFor(() => expect(lastRequest("/minicodes")?.searchParams.get("presenter")).toBe("Aino Virtanen"));
    expect(lastRequest("/minicodes")?.searchParams.get("tags")).toBe("ai-genai");

    await user.click(screen.getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/learning$/));
  });

  it("searches and links transcript hits to the detail page at their timestamp", async () => {
    const user = userEvent.setup();
    renderSection("/learning");

    await user.type(await screen.findByRole("searchbox", { name: "Search minicodes" }), "registry{Enter}");

    expect(await screen.findByRole("heading", { name: '1 minicode for "registry"' })).toBeInTheDocument();
    expect(lastRequest("/search")?.searchParams.get("q")).toBe("registry");
    const hit = screen.getByRole("link", { name: /Play from 02:05/ });
    expect(hit).toHaveAttribute("href", "/learning/minicodes/01MOCKBICEP?t=125");
    expect(within(hit).getByText("registry", { selector: "mark" })).toBeInTheDocument();
    expect(hit.querySelector("script")).toBeNull();
  });
});
