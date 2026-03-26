import { useEffect, useState } from "react";

// Tracks the responsive layout mode because the app should stay usable on both desktop and smaller devices.
function getIsCompactLayout() {
  return window.innerWidth < 1100;
}

// Exposes the compact breakpoint because the shell layout should respond to viewport changes in one shared hook.
export default function useCompactLayout() {
  const [isCompactLayout, setIsCompactLayout] = useState(getIsCompactLayout);

  useEffect(function syncCompactLayoutOnResize() {
    // Recomputes the breakpoint on resize because the user may rotate or resize the browser after the app loads.
    function handleResize() {
      setIsCompactLayout(getIsCompactLayout());
    }

    window.addEventListener("resize", handleResize);

    return function cleanupResizeListener() {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return isCompactLayout;
}
