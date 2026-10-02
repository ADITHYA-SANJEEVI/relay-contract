import React from 'react';
import { AuthorityState } from '../../types/domain';
import { CopyField } from './CopyField';
import { CheckCircle2, MinusCircle, HelpCircle, AlertTriangle } from 'lucide-react';

interface AuthorityPanelProps {
  authority: AuthorityState | null;
  isLoading?: boolean;
}

export const AuthorityPanel: React.FC<AuthorityPanelProps> = ({ authority, isLoading = false }) => {
  if (isLoading) {
    return (
      <div 
        className="p-4 rounded-md bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]"
        aria-busy="true"
      >
        <span className="text-xs text-[var(--color-text-muted)]">Loading authority relation…</span>
      </div>
    );
  }

  if (!authority || authority.status === 'UNKNOWN') {
    return (
      <div 
        className="p-4 rounded-md bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]"
        role="region"
        aria-label="Result authority"
      >
        <div className="flex items-center gap-2 text-[var(--color-text-secondary)]">
          <HelpCircle size={16} aria-hidden="true" />
          <span className="font-semibold text-sm">Authority state unavailable</span>
        </div>
        <p className="mt-1 text-xs text-[var(--color-text-muted)]">
          The accepted-result relation for this partition could not be verified from available read models.
        </p>
      </div>
    );
  }

  if (authority.status === 'NONE') {
    return (
      <div 
        className="p-4 rounded-md bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]"
        role="region"
        aria-label="Result authority"
      >
        <div className="flex items-center gap-2 text-[var(--color-text-secondary)]">
          <MinusCircle size={16} aria-hidden="true" />
          <span className="font-semibold text-sm text-[var(--color-text-primary)]">No accepted result</span>
        </div>
        <p className="mt-1 text-xs text-[var(--color-text-muted)]">
          No attempt has committed an accepted output for Partition {authority.partition_ordinal}. Eventual success is not guaranteed.
        </p>
      </div>
    );
  }

  // Status is ACCEPTED
  return (
    <div 
      className="p-4 rounded-md bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] authority-rail-accepted"
      role="region"
      aria-label="Accepted result authority"
    >
      <div className="flex items-center justify-between pb-2 mb-3 border-b border-[var(--color-border-subtle)]">
        <div className="flex items-center gap-2">
          <CheckCircle2 size={16} className="text-[var(--color-accepted)]" aria-hidden="true" />
          <span className="font-semibold text-sm text-[var(--color-accepted)]">
            Accepted result
          </span>
          {authority.generation && (
            <span className="px-1.5 py-0.5 text-xs font-mono rounded bg-[rgba(121,217,170,0.15)] text-[var(--color-accepted)] border border-[rgba(121,217,170,0.3)]">
              Generation {authority.generation}
            </span>
          )}
        </div>
        {authority.accepted_at && (
          <span className="text-xs text-[var(--color-text-muted)] font-mono" title={`Accepted at ${authority.accepted_at}`}>
            {new Date(authority.accepted_at).toISOString().replace('T', ' ').slice(0, 19)} UTC
          </span>
        )}
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div>
          <dt className="text-[var(--color-text-secondary)] font-medium">Artifact ID</dt>
          <dd className="mt-0.5">
            {authority.artifact_id ? (
              <CopyField value={authority.artifact_id} label="Artifact ID" shorten truncateLength={8} />
            ) : (
              <span className="text-[var(--color-text-muted)]">Unavailable</span>
            )}
          </dd>
        </div>

        <div>
          <dt className="text-[var(--color-text-secondary)] font-medium">Attempt ID</dt>
          <dd className="mt-0.5">
            {authority.attempt_id ? (
              <CopyField value={authority.attempt_id} label="Attempt ID" shorten truncateLength={8} />
            ) : (
              <span className="text-[var(--color-text-muted)]">Unavailable</span>
            )}
          </dd>
        </div>

        {authority.publication_fingerprint && (
          <div className="sm:col-span-2">
            <dt className="text-[var(--color-text-secondary)] font-medium">Publication Fingerprint</dt>
            <dd className="mt-0.5">
              <CopyField value={authority.publication_fingerprint} label="Publication Fingerprint" shorten truncateLength={12} />
            </dd>
          </div>
        )}
      </dl>

      {/* Explicit later content integrity failure warning if present */}
      {authority.integrity_failure && (
        <div 
          className="mt-3 p-2.5 rounded bg-[rgba(240,198,116,0.12)] border border-[var(--color-attention)] text-xs text-[var(--color-attention)] flex items-start gap-2"
          role="alert"
        >
          <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div>
            <div className="font-semibold">Pinned content could not be verified on this read</div>
            <div className="mt-0.5 text-[var(--color-text-primary)]">
              {authority.integrity_failure.error_message}
            </div>
            {authority.integrity_failure.request_id && (
              <div className="mt-0.5 text-[var(--color-text-muted)] font-mono">
                Request ID: {authority.integrity_failure.request_id}
              </div>
            )}
            <div className="mt-1 text-[var(--color-text-secondary)] text-[11px]">
              The accepted authority relation remains valid. Content failure indicates a transport/storage read anomaly.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
