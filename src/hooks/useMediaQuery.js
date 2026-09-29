import { useState, useEffect } from 'react';

export function useMediaQuery(query) {
  // Lazy initializer reads the real match on the FIRST render instead of
  // defaulting to false and correcting a render later -- that one-render
  // flash (false -> true -> false as the effect below catches up) was
  // enough to mount-then-immediately-exit Sidebar.js's backdrop overlay,
  // which left a zombie element behind: framer-motion's exit animation
  // fades opacity to 0 but doesn't set pointer-events:none, so an
  // invisible full-page click-blocker could survive indefinitely. Confirmed
  // live -- this froze every button/input on the page at a 1024px viewport.
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const media = window.matchMedia(query);
    setMatches(media.matches);
    const handler = (e) => setMatches(e.matches);
    media.addEventListener('change', handler);
    return () => media.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

export const useIsMobile = () => useMediaQuery('(max-width: 768px)');
export const useIsTablet = () => useMediaQuery('(max-width: 1024px)');
