import { relayFetch } from './client';
import { 
  JobSummary, 
  PartitionItem, 
  RelayEvent, 
  ConnectionStatus,
  AuthorityState,
  CapabilityState 
} from '../types/domain';

export class LiveDataAdapter {
  private baseUrl = '';
  private token: string | null = null;

  constructor(token?: string, baseUrl = '') {
    this.token = token || null;
    this.baseUrl = baseUrl;
  }

  setToken(token: string | null) {
    this.token = token;
  }

  async checkHealth(): Promise<ConnectionStatus> {
    const asOf = new Date().toISOString();
    try {
      const liveRes = await relayFetch<{ live: boolean }>(`${this.baseUrl}/health/live`);
      let readyRes: { ready: boolean; migration_revision?: string } | null = null;
      try {
        const readyData = await relayFetch<{ ready: boolean; migration_revision?: string }>(`${this.baseUrl}/health/ready`);
        readyRes = readyData.data;
      } catch {
        // Readiness can be degraded while API process is live
        readyRes = null;
      }

      return {
        isLive: true,
        isSynthetic: false,
        apiReachable: liveRes.data.live,
        readinessPassed: readyRes?.ready ?? false,
        dbRevision: readyRes?.migration_revision,
        lastObservedAt: asOf,
      };
    } catch (err: any) {
      return {
        isLive: true,
        isSynthetic: false,
        apiReachable: false,
        readinessPassed: null,
        lastObservedAt: asOf,
        error: err.message || 'API unreachable',
        errorCode: err.code || 'unreachable',
        statusCode: err.status || 0,
      };
    }
  }

  async getJob(id: string): Promise<{ data: JobSummary; asOf: string }> {
    const res = await relayFetch<JobSummary>(`${this.baseUrl}/v1/jobs/${id}`, {
      token: this.token || undefined,
    });
    return { data: res.data, asOf: res.asOf };
  }

  async getPartitions(
    jobId: string, 
    afterOrdinal = -1, 
    limit = 100, 
    status?: string
  ): Promise<{ items: PartitionItem[]; next_cursor: number | null; asOf: string }> {
    const params = new URLSearchParams({
      after_ordinal: afterOrdinal.toString(),
      limit: limit.toString(),
    });
    if (status) {
      params.set('status', status);
    }

    const res = await relayFetch<{ items: PartitionItem[]; next_cursor: number | null }>(
      `${this.baseUrl}/v1/jobs/${jobId}/partitions?${params.toString()}`,
      { token: this.token || undefined }
    );
    return { ...res.data, asOf: res.asOf };
  }

  async getEvents(
    jobId: string, 
    afterSeq = '0', 
    limit = 100
  ): Promise<{ items: RelayEvent[]; next_cursor: string | null; asOf: string }> {
    const params = new URLSearchParams({
      after_seq: afterSeq,
      limit: limit.toString(),
    });

    const res = await relayFetch<{ items: RelayEvent[]; next_cursor: string | null }>(
      `${this.baseUrl}/v1/jobs/${jobId}/events?${params.toString()}`,
      { token: this.token || undefined }
    );
    return { ...res.data, asOf: res.asOf };
  }

  async getResults(
    jobId: string, 
    afterOrdinal = -1, 
    limit = 100
  ): Promise<{
    job_id: string;
    job_status: string;
    complete: boolean;
    partial_result_count: string;
    partition_count: string;
    items: Array<any>;
    next_cursor: number | null;
    asOf: string;
  }> {
    const params = new URLSearchParams({
      after_ordinal: afterOrdinal.toString(),
      limit: limit.toString(),
    });

    const res = await relayFetch<any>(
      `${this.baseUrl}/v1/jobs/${jobId}/results?${params.toString()}`,
      { token: this.token || undefined }
    );
    return { ...res.data, asOf: res.asOf };
  }

  /**
   * The following endpoints are documented as BACKEND VISIBILITY GAPS.
   * They must NOT be guessed or faked; they return honest capability gap explanations.
   */
  getPartitionHistoryGap(): CapabilityState {
    return {
      code: 'BV03_PARTITION_HISTORY',
      title: 'Complete Partition Attempt History',
      description: 'Historical attempts, worker session bindings, and non-authoritative artifacts for this partition are not exposed by the current baseline read contract.',
      requiredReadContract: 'GET /v1/operator/partitions/{id}',
      isGap: true,
    };
  }

  getJobsCatalogueGap(): CapabilityState {
    return {
      code: 'BV01_JOBS_CATALOGUE',
      title: 'Global Jobs Catalogue',
      description: 'A global listing of jobs across the installation is not exposed by the current baseline backend. Jobs can be inspected by explicit Job ID.',
      requiredReadContract: 'GET /v1/operator/jobs',
      isGap: true,
    };
  }

  getFleetGap(): CapabilityState {
    return {
      code: 'BV07_FLEET_HISTORY',
      title: 'Worker Fleet and Session History',
      description: 'Worker fleet listing, registration sessions, and heartbeat observations are not exposed via an operator read route. Worker-self endpoints require worker secrets and cannot be called from the browser.',
      requiredReadContract: 'GET /v1/operator/workers',
      isGap: true,
    };
  }

  getAuthorityForPartition(partition: PartitionItem): AuthorityState {
    if (partition.accepted_artifact_id) {
      return {
        status: 'ACCEPTED',
        partition_id: partition.id,
        partition_ordinal: partition.ordinal,
        artifact_id: partition.accepted_artifact_id,
        generation: partition.accepted_generation || undefined,
        attempt_id: partition.attempt_id || undefined,
      };
    }
    return {
      status: 'NONE',
      partition_id: partition.id,
      partition_ordinal: partition.ordinal,
    };
  }
}
