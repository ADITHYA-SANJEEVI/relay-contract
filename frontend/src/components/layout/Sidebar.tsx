import React from 'react';
import { NavLink } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Workflow, 
  Cpu, 
  FlaskConical, 
  FileCheck2 
} from 'lucide-react';

interface SidebarProps {
  className?: string;
}

export const Sidebar: React.FC<SidebarProps> = ({ className = '' }) => {
  const navItems = [
    { to: '/board', label: 'Overview', icon: LayoutDashboard, end: true },
    { to: '/board/jobs', label: 'Jobs', icon: Workflow, end: false },
    { to: '/board/workers', label: 'Workers', icon: Cpu, end: false },
    { to: '/board/lab', label: 'Failure Lab', icon: FlaskConical, end: false },
    { to: '/board/evidence', label: 'Evidence', icon: FileCheck2, end: false },
  ];

  return (
    <aside 
      className={`w-[216px] min-w-[216px] bg-[var(--color-surface-1)] border-r border-[var(--color-border-subtle)] flex flex-col h-full ${className}`}
      aria-label="Primary Navigation"
    >
      {/* Brand */}
      <div className="h-[52px] px-4 flex items-center gap-2.5 border-b border-[var(--color-border-subtle)]">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--color-execution)] flex-shrink-0" aria-hidden="true">
          <path d="M4 6h7a4 4 0 0 1 4 4v0a4 4 0 0 0 4 4h1" />
          <path d="M4 18h7a4 4 0 0 0 4-4v0a4 4 0 0 1 4-4h1" />
          <circle cx="4" cy="6" r="1.5" fill="#86B7FF" />
          <circle cx="4" cy="18" r="1.5" fill="#86B7FF" />
          <circle cx="20" cy="14" r="1.5" fill="#79D9AA" />
          <circle cx="20" cy="10" r="1.5" fill="#6DD3D0" />
        </svg>
        <div className="flex flex-col">
          <span className="font-semibold text-sm tracking-tight text-[var(--color-text-primary)]">Relay</span>
          <span className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider font-mono">Control Board</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto" aria-label="Main menu">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `
                flex items-center gap-2.5 px-3 py-2 rounded-md text-xs font-medium transition-colors
                ${isActive 
                  ? 'bg-[var(--color-surface-2)] text-[var(--color-execution)] border-l-2 border-[var(--color-execution)] pl-2.5 font-semibold' 
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text-primary)]'
                }
              `}
            >
              <Icon size={16} aria-hidden="true" className="flex-shrink-0" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Environment Footer */}
      <div className="p-3 border-t border-[var(--color-border-subtle)] text-[11px] text-[var(--color-text-muted)] font-mono">
        <div className="flex items-center justify-between">
          <span>Target</span>
          <span className="text-[var(--color-text-secondary)]">local</span>
        </div>
        <div className="flex items-center justify-between mt-1">
          <span>Revision</span>
          <span className="text-[var(--color-text-secondary)]">0002_ready</span>
        </div>
      </div>
    </aside>
  );
};
