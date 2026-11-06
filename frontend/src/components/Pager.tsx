interface Props {
  total: number;
  limit: number;
  offset: number;
  onOffset: (offset: number) => void;
}

export function Pager({ total, limit, offset, onOffset }: Props) {
  if (total <= limit) return null;
  const end = Math.min(offset + limit, total);
  return (
    <div className="pager">
      <button disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - limit))}>
        Previous
      </button>
      <span>
        {offset + 1} to {end} of {total}
      </span>
      <button disabled={end >= total} onClick={() => onOffset(offset + limit)}>
        Next
      </button>
    </div>
  );
}
