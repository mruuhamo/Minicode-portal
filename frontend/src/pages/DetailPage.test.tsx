import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { renderSection } from "../test/render";

beforeAll(() => {
  // jsdom has no media pipeline: make metadata "loaded" so seeking applies immediately
  Object.defineProperty(HTMLMediaElement.prototype, "readyState", { configurable: true, get: () => 4 });
  Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value: () => Promise.resolve() });
});

describe("DetailPage", () => {
  it("shows summary, tags and seeks the HTML5 player to ?t", async () => {
    const user = userEvent.setup();
    renderSection("/learning/minicodes/01MOCKBICEP?t=125", { player: "html5", demoVideoUrl: "/demo.mp4" });

    expect(await screen.findByRole("heading", { level: 1, name: "Minicode: Bicep private registry" })).toBeInTheDocument();
    expect(screen.getByText(/publish and consume Bicep modules/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Demo / tool walkthrough" })).toHaveAttribute("href", "/learning/?contentType=demo");
    const video = screen.getByLabelText("Video: Minicode: Bicep private registry") as HTMLVideoElement;
    await waitFor(() => expect(video.currentTime).toBe(125));
    expect(screen.getByRole("button", { name: /02:05/ })).toHaveAttribute("aria-current", "true");

    await user.click(screen.getByRole("button", { name: /00:00/ }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/learning/minicodes/01MOCKBICEP?t=0"));
    expect(video.currentTime).toBe(0);
  });

  it("embeds the Stream player with the start time", async () => {
    renderSection("/learning/minicodes/01MOCKBICEP?t=125");
    const frame = await screen.findByTitle("Video: Minicode: Bicep private registry");
    const src = new URL(frame.getAttribute("src")!);
    expect(JSON.parse(src.searchParams.get("embed")!)).toMatchObject({ st: 125, ust: true });
  });

  it("shows a not-found message for unknown ids", async () => {
    renderSection("/learning/minicodes/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("This minicode was not found.");
  });
});
