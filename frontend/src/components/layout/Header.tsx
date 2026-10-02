import React from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useRelay } from '../../context/RelayContext';
import { RefreshCw, CheckCircle2, AlertTriangle, XCircle, Menu } from 'lucide-react';

interface HeaderProps {
  onToggleSidebar?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onToggleSidebar }) => {
  const { connectionStatus, refreshHealth } = useRelay();
  const location = useLocation();

  // Generate breadcrumb items
  const pathParts = location.pathname.split('/').filter(Boolean);
  const breadcrumbs = pathParts.map((part, index) => {
    const url = `/${pathParts.slice(0, index + 1).join('/')}`;
    const isLast = index === pathParts.length - 1;
    let label = part;
    if (part === 'board') label = 'Board';
    else if (part === 'jobs') label = 'Jobs';
    else if (part === 'workers') label = 'Workers';
    else if (part === 'lab') label = 'Failure Lab';
    else if (part === 'evidence') label = 'Evidence';
    else if (part === 'partitions') label = 'Partitions';
    else if (part.length > 12) label = `${part.slice(0, 6)}…${part.slice(-4)}`;

    return { url, label, isLast };
  });

  return (
    <header 
      className="h-[52px] min-h-[52px] px-4 bg-[var(--color-surface-1)] border-b border-[var(--color-border-subtle)] flex items-center justify-between"
      role="banner"
    >
      <div className="flex items-center gap-3">
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className="xl:hidden btn-icon text-[var(--color-text-secondary)]"
            aria-label="Toggle navigation menu"
          >
            <Menu size={18} aria-hidden="true" />
          </button>
        )}

        {/* Breadcrumb */}
        <nav aria-label="Breadcrumbs" className="flex items-center gap-1.5 text-xs">
          {breadcrumbs.map((bc, i) => (
            <React.Fragment key={bc.url}>
              {i > 0 && <span className="text-[var(--color-text-muted)]">/</span>}
              {bc.isLast ? (
                <span className="font-semibold text-[var(--color-text-primary)] font-mono" aria-current="page">
                  {bc.label}
                </span>
              ) : (
                <Link 
                  to={bc.url}
                  className="text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
                >
                  {bc.label}
                </Link>
              )}
            </React.Fragment>
          ))}
        </nav>
      </div>

      {/* Connection & Observation Status */}
      <div className="flex items-center gap-3 text-xs">
        {/* API Reachability */}
        <div className="flex items-center gap-1.5">
          <span className="text-[var(--color-text-muted)] hidden sm:inline">API:</span>
          {connectionStatus.apiReachable === true ? (
            <span className="inline-flex items-center gap-1 text-[var(--color-accepted)] font-mono text-[11px]" title="API HTTP process reachable">
              <CheckCircle2 size={13} aria-hidden="true" />
              <span>Reachable</span>
            </span>
          ) : connectionStatus.apiReachable === false ? (
            <span className="inline-flex items-center gap-1 text-[var(--color-failure)] font-mono text-[11px]" title="API unreachable">
              <XCircle size={13} aria-hidden="true" />
              <span>Unreachable</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-[var(--color-text-muted)] font-mono text-[11px]" title="API reachability unobserved">
              <span>Unknown</span>
            </span>
          )}
        </div>

        {/* Readiness Observation */}
        <div className="flex items-center gap-1.5">
          <span className="text-[var(--color-text-muted)] hidden sm:inline">Readiness:</span>
          {connectionStatus.readinessPassed === true ? (
            <span className="inline-flex items-center gap-1 text-[var(--color-accepted)] font-mono text-[11px]" title="Readiness checks passed">
              <CheckCircle2 size={13} aria-hidden="true" />
              <span>Passed</span>
            </span>
          ) : connectionStatus.readinessPassed === false ? (
            <span className="inline-flex items-center gap-1 text-[var(--color-attention)] font-mono text-[11px]" title="Readiness checks degraded or failed">
              <AlertTriangle size={13} aria-hidden="true" />
              <span>Degraded</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-[var(--color-text-muted)] font-mono text-[11px]" title="Readiness status unknown or not checked">
              <span>Unknown</span>
            </span>
          )}
        </div>

        {/* Observation Timestamp */}
        {connectionStatus.lastObservedAt && (
          <div className="hidden lg:flex items-center gap-1 text-[11px] text-[var(--color-text-muted)] font-mono">
            <span>Observed:</span>
            <span>
              {new Date(connectionStatus.lastObservedAt).toISOString().slice(11, 19)}Z
            </span>
          </div>
        )}

        {/* Refresh Action */}
        <button
          type="button"
          onClick={() => refreshHealth()}
          className="btn-icon text-[var(--color-text-secondary)]"
          aria-label="Refresh connection health observation"
          title="Refresh health observation"
        >
          <RefreshCw size={14} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
};
