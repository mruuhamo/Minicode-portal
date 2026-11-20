import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Highlight } from "./Highlight";

describe("Highlight", () => {
  it("marks <em> fragments and renders everything else as text", () => {
    const { container } = render(<Highlight text={'push to the <em>registry</em> <img src=x onerror="alert(1)"> done'} />);
    expect(container.querySelector("mark")).toHaveTextContent("registry");
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent('push to the registry <img src=x onerror="alert(1)"> done');
  });
});
