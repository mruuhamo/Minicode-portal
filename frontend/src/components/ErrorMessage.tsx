import { ApiError } from "../api/client";

export function ErrorMessage({ error }: { error: Error }) {
  const status = error instanceof ApiError ? error.status : undefined;
  const text =
    status === 401
      ? "Your session has expired. Reload the page to sign in again."
      : status === 403
        ? "You don't have access to the Learning section."
        : status === 404
          ? "This minicode was not found."
          : status === 503
            ? "Search is temporarily unavailable. Try again in a moment."
            : error.message || "Something went wrong.";
  return (
    <div className="mcl-error" role="alert">
      {text}
    </div>
  );
}
