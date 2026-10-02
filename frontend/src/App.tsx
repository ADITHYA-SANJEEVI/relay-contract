import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { OverviewView } from './views/OverviewView';
import { JobsListView } from './views/JobsListView';
import { JobDetailView } from './views/JobDetailView';
import { WorkersView } from './views/WorkersView';
import { FailureLabView } from './views/FailureLabView';
import { EvidenceView } from './views/EvidenceView';

export const App: React.FC = () => {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/board" replace />} />
      <Route path="/board" element={<AppShell />}>
        <Route index element={<OverviewView />} />
        <Route path="jobs" element={<JobsListView />} />
        <Route path="jobs/:jobId" element={<JobDetailView />} />
        <Route path="workers" element={<WorkersView />} />
        <Route path="lab" element={<FailureLabView />} />
        <Route path="evidence" element={<EvidenceView />} />
        {/* Fallback to Overview */}
        <Route path="*" element={<Navigate to="/board" replace />} />
      </Route>
    </Routes>
  );
};
