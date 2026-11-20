import type { MinicodeDetail, MinicodeSummary, Page, SearchResponse, Taxonomy } from "../api/types";

export const taxonomy: Taxonomy = {
  topic: [
    { id: "devops-iac", label: "DevOps & Infrastructure as Code" },
    { id: "azure-platform", label: "Azure platform" },
    { id: "ai-genai", label: "AI & Generative AI" },
  ],
  content_type: [
    { id: "demo", label: "Demo / tool walkthrough" },
    { id: "knowledge-share", label: "Knowledge share / talk" },
  ],
  level: [
    { id: "200", label: "200 - Intermediate: familiar with the basics" },
    { id: "300", label: "300 - Advanced: hands-on experience expected" },
  ],
  version: 1,
};

export const bicep: MinicodeSummary = {
  id: "01MOCKBICEP",
  title: "Minicode: Bicep private registry",
  summary: "How to publish and consume Bicep modules from a private registry.",
  presenter: "Aino Virtanen",
  date: "2026-11-02",
  topics: ["devops-iac", "azure-platform"],
  contentType: "demo",
  level: 300,
  language: "en",
  keywords: ["bicep", "acr"],
  webUrl: "https://contoso.sharepoint.com/sites/minicodes/Shared%20Documents/Recordings/bicep.mp4",
  durationSeconds: 1800,
};

export const copilot: MinicodeSummary = {
  ...bicep,
  id: "01MOCKCOPILOT",
  title: "Minicode: GitHub Copilot tips",
  summary: "Prompting patterns for Copilot.",
  presenter: "Mikko Laine",
  date: "2026-09-14",
  topics: ["ai-genai"],
  contentType: "knowledge-share",
  level: 200,
};

export const listPage: Page<MinicodeSummary> = {
  items: [bicep, copilot],
  count: 2,
  top: 12,
  skip: 0,
  facets: {
    topics: [
      { value: "devops-iac", count: 1 },
      { value: "azure-platform", count: 1 },
      { value: "ai-genai", count: 1 },
    ],
    presenter: [
      { value: "Aino Virtanen", count: 1 },
      { value: "Mikko Laine", count: 1 },
    ],
    contentType: [
      { value: "demo", count: 1 },
      { value: "knowledge-share", count: 1 },
    ],
    level: [
      { value: 200, count: 1 },
      { value: 300, count: 1 },
    ],
    language: [{ value: "en", count: 2 }],
  },
};

export const searchPage: SearchResponse = {
  query: "registry",
  items: [
    {
      ...bicep,
      score: 3.2,
      matchedSummary: true,
      hits: [
        {
          chunkId: "01MOCKBICEP-0003",
          start: 125,
          end: 190,
          startLabel: "02:05",
          speakers: ["Aino Virtanen"],
          highlights: ["we push the module to the private <em>registry</em> with <script>x</script>"],
          text: null,
          url: `${bicep.webUrl}?nav=x`,
        },
      ],
    },
  ],
  count: 1,
  top: 12,
  skip: 0,
  facets: { topics: [{ value: "devops-iac", count: 1 }], presenter: [{ value: "Aino Virtanen", count: 1 }] },
};

export const detail: MinicodeDetail = {
  ...bicep,
  recordedAt: "2026-11-02T10:00:00Z",
  embedUrl:
    'https://contoso.sharepoint.com/sites/minicodes/_layouts/15/embed.aspx?UniqueId=abc&embed={"ust":true,"hv":"CopyEmbedCode"}',
  transcriptSource: "teams",
  chunkCount: 2,
  chapters: [
    { start: 0, end: 125, startLabel: "00:00", speakers: ["Aino Virtanen"], preview: "Welcome everyone", url: null },
    { start: 125, end: 190, startLabel: "02:05", speakers: ["Aino Virtanen"], preview: "Pushing to the registry", url: null },
  ],
};
