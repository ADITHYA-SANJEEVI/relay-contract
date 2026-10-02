import React, { createContext, useContext, useState, useMemo, useCallback } from 'react';
import { LiveDataAdapter } from '../api/liveAdapter';
import { FixtureDataAdapter, ScenarioKey } from '../api/fixtureAdapter';
import { ConnectionStatus } from '../types/domain';

interface RelayContextValue {
  isSynthetic: boolean;
  setSyntheticMode: (enabled: boolean) => void;
  activeScenario: ScenarioKey;
  setScenario: (scenario: ScenarioKey) => void;
  token: string | null;
  setToken: (token: string | null) => void;
  liveAdapter: LiveDataAdapter;
  fixtureAdapter: FixtureDataAdapter;
  connectionStatus: ConnectionStatus;
  setConnectionStatus: React.Dispatch<React.SetStateAction<ConnectionStatus>>;
  refreshHealth: () => Promise<void>;
}

const RelayContext = createContext<RelayContextValue | null>(null);

export const RelayProvider: React.FC<{ children: React.ReactNode; defaultSynthetic?: boolean }> = ({ 
  children, 
  defaultSynthetic = true // Defaults to synthetic demo until operator explicitly enters token/live mode
}) => {
  const [isSynthetic, setIsSynthetic] = useState<boolean>(defaultSynthetic);
  const [activeScenario, setActiveScenarioState] = useState<ScenarioKey>('NORMAL');
  const [token, setTokenState] = useState<string | null>(null);

  const liveAdapter = useMemo(() => new LiveDataAdapter(token || undefined), [token]);
  const fixtureAdapter = useMemo(() => new FixtureDataAdapter(), []);

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    isLive: !defaultSynthetic,
    isSynthetic: defaultSynthetic,
    apiReachable: true,
    readinessPassed: true,
    dbRevision: defaultSynthetic ? '0002_readiness (synthetic)' : undefined,
    lastObservedAt: new Date().toISOString(),
  });

  const setScenario = useCallback((scenario: ScenarioKey) => {
    setActiveScenarioState(scenario);
    fixtureAdapter.setScenario(scenario);
    if (scenario === 'SCENARIO_G_DISCONNECTED') {
      setConnectionStatus({
        isLive: true,
        isSynthetic: false,
        apiReachable: false,
        readinessPassed: null,
        lastObservedAt: '2026-10-03T01:58:30.000Z',
        error: 'Connection refused: http://localhost:8000 (retaining last-known observation)',
        errorCode: 'network_error',
        statusCode: 0
      });
    }
  }, [fixtureAdapter]);

  const setSyntheticMode = useCallback((enabled: boolean) => {
    // Explicit selection only. Live errors NEVER flip this boolean automatically.
    setIsSynthetic(enabled);
    if (enabled) {
      setConnectionStatus({
        isLive: false,
        isSynthetic: true,
        apiReachable: true,
        readinessPassed: true,
        dbRevision: '0002_readiness (synthetic)',
        lastObservedAt: new Date().toISOString(),
      });
    }
  }, []);

  const setToken = useCallback((newToken: string | null) => {
    setTokenState(newToken);
    liveAdapter.setToken(newToken);
  }, [liveAdapter]);

  const refreshHealth = useCallback(async () => {
    if (isSynthetic) {
      const status = await fixtureAdapter.checkHealth();
      setConnectionStatus(status);
    } else {
      const status = await liveAdapter.checkHealth();
      setConnectionStatus(status);
    }
  }, [isSynthetic, fixtureAdapter, liveAdapter]);

  const value = useMemo(() => ({
    isSynthetic,
    setSyntheticMode,
    activeScenario,
    setScenario,
    token,
    setToken,
    liveAdapter,
    fixtureAdapter,
    connectionStatus,
    setConnectionStatus,
    refreshHealth
  }), [
    isSynthetic, 
    setSyntheticMode, 
    activeScenario, 
    setScenario, 
    token, 
    setToken, 
    liveAdapter, 
    fixtureAdapter, 
    connectionStatus, 
    refreshHealth
  ]);

  return <RelayContext.Provider value={value}>{children}</RelayContext.Provider>;
};

export function useRelay(): RelayContextValue {
  const ctx = useContext(RelayContext);
  if (!ctx) {
    throw new Error('useRelay must be used within a RelayProvider');
  }
  return ctx;
}
