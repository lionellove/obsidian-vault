import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

type StatProps = {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
};

export function Stat({ label, value, detail }: StatProps) {
  return (
    <section className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {detail ? <div className="stat-detail">{detail}</div> : null}
    </section>
  );
}

export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Notice({ tone, children }: { tone: "ok" | "warn" | "danger" | "info"; children: ReactNode }) {
  const Icon = tone === "ok" ? CheckCircle2 : AlertTriangle;
  return (
    <div className={`notice ${tone}`}>
      <Icon size={18} />
      <span>{children}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Loading() {
  return (
    <div className="loading">
      <Loader2 size={18} className="spin" />
      Loading
    </div>
  );
}
