/**
 * The site-wide line (v2 spec §1): this product places no orders, the ledger is the product.
 * A banner, not a footnote: it sits above every page so no screenshot of a number can lose it.
 */
export const NO_ORDERS_TEXT = "Places no orders — the ledger is the product.";

export function NoOrdersBanner() {
  return (
    <div
      role="note"
      className="border-b border-slate-800 bg-slate-900/70 px-4 py-1.5 text-center text-[11px] uppercase tracking-wider text-slate-400"
    >
      {NO_ORDERS_TEXT}
    </div>
  );
}
