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
  JOB_ID_FAILED_WITH_PARTIAL,
  JOB_ID_RUNNING_WITH_FAILURE,
  PARTITION_0_ID,
  PARTITION_1_ID,
  PARTITION_2_ID,
  PARTITION_3_ID,
  SCENARIO_NORMAL_JOB,
  SCENARIO_NORMAL_PARTITIONS,
  SCENARIO_NORMAL_EVENTS,
  SCENARIO_A_GENERATIONS,
  SCENARIO_A_AUTHORITY,
  SCENARIO_B_GENERATIONS,
  SCENARIO_B_AUTHORITY,
  SCENARIO_C_JOB,
  SCENARIO_D_JOB,
  SCENARIO_E_AUTHORITY,
  SCENARIO_F_AUTHORITY,
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
    if (this.activeScenario === 'SCENARIO_D_FAILED_WITH_PARTIAL' || id === JOB_ID_FAILED_WITH_PARTIAL) {
      job = SCENARIO_D_JOB;
    } else if (this.activeScenario === 'SCENARIO_C_RUNNING_WITH_FAILURE' || id === JOB_ID_RUNNING_WITH_FAILURE) {
      job = SCENARIO_C_JOB;
    } else {
      job = SCENARIO_NORMAL_JOB;
    }
    return { data: job, asOf: FIXTURE_OBSERVATION_TIME };
  }

  async getPartitions(
    _jobId: string, 
    _afterOrdinal = -1, 
    _limit = 100, 
    status?: string
  ): Promise<{ items: PartitionItem[]; next_cursor: number | null; asOf: string }> {
    let items = [...SCENARIO_NORMAL_PARTITIONS];
    if (status) {
      items = items.filter(p => p.status === status);
    }
    return {
      items,
      next_cursor: null,
      asOf: FIXTURE_OBSERVATION_TIME,
    };
  }

  async getGenerationsForPartition(partitionId: string): Promise<{ items: GenerationDetail[]; asOf: string }> {
    if (this.activeScenario === 'SCENARIO_H_CAPABILITY_GAP') {
      throw new Error('CAPABILITY_GAP: BV03_PARTITION_HISTORY');
    }
    if (partitionId === PARTITION_0_ID || this.activeScenario === 'SCENARIO_A_STALE_REJECTION') {
      return { items: SCENARIO_A_GENERATIONS, asOf: FIXTURE_OBSERVATION_TIME };
    }
    if (partitionId === PARTITION_1_ID || this.activeScenario === 'SCENARIO_B_DEADLINE_PASSED') {
      return { items: SCENARIO_B_GENERATIONS, asOf: FIXTURE_OBSERVATION_TIME };
    }
    return { items: [], asOf: FIXTURE_OBSERVATION_TIME };
  }

  async getAuthorityForPartition(partitionId: string, ordinal = 0): Promise<AuthorityState> {
    if (this.activeScenario === 'SCENARIO_F_INTEGRITY_FAILURE' || partitionId === PARTITION_3_ID) {
      return SCENARIO_F_AUTHORITY;
    }
    if (this.activeScenario === 'SCENARIO_E_NO_ACCEPTED_RESULT' || partitionId === PARTITION_2_ID) {
      return SCENARIO_E_AUTHORITY;
    }
    if (this.activeScenario === 'SCENARIO_B_DEADLINE_PASSED' || partitionId === PARTITION_1_ID) {
      return SCENARIO_B_AUTHORITY;
    }
    if (partitionId === PARTITION_0_ID || this.activeScenario === 'SCENARIO_A_STALE_REJECTION' || this.activeScenario === 'NORMAL') {
      return SCENARIO_A_AUTHORITY;
    }
    return {
      status: 'NONE',
      partition_id: partitionId,
      partition_ordinal: ordinal,
    };
  }

  async getEvents(_jobId: string, _afterSeq = '0', _limit = 100): Promise<{ items: RelayEvent[]; next_cursor: string | null; asOf: string }> {
    return {
      items: SCENARIO_NORMAL_EVENTS,
      next_cursor: null,
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
