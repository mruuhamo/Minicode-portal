import { Link } from "react-router";
import { useLinks } from "../context";

export function NotFoundPage() {
  const links = useLinks();
  return (
    <div className="mcl-notfound">
      <h1>Page not found</h1>
      <Link to={links.listing()}>Back to all minicodes</Link>
    </div>
  );
}
