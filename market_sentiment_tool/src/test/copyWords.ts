/**
 * How much explaining a page does, in words: everything inside headings and paragraphs, nothing inside
 * tables, chips, buttons or links (those are the data). Page tests assert a budget on this so the copy
 * cannot quietly grow back into essays. A page that needs more words should show a number instead.
 */
export function copyWords(root: ParentNode): number {
  const nodes = Array.from(root.querySelectorAll("h1, h2, h3, p, summary"));
  return nodes
    .map((node) => (node.textContent ?? "").trim())
    .filter(Boolean)
    .reduce((total, text) => total + text.split(/\s+/).length, 0);
}
