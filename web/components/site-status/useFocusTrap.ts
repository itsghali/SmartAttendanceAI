import { useEffect, useRef } from "react";

// Module-scoped stack, not per-hook state — Escape/Tab must only ever be
// handled by the topmost open panel (design review's stacked-drawer
// topology: EventDetailsDrawer over HistoryPanel, Escape closes topmost
// first). Registration-order-based event listeners can't guarantee this
// once a panel that opened later needs priority over one that opened
// earlier, so priority is tracked explicitly instead.
let panelStack: symbol[] = [];

export function useFocusTrap(
  active: boolean,
  containerRef: React.RefObject<HTMLElement | null>,
  onEscape: () => void,
) {
  const idRef = useRef<symbol | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const onEscapeRef = useRef(onEscape);

  useEffect(() => {
    onEscapeRef.current = onEscape;
  }, [onEscape]);

  useEffect(() => {
    if (!active) return;

    const id = Symbol("panel");
    idRef.current = id;
    panelStack.push(id);
    previouslyFocused.current = document.activeElement as HTMLElement | null;

    const container = containerRef.current;
    const focusableSelector =
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

    function getFocusable(): HTMLElement[] {
      if (!container) return [];
      return Array.from(container.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (el) => el.offsetParent !== null,
      );
    }

    // Move initial focus into the panel so a screen-reader user lands
    // somewhere meaningful, not left on the (now background) trigger.
    getFocusable()[0]?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      const isTopmost = panelStack[panelStack.length - 1] === id;
      if (!isTopmost) return;

      if (e.key === "Escape") {
        e.stopPropagation();
        onEscapeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = getFocusable();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      panelStack = panelStack.filter((x) => x !== id);
      // Restores to whatever had focus when THIS panel opened — for the
      // inner panel that's the row that opened it, for the outer panel
      // (closed after the inner already popped) that's the original
      // table row / search result, per the design review's spec.
      previouslyFocused.current?.focus();
    };
  }, [active, containerRef]);
}
