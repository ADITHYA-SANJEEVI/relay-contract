import {
  JobSummary,
  PartitionItem,
  GenerationDetail,
  AuthorityState,
  RelayEvent,
  WorkerSession,
  ConnectionStatus,
  CapabilityState
} from '../types/domain';
import {
  FIXTURE_OBSERVATION_TIME,
  JOB_ID_NORMAL,
  JOB_ID_FAILED_WITH_PARTIAL,
  JOB_ID_RUNNING_WITH_FAILURE,
  PARTITION_0_ID,
  PARTITION_1_ID,
  PARTITION_2_ID,
  PARTITION_3_ID,
  SCENARIO_NORMAL_JOB,
  SCENARIO_NORMAL_PARTITIONS,
  SCENARIO_NORMAL_EVENTS,
  SCENARIO_C_PARTITIONS,
  SCENARIO_C_EVENTS,
  SCENARIO_D_PARTITIONS,
  SCENARIO_D_EVENTS,
  SCENARIO_A_GENERATIONS,
  SCENARIO_A_AUTHORITY,
  SCENARIO_B_GENERATIONS,
  SCENARIO_B_AUTHORITY,
  SCENARIO_C_JOB,
  SCENARIO_D_JOB,
  SCENARIO_E_AUTHORITY,
  SCENARIO_F_AUTHORITY,
  SCENARIO_F_PARTITIONS,
  SCENARIO_G_CONNECTION,
  SCENARIO_H_CAPABILITY,
  SCENARIO_WORKERS
} from '../fixtures/scenarios';

export type ScenarioKey =
  | 'NORMAL'
  | 'SCENARIO_A_STALE_REJECTION'
  | 'SCENARIO_B_DEADLINE_PASSED'
  | 'SCENARIO_C_RUNNING_WITH_FAILURE'
  | 'SCENARIO_D_FAILED_WITH_PARTIAL'
  | 'SCENARIO_E_NO_ACCEPTED_RESULT'
  | 'SCENARIO_F_INTEGRITY_FAILURE'
  | 'SCENARIO_G_DISCONNECTED'
  | 'SCENARIO_H_CAPABILITY_GAP';

export class FixtureDataAdapter {
  private activeScenario: ScenarioKey = 'NORMAL';

  setScenario(scenario: ScenarioKey) {
    this.activeScenario = scenario;
  }

  getScenario(): ScenarioKey {
    return this.activeScenario;
  }

  async checkHealth(): Promise<ConnectionStatus> {
    if (this.activeScenario === 'SCENARIO_G_DISCONNECTED') {
      return SCENARIO_G_CONNECTION;
    }
    return {
      isLive: false,
      isSynthetic: true,
      apiReachable: true,
      readinessPassed: true,
      dbRevision: '0002_readiness (synthetic)',
      lastObservedAt: FIXTURE_OBSERVATION_TIME,
    };
  }

  async getJob(id?: string): Promise<{ data: JobSummary; asOf: string }> {
    let job: JobSummary;
    if (id === JOB_ID_FAILED_WITH_PARTIAL || (!id && this.activeScenario === 'SCENARIO_D_FAILED_WITH_PARTIAL')) {
      job = SCENARIO_D_JOB;
    } else if (id === JOB_ID_RUNNING_WITH_FAILURE || (!id && this.activeScenario === 'SCENARIO_C_RUNNING_WITH_FAILURE')) {
      job = SCENARIO_C_JOB;
    } else if (!id || id === JOB_ID_NORMAL) {
      job = SCENARIO_NORMAL_JOB;
    } else {
      const err = new Error(`Job "${id}" not found in synthetic repository.`);
      (err as any).status = 404;
      (err as any).code = 'not_found';
      throw err;
    }
    return { data: job, asOf: FIXTURE_OBSERVATION_TIME };
  }

  async getPartitions(
    jobId: string,
    afterOrdinal = -1,
    limit = 100,
    status?: string
  ): Promise<{ items: PartitionItem[]; next_cursor: number | null; asOf: string }> {
    let baseItems: PartitionItem[];
    if (this.activeScenario === 'SCENARIO_F_INTEGRITY_FAILURE') {
      baseItems = SCENARIO_F_PARTITIONS;
    } else if (jobId === JOB_ID_FAILED_WITH_PARTIAL || (!jobId && this.activeScenario === 'SCENARIO_D_FAILED_WITH_PARTIAL')) {
      baseItems = SCENARIO_D_PARTITIONS;
    } else if (jobId === JOB_ID_RUNNING_WITH_FAILURE || (!jobId && this.activeScenario === 'SCENARIO_C_RUNNING_WITH_FAILURE')) {
      baseItems = SCENARIO_C_PARTITIONS;
    } else if (!jobId || jobId === JOB_ID_NORMAL) {
      baseItems = SCENARIO_NORMAL_PARTITIONS;
    } else {
      const err = new Error(`Job "${jobId}" not found in synthetic repository.`);
      (err as any).status = 404;
      throw err;
    }

    let items = baseItems.filter(p => p.ordinal > afterOrdinal);
    if (status) {
      items = items.filter(p => p.status === status);
    }
    const pageItems = items.slice(0, limit);
    const nextCursor = items.length > limit ? pageItems[pageItems.length - 1].ordinal : null;

    return {
      items: pageItems,
      next_cursor: nextCursor,
      asOf: FIXTURE_OBSERVATION_TIME,
    };
  }

  async getGenerationsForPartition(partitionId: string): Promise<{ items: GenerationDetail[]; asOf: string }> {
    if (this.activeScenario === 'SCENARIO_H_CAPABILITY_GAP') {
      throw new Error('CAPABILITY_GAP: BV03_PARTITION_HISTORY');
    }
    let rawItems: GenerationDetail[] = [];
    if (partitionId === PARTITION_0_ID || this.activeScenario === 'SCENARIO_A_STALE_REJECTION') {
      rawItems = SCENARIO_A_GENERATIONS;
    } else if (partitionId === PARTITION_1_ID || this.activeScenario === 'SCENARIO_B_DEADLINE_PASSED') {
      rawItems = SCENARIO_B_GENERATIONS;
    }

    // Bind partition identity to selected partition
    const items = rawItems.map(g => ({
      ...g,
      partition_id: partitionId,
    }));

    return { items, asOf: FIXTURE_OBSERVATION_TIME };
  }

  async getAuthorityForPartition(partitionId: string, ordinal = 0): Promise<AuthorityState> {
    let baseAuth: AuthorityState;
    if (this.activeScenario === 'SCENARIO_F_INTEGRITY_FAILURE') {
      baseAuth = SCENARIO_F_AUTHORITY;
    } else if (this.activeScenario === 'SCENARIO_E_NO_ACCEPTED_RESULT' || partitionId === PARTITION_2_ID) {
      baseAuth = SCENARIO_E_AUTHORITY;
    } else if (this.activeScenario === 'SCENARIO_B_DEADLINE_PASSED' || partitionId === PARTITION_1_ID) {
      baseAuth = SCENARIO_B_AUTHORITY;
    } else if (partitionId === PARTITION_3_ID) {
      baseAuth = {
        status: 'NONE',
        partition_id: partitionId,
        partition_ordinal: ordinal,
      };
    } else {
      baseAuth = SCENARIO_A_AUTHORITY;
    }

    return {
      ...baseAuth,
      partition_id: partitionId,
      partition_ordinal: ordinal,
    };
  }

  async getEvents(jobId: string, afterSeq = '0', limit = 100): Promise<{ items: RelayEvent[]; next_cursor: string | null; asOf: string }> {
    let baseEvents: RelayEvent[];
    if (jobId === JOB_ID_FAILED_WITH_PARTIAL || (!jobId && this.activeScenario === 'SCENARIO_D_FAILED_WITH_PARTIAL')) {
      baseEvents = SCENARIO_D_EVENTS;
    } else if (jobId === JOB_ID_RUNNING_WITH_FAILURE || (!jobId && this.activeScenario === 'SCENARIO_C_RUNNING_WITH_FAILURE')) {
      baseEvents = SCENARIO_C_EVENTS;
    } else if (!jobId || jobId === JOB_ID_NORMAL) {
      baseEvents = SCENARIO_NORMAL_EVENTS;
    } else {
      const err = new Error(`Job "${jobId}" not found in synthetic repository.`);
      (err as any).status = 404;
      throw err;
    }

    const afterSeqBig = BigInt(afterSeq || '0');
    const filtered = baseEvents.filter(e => BigInt(e.seq) > afterSeqBig);
    const items = filtered.slice(0, limit);
    const nextCursor = filtered.length > limit ? items[items.length - 1].seq : null;

    return {
      items,
      next_cursor: nextCursor,
      asOf: FIXTURE_OBSERVATION_TIME,
    };
  }

  async getWorkers(): Promise<{ items: WorkerSession[]; asOf: string }> {
    return {
      items: SCENARIO_WORKERS,
      asOf: FIXTURE_OBSERVATION_TIME,
    };
  }

  getCapabilityGap(code: string): CapabilityState {
    if (code === 'BV03_PARTITION_HISTORY') {
      return SCENARIO_H_CAPABILITY;
    }
    return {
      code,
      title: 'Capability Unavailable',
      description: 'The requested operation or observation is not supported by the connected backend.',
      requiredReadContract: 'N/A',
      isGap: true,
    };
  }
}
