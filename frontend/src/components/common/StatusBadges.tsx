import React from 'react';
import { 
  JobStatus, 
  PartitionStatus, 
  AttemptStatus, 
  ArtifactStatus, 
  PublicationStatus, 
  WorkerLivenessState 
} from '../../types/domain';
import { 
  CheckCircle2, 
  Clock, 
  Activity, 
  AlertOctagon, 
  MinusCircle, 
  HelpCircle,
  FileCheck,
  FileX,
  FileClock,
  AlertTriangle
} from 'lucide-react';

export const RecordedStatusBadge: React.FC<{
  status: JobStatus | PartitionStatus | AttemptStatus | string;
  type?: 'job' | 'partition' | 'attempt';
}> = ({ status, type = 'job' }) => {
  const normalized = status.toUpperCase();

  switch (normalized) {
    case 'SUCCEEDED':
      return (
        <span className="badge badge-accepted" role="status">
          <CheckCircle2 size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>{type === 'partition' ? 'Accepted result' : 'SUCCEEDED'}</span>
        </span>
      );
    case 'RUNNING':
      return (
        <span className="badge badge-execution" role="status">
          <Activity size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>RUNNING</span>
        </span>
      );
    case 'ACTIVE':
      return (
        <span className="badge badge-execution" role="status">
          <Activity size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>ACTIVE</span>
        </span>
      );
    case 'READY':
      return (
        <span className="badge badge-neutral" role="status">
          <Clock size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>READY</span>
        </span>
      );
    case 'QUEUED':
      return (
        <span className="badge badge-neutral" role="status">
          <Clock size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>QUEUED</span>
        </span>
      );
    case 'EXPIRED':
      return (
        <span className="badge badge-attention" role="status">
          <Clock size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>EXPIRED</span>
        </span>
      );
    case 'FAILED':
      return (
        <span className="badge badge-failure" role="status">
          <AlertOctagon size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>FAILED</span>
        </span>
      );
    case 'CANCELLED':
      return (
        <span className="badge badge-neutral" role="status">
          <MinusCircle size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>CANCELLED</span>
        </span>
      );
    default:
      return (
        <span className="badge badge-neutral" role="status">
          <HelpCircle size={12} aria-hidden="true" />
          <span className="sr-only">Recorded {type} status:</span>
          <span>Unsupported / unknown state ({status})</span>
        </span>
      );
  }
};

export const ObservationBadge: React.FC<{
  isDeadlinePassed?: boolean;
  attemptStatus?: AttemptStatus;
  liveness?: WorkerLivenessState;
}> = ({ isDeadlinePassed, attemptStatus, liveness }) => {
  if (isDeadlinePassed && attemptStatus === 'ACTIVE') {
    return (
      <span className="badge badge-attention" title="Observation: Lease/deadline elapsed in browser clock; awaiting durable backend settlement">
        <AlertTriangle size={12} aria-hidden="true" />
        <span className="sr-only">Observation:</span>
        <span>Deadline passed · awaiting settlement</span>
      </span>
    );
  }

  if (liveness === 'FRESH') {
    return (
      <span className="badge badge-execution" title="Heartbeat observed within last 30 seconds">
        <Activity size={12} aria-hidden="true" />
        <span className="sr-only">Observation:</span>
        <span>FRESH</span>
      </span>
    );
  }

  if (liveness === 'SUSPECT') {
    return (
      <span className="badge badge-attention" title="Heartbeat delayed >30 seconds. Suspect observation; not a confirmed crash.">
        <AlertTriangle size={12} aria-hidden="true" />
        <span className="sr-only">Observation:</span>
        <span>SUSPECT</span>
      </span>
    );
  }

  if (liveness === 'NOT_APPLICABLE') {
    return (
      <span className="badge badge-neutral" title="Worker is stopped; liveness not applicable">
        <span className="sr-only">Observation:</span>
        <span>Liveness not applicable</span>
      </span>
    );
  }

  return null;
};

export const ArtifactStatusBadge: React.FC<{ status: ArtifactStatus }> = ({ status }) => {
  switch (status) {
    case 'VERIFIED':
      return (
        <span className="badge badge-verified" title="Artifact bytes and schema verified against hash and spec">
          <FileCheck size={12} aria-hidden="true" />
          <span className="sr-only">Artifact state:</span>
          <span>VERIFIED</span>
        </span>
      );
    case 'RESERVED':
      return (
        <span className="badge badge-neutral" title="Artifact reservation created; payload pending verification">
          <FileClock size={12} aria-hidden="true" />
          <span className="sr-only">Artifact state:</span>
          <span>RESERVED</span>
        </span>
      );
    case 'REJECTED':
      return (
        <span className="badge badge-failure" title="Artifact bytes or schema rejected by validation gate">
          <FileX size={12} aria-hidden="true" />
          <span className="sr-only">Artifact state:</span>
          <span>REJECTED</span>
        </span>
      );
    case 'UNAVAILABLE':
    default:
      return (
        <span className="badge badge-neutral" title="Artifact metadata not available">
          <HelpCircle size={12} aria-hidden="true" />
          <span className="sr-only">Artifact state:</span>
          <span>Unavailable</span>
        </span>
      );
  }
};

export const PublicationStatusBadge: React.FC<{ 
  status: PublicationStatus;
  rejectionReason?: string;
}> = ({ status, rejectionReason }) => {
  switch (status) {
    case 'ACCEPTED':
      return (
        <span className="badge badge-accepted" title="Committed accepted result relation for partition">
          <CheckCircle2 size={12} aria-hidden="true" />
          <span className="sr-only">Publication status:</span>
          <span>ACCEPTED · authoritative</span>
        </span>
      );
    case 'REJECTED_STALE_GENERATION':
      return (
        <span className="badge badge-failure" title="Publication rejected: attempt finished after newer generation claimed or superseded">
          <AlertOctagon size={12} aria-hidden="true" />
          <span className="sr-only">Publication status:</span>
          <span>REJECTED · stale_generation</span>
        </span>
      );
    case 'REJECTED_KNOWN_CODE':
      return (
        <span className="badge badge-failure" title={`Publication rejected: ${rejectionReason || 'known code'}`}>
          <AlertOctagon size={12} aria-hidden="true" />
          <span className="sr-only">Publication status:</span>
          <span>REJECTED · {rejectionReason || 'known_code'}</span>
        </span>
      );
    case 'NO_ACCEPTANCE_OBSERVED':
      return (
        <span className="badge badge-neutral" title="No publication acceptance observed for this generation">
          <span className="sr-only">Publication status:</span>
          <span>No acceptance observed</span>
        </span>
      );
    case 'UNKNOWN':
    default:
      return (
        <span className="badge badge-neutral" title="Publication state unknown or not exposed">
          <HelpCircle size={12} aria-hidden="true" />
          <span className="sr-only">Publication status:</span>
          <span>Unknown</span>
        </span>
      );
  }
};
