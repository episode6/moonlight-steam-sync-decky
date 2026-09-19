import { useEffect, useState } from "react";

import type { Store } from "../lib/state";

/** Re-render on every store change; returns the current state. */
export function useStore<S>(store: Store<S>): S {
  const [state, setState] = useState(store.get());
  useEffect(() => {
    const unsubscribe = store.subscribe(() => setState(store.get()));
    setState(store.get()); // anything that changed between render and subscribe
    return unsubscribe;
  }, [store]);
  return state;
}
