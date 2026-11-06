/** Контексты: авторизация (Bearer/X-Api-Key + профиль) и тосты (ТЗ §5.3). */
import React from "react";
import { api } from "../api";

export interface AuthUser {
  id: string | null;
  org_id: string;
  email: string;
  display_name: string | null;
  role: "admin" | "supervisor" | "analyst" | "agent" | "dpo";
  team_name: string | null;
  agent_ext_ids: string[];
  is_active: boolean;
  is_service?: boolean;
}

interface AuthCtx {
  user: AuthUser | null;
  setUser: (u: AuthUser | null) => void;
  hasRole: (...roles: string[]) => boolean;
  logout: () => void;
}

const Ctx = React.createContext<AuthCtx>({
  user: null,
  setUser: () => undefined,
  hasRole: () => false,
  logout: () => undefined,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<AuthUser | null>(null);
  React.useEffect(() => {
    // UI-01: все обращения к API — через api.ts, без прямых fetch
    api.me()
      .then((u) => setUser(u as AuthUser))
      .catch(() => undefined);
  }, []);
  const value: AuthCtx = {
    user,
    setUser,
    hasRole: (...roles) => (user ? roles.includes(user.role) : false),
    logout: () => setUser(null),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  return React.useContext(Ctx);
}

interface Toast { id: number; kind: "success" | "error"; text: string }
const ToastCtx = React.createContext<{ push: (kind: Toast["kind"], text: string) => void }>({ push: () => undefined });
let toastSeq = 1;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const push = React.useCallback((kind: Toast["kind"], text: string) => {
    const id = toastSeq++;
    setToasts((prev) => [...prev, { id, kind, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="toast-wrap">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return React.useContext(ToastCtx);
}
