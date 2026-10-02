import React from 'react';
import { GenerationDetail } from '../../types/domain';
import { GenerationCard } from './GenerationCard';
import { CapabilityUnavailable } from '../common/CapabilityUnavailable';

interface GenerationStackProps {
  generations: GenerationDetail[];
  selectedGeneration: string | null;
  onSelectGeneration: (gen: GenerationDetail) => void;
  isLoading?: boolean;
  isGap?: boolean;
}

export const GenerationStack: React.FC<GenerationStackProps> = ({
  generations,
  selectedGeneration,
  onSelectGeneration,
  isLoading = false,
  isGap = false,
}) => {
  if (isGap) {
    return (
      <CapabilityUnavailable
        title="Generation History Unavailable"
        description="Detailed attempt history and non-authoritative generations for this partition are not exposed by the current backend read route."
        requiredReadContract="GET /v1/operator/partitions/{id}"
      />
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-3" aria-busy="true">
        <div className="h-24 rounded-lg bg-[var(--color-surface-1)] animate-pulse" />
        <div className="h-24 rounded-lg bg-[var(--color-surface-1)] animate-pulse" />
      </div>
    );
  }

  if (generations.length === 0) {
    return (
      <div className="p-6 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] text-center text-xs text-[var(--color-text-muted)]">
        No generation history records recorded for this partition yet.
      </div>
    );
  }

  // Sort descending by generation number (highest / newest first)
  const sorted = [...generations].sort((a, b) => {
    return parseInt(b.generation, 10) - parseInt(a.generation, 10);
  });

  return (
    <div className="space-y-3" role="feed" aria-label="Generation history stack">
      {sorted.map((gen) => (
        <GenerationCard
          key={gen.generation}
          generation={gen}
          isSelected={gen.generation === selectedGeneration}
          onSelect={() => onSelectGeneration(gen)}
        />
      ))}
    </div>
  );
};
