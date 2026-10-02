import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useRelay } from '../context/RelayContext';
import {
  JobSummary,
  PartitionItem,
  GenerationDetail,
  AuthorityState,
  RelayEvent
} from '../types/domain';
import { JobHeader } from '../components/job/JobHeader';
import { JobSummaryStrip } from '../components/job/JobSummaryStrip';
import { PartitionTable } from '../components/job/PartitionTable';
import { PartitionInspector } from '../components/job/PartitionInspector';
import { EventList } from '../components/job/EventList';
import { ResultsTab } from '../components/job/ResultsTab';
import { DefinitionTab } from '../components/job/DefinitionTab';
import { CapabilityUnavailable } from '../components/common/CapabilityUnavailable';

type ActiveTab = 'execution' | 'activity' | 'results' | 'definition';

export const JobDetailView: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { isSynthetic, liveAdapter, fixtureAdapter } = useRelay();

  // Tab state
  const tabParam = (searchParams.get('tab') as ActiveTab) || 'execution';
  const [activeTab, setActiveTab] = useState<ActiveTab>(tabParam);

  // Job data state
  const [job, setJob] = useState<JobSummary | null>(null);
  const [partitions, setPartitions] = useState<PartitionItem[]>([]);
  const [events, setEvents] = useState<RelayEvent[]>([]);
  const [nextEventCursor, setNextEventCursor] = useState<string | null>(null);
  const [isLoadingMoreEvents, setIsLoadingMoreEvents] = useState<boolean>(false);
  const [observedAt, setObservedAt] = useState<string>(new Date().toISOString());

  // Selected partition & inspector data
  const selectedOrdinalParam = searchParams.get('partition');
  const [selectedPartition, setSelectedPartition] = useState<PartitionItem | null>(null);
  const [generations, setGenerations] = useState<GenerationDetail[]>([]);
  const [authority, setAuthority] = useState<AuthorityState | null>(null);
  const [isInspectorOpenMobile, setIsInspectorOpenMobile] = useState<boolean>(false);
  const lastFocusedRowRef = React.useRef<HTMLElement | null>(null);

  // Filters & loading
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);

  // Sync tab with URL
  const handleTabChange = (tab: ActiveTab) => {
    setActiveTab(tab);
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.set('tab', tab);
      return next;
    });
  };

  // Close inspector drawer on mobile and restore focus
  const handleCloseInspectorMobile = useCallback(() => {
    setIsInspectorOpenMobile(false);
    if (selectedPartition) {
      const row = document.querySelector<HTMLElement>(`tr[data-partition-ordinal="${selectedPartition.ordinal}"]`);
      if (row) {
        row.focus();
        return;
      }
    }
    if (lastFocusedRowRef.current) {
      lastFocusedRowRef.current.focus();
    }
  }, [selectedPartition]);

  // Keyboard Escape listener to close drawer on smaller viewports
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isInspectorOpenMobile) {
        handleCloseInspectorMobile();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isInspectorOpenMobile, handleCloseInspectorMobile]);

  // Fetch job & partitions snapshot
  const loadJobData = useCallback(async (isBackground = false) => {
    if (!isBackground) setIsLoading(true);
    else setIsRefreshing(true);
    setError(null);

    try {
      if (isSynthetic) {
        const jobRes = await fixtureAdapter.getJob(jobId);
        const partRes = await fixtureAdapter.getPartitions(jobId || '', -1, 100, statusFilter === 'ALL' ? undefined : statusFilter);
        const evRes = await fixtureAdapter.getEvents(jobId || '');

        setJob(jobRes.data);
        setPartitions(partRes.items);
        setEvents(evRes.items);
        setNextEventCursor(evRes.next_cursor);
        setObservedAt(jobRes.asOf);

        // Retain or set selected partition
        const targetOrdinal = selectedOrdinalParam ? parseInt(selectedOrdinalParam, 10) : 0;
        const targetPart = partRes.items.find(p => p.ordinal === targetOrdinal) || partRes.items[0];
        if (targetPart) {
          setSelectedPartition(targetPart);
          const auth = await fixtureAdapter.getAuthorityForPartition(targetPart.id, targetPart.ordinal);
          setAuthority(auth);
          try {
            const genRes = await fixtureAdapter.getGenerationsForPartition(targetPart.id);
            setGenerations(genRes.items);
          } catch {
            setGenerations([]);
          }
        }
      } else {
        if (!jobId) throw new Error('Job ID required');
        const jobRes = await liveAdapter.getJob(jobId);
        const partRes = await liveAdapter.getPartitions(jobId, -1, 100, statusFilter === 'ALL' ? undefined : statusFilter);
        const evRes = await liveAdapter.getEvents(jobId);

        setJob(jobRes.data);
        setPartitions(partRes.items);
        setEvents(evRes.items);
        setNextEventCursor(evRes.next_cursor);
        setObservedAt(jobRes.asOf);

        // Select partition
        const targetOrdinal = selectedOrdinalParam ? parseInt(selectedOrdinalParam, 10) : 0;
        const targetPart = partRes.items.find(p => p.ordinal === targetOrdinal) || partRes.items[0];
        if (targetPart) {
          setSelectedPartition(targetPart);
          const auth = liveAdapter.getAuthorityForPartition(targetPart);
          setAuthority(auth);
          // Backend visibility gap: Generation history route does not exist live
          setGenerations([]);
        }
      }
    } catch (err: any) {
      setError({
        status: err.status || 500,
        message: err.message || 'Failed to fetch job record'
      });
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [jobId, isSynthetic, fixtureAdapter, liveAdapter, statusFilter, selectedOrdinalParam]);

  useEffect(() => {
    loadJobData();
  }, [loadJobData]);

  // Load more events forward pagination
  const handleLoadMoreEvents = async () => {
    if (!nextEventCursor || !jobId) return;
    setIsLoadingMoreEvents(true);
    try {
      const evRes = isSynthetic
        ? await fixtureAdapter.getEvents(jobId, nextEventCursor, 100)
        : await liveAdapter.getEvents(jobId, nextEventCursor, 100);
      setEvents(prev => [...prev, ...evRes.items]);
      setNextEventCursor(evRes.next_cursor);
    } catch (err) {
      console.error('Failed to load next event batch', err);
    } finally {
      setIsLoadingMoreEvents(false);
    }
  };

  // Select a partition
  const handleSelectPartition = useCallback(async (part: PartitionItem) => {
    setSelectedPartition(part);
    setIsInspectorOpenMobile(true);
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.set('partition', part.ordinal.toString());
      return next;
    });

    if (isSynthetic) {
      const auth = await fixtureAdapter.getAuthorityForPartition(part.id, part.ordinal);
      setAuthority(auth);
      try {
        const genRes = await fixtureAdapter.getGenerationsForPartition(part.id);
        setGenerations(genRes.items);
      } catch {
        setGenerations([]);
      }
    } else {
      const auth = liveAdapter.getAuthorityForPartition(part);
      setAuthority(auth);
      setGenerations([]);
    }
  }, [isSynthetic, fixtureAdapter, liveAdapter, setSearchParams]);

  if (error) {
    if (error.status === 404) {
      return (
        <CapabilityUnavailable
          type="404"
          title="Job Not Found"
          description={`No recorded job matching ID "${jobId}" was found in this Relay installation.`}
          onRetry={() => loadJobData()}
        />
      );
    }
    if (error.status === 401 || error.status === 403) {
      return (
        <CapabilityUnavailable
          type="401"
          title="Operator Authentication Required (BV10)"
          description="Authenticated live job detail requires the BV10 browser session and authentication adapter. Baseline Relay does not yet expose browser session authentication for operator reads."
          requiredReadContract="GET /v1/jobs/{id}"
          onRetry={() => loadJobData()}
        />
      );
    }
    return (
      <CapabilityUnavailable
        type="503"
        title={`Error Loading Job (${error.status})`}
        description={error.message}
        onRetry={() => loadJobData()}
      />
    );
  }

  if (isLoading && !job) {
    return (
      <div className="space-y-4 max-w-7xl mx-auto" aria-busy="true">
        <div className="h-28 rounded-lg bg-[var(--color-surface-1)] animate-pulse" />
        <div className="h-20 rounded-lg bg-[var(--color-surface-1)] animate-pulse" />
        <div className="h-96 rounded-lg bg-[var(--color-surface-1)] animate-pulse" />
      </div>
    );
  }

  if (!job) {
    return null;
  }

  return (
    <div className="space-y-4 max-w-7xl mx-auto pb-8">
      {/* 1. Header */}
      <JobHeader
        job={job}
        onRefresh={() => loadJobData(true)}
        isRefreshing={isRefreshing}
      />

      {/* 2. Compact Summary Strip */}
      <JobSummaryStrip
        job={job}
        observedAt={observedAt}
      />

      {/* 3. Navigation Tabs */}
      <div className="border-b border-[var(--color-border-subtle)] flex items-center gap-1" role="tablist" aria-label="Job Detail Tabs">
        {(['execution', 'activity', 'results', 'definition'] as ActiveTab[]).map((tab) => {
          const isActive = activeTab === tab;
          const label = tab.charAt(0).toUpperCase() + tab.slice(1);
          return (
            <button
              key={tab}
              role="tab"
              id={`tab-${tab}`}
              aria-selected={isActive}
              aria-controls={`panel-${tab}`}
              onClick={() => handleTabChange(tab)}
              className={`
                px-4 py-2.5 text-xs font-medium border-b-2 transition-colors
                ${isActive
                  ? 'border-[var(--color-execution)] text-[var(--color-execution)] font-semibold'
                  : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:border-[var(--color-border-control)]'
                }
              `}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* 4. Tab Panels */}
      <div className="min-h-[500px]">
        {/* EXECUTION TAB (Default showcase) */}
        {activeTab === 'execution' && (
          <div
            id="panel-execution"
            role="tabpanel"
            aria-labelledby="tab-execution"
            className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start"
          >
            {/* Left: Partition Table (~60% desktop width) */}
            <div className="xl:col-span-7 min-w-0 h-[620px]">
              <PartitionTable
                partitions={partitions}
                selectedPartitionId={selectedPartition?.id || null}
                onSelectPartition={handleSelectPartition}
                statusFilter={statusFilter}
                onChangeStatusFilter={setStatusFilter}
                observedAt={observedAt}
                isLoading={isLoading}
              />
            </div>

            {/* Right: Partition Inspector (~40% desktop width, min 360px) - Persistent side-by-side on desktop >= 1280px */}
            <div className="hidden xl:block xl:col-span-5 min-w-[360px] h-[620px]">
              {selectedPartition ? (
                <PartitionInspector
                  partition={selectedPartition}
                  authority={authority}
                  generations={generations}
                  events={events}
                  observedAt={observedAt}
                  isLoading={isLoading}
                />
              ) : (
                <div className="p-8 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] text-center text-xs text-[var(--color-text-muted)]">
                  Select a partition row to inspect generation history and result authority.
                </div>
              )}
            </div>

            {/* Mobile/Tablet Partition Inspector Drawer (< 1280px) */}
            {isInspectorOpenMobile && selectedPartition && (
              <div
                className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-3 xl:hidden"
                role="dialog"
                aria-modal="true"
                aria-label={`Partition ${selectedPartition.ordinal} Inspector`}
              >
                <div className="w-full max-w-2xl h-[90vh] bg-[var(--color-surface-1)] rounded-lg shadow-2xl overflow-hidden flex flex-col border border-[var(--color-border-control)]">
                  <PartitionInspector
                    partition={selectedPartition}
                    authority={authority}
                    generations={generations}
                    events={events}
                    observedAt={observedAt}
                    onClose={handleCloseInspectorMobile}
                    isLoading={isLoading}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* ACTIVITY TAB */}
        {activeTab === 'activity' && (
          <div id="panel-activity" role="tabpanel" aria-labelledby="tab-activity">
            <EventList
              events={events}
              nextCursor={nextEventCursor}
              onLoadMore={handleLoadMoreEvents}
              isLoadingMore={isLoadingMoreEvents}
              selectedPartitionOrdinal={selectedPartition?.ordinal}
              onSelectPartitionOrdinal={(ord) => {
                const p = partitions.find(item => item.ordinal === ord);
                if (p) handleSelectPartition(p);
                handleTabChange('execution');
              }}
              isLoading={isLoading}
            />
          </div>
        )}

        {/* RESULTS TAB */}
        {activeTab === 'results' && (
          <div id="panel-results" role="tabpanel" aria-labelledby="tab-results">
            <ResultsTab job={job} />
          </div>
        )}

        {/* DEFINITION TAB */}
        {activeTab === 'definition' && (
          <div id="panel-definition" role="tabpanel" aria-labelledby="tab-definition">
            <DefinitionTab job={job} />
          </div>
        )}
      </div>
    </div>
  );
};
