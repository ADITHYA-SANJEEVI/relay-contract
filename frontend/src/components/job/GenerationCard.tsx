import React from 'react';
import { GenerationDetail } from '../../types/domain';
import { 
  RecordedStatusBadge, 
  ArtifactStatusBadge, 
  PublicationStatusBadge 
} from '../common/StatusBadges';
import { CopyField } from '../common/CopyField';
import { Layers } from 'lucide-react';

interface GenerationCardProps {
  generation: GenerationDetail;
  isSelected?: boolean;
  onSelect?: () => void;
}

export const GenerationCard: React.FC<GenerationCardProps> = ({
  generation,
  isSelected = false,
  onSelect,
}) => {
  const isAccepted = generation.publication.status === 'ACCEPTED';

  return (
    <div
      onClick={onSelect}
      onKeyDown={(e) => {
        if (onSelect && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onSelect();
        }
      }}
      tabIndex={onSelect ? 0 : undefined}
      role={onSelect ? 'button' : 'region'}
      aria-label={`Generation ${generation.generation}`}
      className={`
        p-3.5 rounded-sm border transition-all
        ${isSelected 
          ? 'bg-[var(--color-surface-2)] border-[var(--color-execution)]' 
          : 'bg-[var(--color-surface-1)] border-[var(--color-border-subtle)] hover:border-[var(--color-border-control)]'
        }
        ${isAccepted ? 'authority-rail-accepted' : ''}
      `}
    >
      {/* Header: Generation Number & Quick identity */}
      <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[var(--color-border-subtle)]">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 font-mono font-bold text-xs px-2 py-0.5 rounded bg-[var(--color-surface-2)] text-[var(--color-text-primary)] border border-[var(--color-border-subtle)]">
            <Layers size={11} aria-hidden="true" />
            G{generation.generation}
          </span>
          <span className="text-xs text-[var(--color-text-secondary)] font-mono">
            Attempt: <CopyField value={generation.attempt_id} label="Attempt ID" shorten truncateLength={6} />
          </span>
        </div>

        {generation.worker_session_id && (
          <span className="text-[11px] text-[var(--color-text-muted)] font-mono hidden sm:inline">
            Worker: <CopyField value={generation.worker_session_id} label="Worker Session" shorten truncateLength={4} />
          </span>
        )}
      </div>

      {/* 3 Independent Dimensions */}
      <div className="space-y-2 text-xs">
        {/* Dimension 1: Recorded Attempt Lifecycle */}
        <div className="flex items-center justify-between">
          <span className="text-[var(--color-text-secondary)] font-medium">
            Attempt Lifecycle:
          </span>
          <div>
            <RecordedStatusBadge status={generation.status} type="attempt" />
          </div>
        </div>

        {/* Dimension 2: Artifact State */}
        <div className="flex items-center justify-between">
          <span className="text-[var(--color-text-secondary)] font-medium">
            Artifact Verification:
          </span>
          <div>
            {generation.artifact ? (
              <ArtifactStatusBadge status={generation.artifact.status} />
            ) : (
              <ArtifactStatusBadge status="UNAVAILABLE" />
            )}
          </div>
        </div>

        {/* Dimension 3: Publication State */}
        <div className="flex items-center justify-between">
          <span className="text-[var(--color-text-secondary)] font-medium">
            Publication Outcome:
          </span>
          <div>
            <PublicationStatusBadge 
              status={generation.publication.status} 
              rejectionReason={generation.publication.rejection_reason} 
            />
          </div>
        </div>
      </div>

      {/* Artifact ID if present */}
      {generation.artifact && (
        <div className="mt-2.5 pt-2 border-t border-[var(--color-border-subtle)] flex items-center justify-between text-[11px] font-mono text-[var(--color-text-muted)]">
          <span>Artifact:</span>
          <CopyField value={generation.artifact.id} label="Artifact ID" shorten truncateLength={8} />
        </div>
      )}
    </div>
  );
};
