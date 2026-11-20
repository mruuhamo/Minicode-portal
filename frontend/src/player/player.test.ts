import { describe, expect, it } from "vitest";
import { detail } from "../test/fixtures";
import { choosePlayer } from "./choosePlayer";
import { withStartTime } from "./streamUrl";

describe("withStartTime", () => {
  it("sets st inside the embed JSON parameter", () => {
    const url = new URL(withStartTime(detail.embedUrl!, 125.7));
    expect(JSON.parse(url.searchParams.get("embed")!)).toEqual({ ust: true, hv: "CopyEmbedCode", st: 125 });
    expect(url.searchParams.get("UniqueId")).toBe("abc");
  });

  it("removes the start time for 0", () => {
    const url = new URL(withStartTime(withStartTime(detail.embedUrl!, 60), 0));
    expect(JSON.parse(url.searchParams.get("embed")!)).not.toHaveProperty("st");
  });
});

describe("choosePlayer", () => {
  const noEmbed = { ...detail, embedUrl: null };
  const demo = () => "/demo.mp4";

  it("prefers the Stream embed in auto mode", () => {
    expect(choosePlayer(detail, { mode: "auto", videoUrl: demo })).toEqual({ kind: "stream" });
    expect(choosePlayer(noEmbed, { mode: "auto", videoUrl: demo })).toEqual({ kind: "html5", src: "/demo.mp4" });
    expect(choosePlayer(noEmbed, { mode: "auto" })).toEqual({ kind: "link" });
  });

  it("honours forced modes", () => {
    expect(choosePlayer(detail, { mode: "html5", videoUrl: demo })).toEqual({ kind: "html5", src: "/demo.mp4" });
    expect(choosePlayer(noEmbed, { mode: "stream", videoUrl: demo })).toEqual({ kind: "link" });
  });
});
