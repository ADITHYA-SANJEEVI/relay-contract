import React from 'react';
import { CapabilityState } from '../../types/domain';
import { AlertCircle, Lock, ServerOff, SearchX, RefreshCw } from 'lucide-react';

interface CapabilityUnavailableProps {
  capability?: CapabilityState;
  title?: string;
  description?: string;
  requiredReadContract?: string;
  type?: 'gap' | '401' | '403' | '404' | '422' | '503' | 'disconnected';
  onRetry?: () => void;
}

export const CapabilityUnavailable: React.FC<CapabilityUnavailableProps> = ({
  capability,
  title,
  description,
  requiredReadContract,
  type = 'gap',
  onRetry,
}) => {
  const displayTitle = title || capability?.title || 'Capability Unavailable';
  const displayDesc = description || capability?.description || 'This operation or observation is not exposed by the current backend contract.';
  const displayContract = requiredReadContract || capability?.requiredReadContract;

  const renderIcon = () => {
    switch (type) {
      case '401':
      case '403':
        return <Lock size={20} className="text-[var(--color-attention)]" aria-hidden="true" />;
      case '404':
        return <SearchX size={20} className="text-[var(--color-text-muted)]" aria-hidden="true" />;
      case '503':
      case 'disconnected':
        return <ServerOff size={20} className="text-[var(--color-failure)]" aria-hidden="true" />;
      default:
        return <AlertCircle size={20} className="text-[var(--color-attention)]" aria-hidden="true" />;
    }
  };

  return (
    <div 
      className="p-6 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] text-center max-w-xl mx-auto my-8"
      role="region"
      aria-label={displayTitle}
    >
      <div className="flex justify-center mb-3">
        <div className="p-3 rounded-full bg-[rgba(255,255,255,0.04)]">
          {renderIcon()}
        </div>
      </div>

      <h3 className="text-base font-semibold text-[var(--color-text-primary)]">
        {displayTitle}
      </h3>

      <p className="mt-2 text-xs text-[var(--color-text-secondary)] leading-relaxed">
        {displayDesc}
      </p>

      {displayContract && (
        <div className="mt-4 p-2.5 rounded bg-[var(--color-surface-2)] border border-[var(--color-border-subtle)] text-left font-mono text-xs">
          <div className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-wider mb-1">
            Required Read Contract:
          </div>
          <div className="text-[var(--color-execution)] select-all">
            {displayContract}
          </div>
        </div>
      )}

      {onRetry && (
        <div className="mt-5">
          <button 
            type="button" 
            onClick={onRetry}
            className="btn-secondary text-xs"
          >
            <RefreshCw size={13} aria-hidden="true" />
            <span>Retry Observation</span>
          </button>
        </div>
      )}
    </div>
  );
};
