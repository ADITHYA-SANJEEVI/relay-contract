import React, { useState, useMemo } from 'react';
import { RelayEvent } from '../../types/domain';
import { CopyField } from '../common/CopyField';
import { 
  History, 
  ChevronDown, 
  ChevronRight, 
  Repeat, 
  CheckCircle2, 
  AlertOctagon, 
  Clock, 
  FileCheck 
} from 'lucide-react';

interface EventListProps {
  events: RelayEvent[];
  selectedPartitionOrdinal?: number | null;
  onSelectPartitionOrdinal?: (ordinal: number) => void;
  isLoading?: boolean;
  nextCursor?: string | null;
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
}

interface EventItemOrGroup {
  isGroup: boolean;
  events: RelayEvent[];
  key: string;
}

export const EventList: React.FC<EventListProps> = ({
  events,
  selectedPartitionOrdinal,
  onSelectPartitionOrdinal,
  isLoading = false,
  nextCursor = null,
  onLoadMore,
  isLoadingMore = false,
}) => {
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [expandedDetails, setExpandedDetails] = useState<Record<string, boolean>>({});

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const toggleDetail = (seq: string) => {
    setExpandedDetails(prev => ({ ...prev, [seq]: !prev[seq] }));
  };

  // Group consecutive LEASE_RENEWED events in the loaded range
  const groupedItems = useMemo<EventItemOrGroup[]>(() => {
    const items: EventItemOrGroup[] = [];
    let currentRenewals: RelayEvent[] = [];

    for (let i = 0; i < events.length; i++) {
      const ev = events[i];
      if (ev.type === 'LEASE_RENEWED') {
        currentRenewals.push(ev);
      } else {
        if (currentRenewals.length > 1) {
          items.push({
            isGroup: true,
            events: currentRenewals,
            key: `group-renew-${currentRenewals[0].seq}-${currentRenewals[currentRenewals.length - 1].seq}`
          });
          currentRenewals = [];
        } else if (currentRenewals.length === 1) {
          items.push({
            isGroup: false,
            events: currentRenewals,
            key: `single-${currentRenewals[0].seq}`
          });
          currentRenewals = [];
        }
        items.push({
          isGroup: false,
          events: [ev],
          key: `single-${ev.seq}`
        });
      }
    }

    if (currentRenewals.length > 1) {
      items.push({
        isGroup: true,
        events: currentRenewals,
        key: `group-renew-${currentRenewals[0].seq}-${currentRenewals[currentRenewals.length - 1].seq}`
      });
    } else if (currentRenewals.length === 1) {
      items.push({
        isGroup: false,
        events: currentRenewals,
        key: `single-${currentRenewals[0].seq}`
      });
    }

    return items;
  }, [events]);

  const getEventIcon = (type: string) => {
    switch (type) {
      case 'RESULT_ACCEPTED':
        return <CheckCircle2 size={14} className="text-[var(--color-accepted)]" aria-hidden="true" />;
      case 'PUBLICATION_REJECTED':
      case 'ATTEMPT_FAILED':
        return <AlertOctagon size={14} className="text-[var(--color-failure)]" aria-hidden="true" />;
      case 'LEASE_RENEWED':
        return <Repeat size={14} className="text-[var(--color-execution)]" aria-hidden="true" />;
      case 'ARTIFACT_RESERVED':
      case 'ARTIFACT_VERIFIED':
        return <FileCheck size={14} className="text-[var(--color-verified)]" aria-hidden="true" />;
      default:
        return <Clock size={14} className="text-[var(--color-text-secondary)]" aria-hidden="true" />;
    }
  };

  const renderSingleEvent = (ev: RelayEvent) => {
    const isDetailOpen = expandedDetails[ev.seq];
    const isPartitionMatched = selectedPartitionOrdinal !== undefined && 
                               selectedPartitionOrdinal !== null && 
                               ev.partition_ordinal === selectedPartitionOrdinal;

    return (
      <div 
        key={ev.seq} 
        className={`p-3 rounded border transition-colors ${
          isPartitionMatched 
            ? 'bg-[var(--color-surface-2)] border-[var(--color-execution)]' 
            : 'bg-[var(--color-surface-1)] border-[var(--color-border-subtle)]'
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold text-[var(--color-text-primary)] px-1.5 py-0.5 rounded bg-[var(--color-surface-2)]">
              #{ev.seq}
            </span>
            {getEventIcon(ev.type)}
            <span className="font-mono font-semibold text-[var(--color-text-primary)]">
              {ev.type}
            </span>
            {ev.attempt_generation && (
              <span className="font-mono text-[var(--color-text-secondary)] text-[11px] px-1 py-0.5 rounded bg-[var(--color-surface-2)]">
                G{ev.attempt_generation}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 font-mono text-[11px] text-[var(--color-text-muted)]">
            {ev.partition_ordinal !== undefined && ev.partition_ordinal !== null && (
              <button
                type="button"
                onClick={() => onSelectPartitionOrdinal && onSelectPartitionOrdinal(ev.partition_ordinal!)}
                className="text-[var(--color-execution)] hover:underline"
              >
                Partition {ev.partition_ordinal}
              </button>
            )}
            <span>
              {new Date(ev.occurred_at).toISOString().replace('T', ' ').slice(0, 19)} UTC
            </span>
          </div>
        </div>

        {/* State transition if applicable */}
        {(ev.from_state || ev.to_state) && (
          <div className="mt-1.5 flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)] font-mono">
            <span>Transition:</span>
            <span className="text-[var(--color-text-muted)]">{ev.from_state || 'null'}</span>
            <span>→</span>
            <span className="text-[var(--color-text-primary)] font-semibold">{ev.to_state}</span>
          </div>
        )}

        {/* Expandable Raw Details */}
        <div className="mt-2 pt-1 border-t border-[var(--color-border-subtle)] flex items-center justify-between">
          <button
            type="button"
            onClick={() => toggleDetail(ev.seq)}
            className="inline-flex items-center gap-1 text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
            aria-expanded={isDetailOpen}
          >
            {isDetailOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>Raw Details</span>
          </button>

          {ev.attempt_id && (
            <span className="text-[11px] font-mono text-[var(--color-text-muted)]">
              Attempt: <CopyField value={ev.attempt_id} label="Attempt ID" shorten truncateLength={4} />
            </span>
          )}
        </div>

        {isDetailOpen && (
          <pre className="mt-2 p-2 rounded bg-[var(--color-canvas)] text-[11px] font-mono text-[var(--color-text-secondary)] overflow-x-auto border border-[var(--color-border-subtle)]">
            {JSON.stringify({ actor_type: ev.actor_type, actor_id: ev.actor_id, request_id: ev.request_id, details: ev.details }, null, 2)}
          </pre>
        )}
      </div>
    );
  };

  if (isLoading && events.length === 0) {
    return (
      <div className="p-8 text-center text-xs text-[var(--color-text-muted)]" aria-busy="true">
        Loading event chronology…
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="p-8 text-center text-xs text-[var(--color-text-muted)]">
        No events recorded for this job yet.
      </div>
    );
  }

  const firstLoadedSeq = events.length > 0 ? events[0].seq : '0';
  const lastLoadedSeq = events.length > 0 ? events[events.length - 1].seq : '0';

  return (
    <div className="space-y-3" role="feed" aria-label="Job event chronology">
      <div className="p-2.5 rounded bg-[var(--color-surface-2)] border border-[var(--color-border-subtle)] flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--color-text-secondary)] font-mono">
        <div className="flex items-center gap-2">
          <History size={14} className="text-[var(--color-execution)]" aria-hidden="true" />
          <span>
            Loaded Sequence Range: <strong className="text-[var(--color-text-primary)]">#{firstLoadedSeq} – #{lastLoadedSeq}</strong> ({events.length} events)
          </span>
        </div>
        <div className="flex items-center gap-2">
          {nextCursor === null ? (
            <span className="px-2 py-0.5 rounded bg-[rgba(121,217,170,0.15)] text-[var(--color-accepted)] border border-[rgba(121,217,170,0.3)] text-[11px] font-semibold">
              At Stream Frontier
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded bg-[rgba(240,198,116,0.15)] text-[var(--color-attention)] border border-[rgba(240,198,116,0.3)] text-[11px] font-semibold">
              Stream Truncated (More Events Ahead)
            </span>
          )}
        </div>
      </div>

      <div className="space-y-2">
        {groupedItems.map((item) => {
          if (!item.isGroup) {
            return renderSingleEvent(item.events[0]);
          }

          const isGroupExpanded = expandedGroups[item.key];
          const firstSeq = item.events[0].seq;
          const lastSeq = item.events[item.events.length - 1].seq;

          return (
            <div 
              key={item.key} 
              className="border border-[var(--color-border-subtle)] rounded overflow-hidden"
            >
              <button
                type="button"
                onClick={() => toggleGroup(item.key)}
                className="w-full p-2.5 bg-[var(--color-surface-1)] hover:bg-[var(--color-surface-hover)] flex items-center justify-between text-xs text-[var(--color-text-secondary)] font-mono transition-colors text-left"
                aria-expanded={isGroupExpanded}
              >
                <div className="flex items-center gap-2">
                  <Repeat size={13} className="text-[var(--color-execution)]" aria-hidden="true" />
                  <span className="font-semibold text-[var(--color-text-primary)]">
                    {item.events.length} renewal events in this loaded range
                  </span>
                  <span className="text-[var(--color-text-muted)]">
                    (seq #{firstSeq} – #{lastSeq})
                  </span>
                </div>
                <div className="flex items-center gap-1 text-[11px] text-[var(--color-text-muted)]">
                  <span>{isGroupExpanded ? 'Collapse' : 'Expand'}</span>
                  {isGroupExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </div>
              </button>

              {isGroupExpanded && (
                <div className="p-2 space-y-2 bg-[var(--color-canvas)] border-t border-[var(--color-border-subtle)]">
                  {item.events.map(renderSingleEvent)}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Pagination / Frontier Controls */}
      {nextCursor && onLoadMore && (
        <div className="p-3 text-center bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] rounded-lg">
          <button
            type="button"
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="btn-primary text-xs font-mono"
          >
            {isLoadingMore ? 'Loading next batch…' : `Load Next Batch (after seq #${nextCursor}) →`}
          </button>
        </div>
      )}
      {!nextCursor && events.length > 0 && (
        <div className="p-2 text-center text-xs text-[var(--color-text-muted)] font-mono">
          All recorded stream events loaded up to sequence #{lastLoadedSeq}.
        </div>
      )}
    </div>
  );
};
