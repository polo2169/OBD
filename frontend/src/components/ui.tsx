import type { ReactNode } from "react";

type NavButtonProps = {
  active: boolean;
  glyph: string;
  label: string;
  onClick: () => void;
  count?: number;
};

export function NavButton({ active, glyph, label, onClick, count }: NavButtonProps) {
  return (
    <button className={`nav-button ${active ? "active" : ""}`} onClick={onClick}>
      <span className="nav-glyph">{glyph}</span>
      <span>{label}</span>
      {count !== undefined && <span className="nav-count">{count}</span>}
    </button>
  );
}

type EmptyStateProps = {
  title: string;
  text: string;
  action?: ReactNode;
};

export function EmptyState({ title, text, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-symbol">◇</span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
