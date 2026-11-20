export function Pagination({
  page,
  pageSize,
  count,
  onPage,
}: {
  page: number;
  pageSize: number;
  count: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages <= 1) return null;
  return (
    <nav className="mcl-pagination" aria-label="Pagination">
      <button type="button" className="mcl-button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span aria-current="page">
        Page {page} of {pages}
      </span>
      <button type="button" className="mcl-button" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}
