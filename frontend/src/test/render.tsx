import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { LearningSection, type LearningSectionProps } from "../LearningSection";
import { API } from "./server";

function LocationProbe() {
  const loc = useLocation();
  return <output data-testid="location">{loc.pathname + loc.search}</output>;
}

/** Renders the section inside a host router at /learning/*, the way the portal would mount it. */
export function renderSection(path: string, props: Partial<LearningSectionProps> = {}) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/learning/*" element={<LearningSection apiBaseUrl={API} basePath="/learning" {...props} />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}
