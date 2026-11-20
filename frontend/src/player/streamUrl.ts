/**
 * Sets the start time of a Stream (SharePoint) embed URL.
 *
 * The URL comes from the API (`embedUrl`, built from Stream's "Embed code" dialog format):
 * `.../_layouts/15/embed.aspx?UniqueId=<id>&embed={"ust":true,"hv":"CopyEmbedCode"}`.
 * `st` is the start time in seconds and `ust` turns it on. UNVERIFIED against the tenant - see docs/week4-frontend.md.
 */
export function withStartTime(embedUrl: string, seconds: number): string {
  const url = new URL(embedUrl);
  let embed: Record<string, unknown> = {};
  try {
    embed = JSON.parse(url.searchParams.get("embed") ?? "{}") as Record<string, unknown>;
  } catch {
    embed = {};
  }
  const st = Math.max(0, Math.floor(seconds));
  if (st > 0) {
    embed.ust = true;
    embed.st = st;
  } else {
    delete embed.st;
  }
  url.searchParams.set("embed", JSON.stringify(embed));
  return url.toString();
}
