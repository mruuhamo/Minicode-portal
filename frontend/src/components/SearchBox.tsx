import { useId, useState, type FormEvent } from "react";

export function SearchBox({ initial, onSearch }: { initial: string; onSearch: (q: string) => void }) {
  const [value, setValue] = useState(initial);
  const [prevInitial, setPrevInitial] = useState(initial);
  if (initial !== prevInitial) {
    // URL changed elsewhere (back button, clear filters): reflect it in the box
    setPrevInitial(initial);
    setValue(initial);
  }
  const id = useId();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSearch(value.trim());
  };

  return (
    <form className="mcl-searchbox" role="search" onSubmit={submit}>
      <label htmlFor={id} className="mcl-visually-hidden">
        Search minicodes
      </label>
      <input
        id={id}
        type="search"
        value={value}
        placeholder="Search titles, summaries and transcripts..."
        onChange={(e) => setValue(e.target.value)}
      />
      <button type="submit" className="mcl-button mcl-button--primary">
        Search
      </button>
    </form>
  );
}
