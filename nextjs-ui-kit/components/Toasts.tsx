"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

/* Minimal toast system that reuses app.css's .toasts / .toast[.success|.error|.warning].
   Drop <ToastProvider> around your app, then call useToast().push(...). If you
   already use a toast lib (sonner, react-hot-toast), skip this file and just add
   className="toast success" etc. to its elements so app.css styles them. */

type Kind = "success" | "error" | "warning" | "";
type Toast = { id: number; text: string; kind: Kind };

const Ctx = createContext<{ push: (text: string, kind?: Kind) => void }>({
  push: () => {},
});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const push = useCallback((text: string, kind: Kind = "") => {
    setItems((cur) => [...cur, { id: Date.now() + Math.random(), text, kind }]);
  }, []);

  return (
    <Ctx.Provider value={{ push }}>
      {children}
      {items.length > 0 && (
        <div className="toasts">
          {items.map((t) => (
            <ToastRow key={t.id} toast={t} onDone={() => setItems((c) => c.filter((x) => x.id !== t.id))} />
          ))}
        </div>
      )}
    </Ctx.Provider>
  );
}

function ToastRow({ toast, onDone }: { toast: Toast; onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    const a = setTimeout(() => setLeaving(true), 4200);
    const b = setTimeout(onDone, 4700);
    return () => {
      clearTimeout(a);
      clearTimeout(b);
    };
  }, [onDone]);
  return (
    <div
      className={`toast ${toast.kind}`}
      style={{
        transition: "opacity .4s, transform .4s",
        opacity: leaving ? 0 : 1,
        transform: leaving ? "translateX(12px)" : "none",
      }}
    >
      {toast.text}
    </div>
  );
}

export const useToast = () => useContext(Ctx);
