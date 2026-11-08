import { PAGE_SIZES } from "../hooks";

interface Props {
  total: number;
  limit: number;
  offset: number;
  onOffset: (offset: number) => void;
  onLimit: (limit: number) => void;
}

export function Pager({ total, limit, offset, onOffset, onLimit }: Props) {
  const end = Math.min(offset + limit, total);
  return (
    <div className="pager">
      <label>
        Rows per page
        <select value={limit} onChange={(e) => onLimit(Number(e.target.value))}>
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <span className="mono">
        {offset + 1} to {end} of {total}
      </span>
      <button disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - limit))}>
        Previous
      </button>
      <button disabled={end >= total} onClick={() => onOffset(offset + limit)}>
        Next
      </button>
    </div>
  );
}
