// React hook wrapping KeyboardClient. Usage:
//   const { ready, schema, sendFrame, sendColors, setKeys, fill, clear } = useKeyboard();
import { useEffect, useRef, useState, useCallback } from "react";
import { KeyboardClient, type RGB, type Schema } from "./keyboardClient";

export function useKeyboard(url = "ws://127.0.0.1:8787") {
  const ref = useRef<KeyboardClient | null>(null);
  const [ready, setReady] = useState(false);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const c = new KeyboardClient(url);
    c.onOpen = () => { setReady(true); setError(null); };
    c.onClose = () => setReady(false);
    c.onSchema = (s) => setSchema(s);
    c.onError = (m) => setError(m);
    c.connect();
    ref.current = c;
    return () => { c.close(); ref.current = null; };
  }, [url]);

  const sendFrame = useCallback((buf: Uint8Array) => ref.current?.sendFrame(buf), []);
  const sendColors = useCallback((cs: (RGB | string)[]) => ref.current?.sendColors(cs), []);
  const setKeys = useCallback((m: Record<string, RGB | string>) => ref.current?.setKeys(m), []);
  const fill = useCallback((c: RGB | string) => ref.current?.fill(c), []);
  const clear = useCallback(() => ref.current?.clear(), []);

  return { ready, schema, error, sendFrame, sendColors, setKeys, fill, clear };
}
