import { useEffect, useId, useRef, useState } from "react";

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}

export function useSheet(open: boolean, onClose: () => void) {
  const isSheet = useMediaQuery("(max-width: 767px)");
  const asideRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  // Escape closes; focus moves into the sheet/overlay and returns on close.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    const previous = document.activeElement as HTMLElement | null;
    asideRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (isSheet) previous?.focus();
    };
  }, [open, isSheet, onClose]);

  return { isSheet, asideRef, titleId };
}
