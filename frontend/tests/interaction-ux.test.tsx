import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { RelayProvider, useRelay } from '../src/context/RelayContext';
import { Header } from '../src/components/layout/Header';
import { SyntheticBanner } from '../src/components/common/SyntheticBanner';
import { PartitionTable } from '../src/components/job/PartitionTable';
import { CopyField } from '../src/components/common/CopyField';
import { SCENARIO_NORMAL_PARTITIONS, FIXTURE_OBSERVATION_TIME } from '../src/fixtures/scenarios';

describe('Relay Interaction, Accessibility and UX Behavior', () => {
  // Test 9: disconnected mode retains last-known observation
  it('9. disconnected mode retains last-known observation', () => {
    const TestComponent = () => {
      const { setConnectionStatus } = useRelay();
      return (
        <div>
          <button 
            onClick={() => setConnectionStatus({
              isLive: true,
              isSynthetic: false,
              apiReachable: false,
              readinessPassed: null,
              lastObservedAt: '2026-10-03T01:58:30.000Z',
              error: 'Disconnected from cluster'
            })}
          >
            Simulate Disconnect
          </button>
          <Header />
        </div>
      );
    };

    render(
      <MemoryRouter>
        <RelayProvider defaultSynthetic={false}>
          <TestComponent />
        </RelayProvider>
      </MemoryRouter>
    );

    // Click simulate disconnect
    fireEvent.click(screen.getByText('Simulate Disconnect'));

    // Verify API is marked Unreachable
    expect(screen.getByText('Unreachable')).toBeInTheDocument();
    // Verify last-known observation timestamp is retained and visible
    expect(screen.getByText(/01:58:30Z/)).toBeInTheDocument();
  });

  // Test 10: unknown differs from zero
  it('10. unknown differs from zero', () => {
    // In Header, when readiness is null/unknown, render "Unknown", NOT 0
    render(
      <MemoryRouter>
        <RelayProvider defaultSynthetic={false}>
          <Header />
        </RelayProvider>
      </MemoryRouter>
    );

    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  // Test 11: selected row styling differs from accepted authority styling
  it('11. selected row styling differs from accepted authority styling', () => {
    const onSelect = vi.fn();
    const { container } = render(
      <PartitionTable
        partitions={SCENARIO_NORMAL_PARTITIONS}
        selectedPartitionId={SCENARIO_NORMAL_PARTITIONS[1].id}
        onSelectPartition={onSelect}
        statusFilter="ALL"
        onChangeStatusFilter={() => {}}
        observedAt={FIXTURE_OBSERVATION_TIME}
      />
    );

    // Selected row must have .row-selected (blue execution accent)
    const selectedRow = container.querySelector('.row-selected');
    expect(selectedRow).not.toBeNull();
    // It must NOT have .authority-rail-accepted
    expect(selectedRow?.classList.contains('authority-rail-accepted')).toBe(false);
  });

  // Test 12: keyboard can select/inspect partition
  it('12. keyboard can select/inspect partition', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    render(
      <PartitionTable
        partitions={SCENARIO_NORMAL_PARTITIONS}
        selectedPartitionId={null}
        onSelectPartition={onSelect}
        statusFilter="ALL"
        onChangeStatusFilter={() => {}}
        observedAt={FIXTURE_OBSERVATION_TIME}
      />
    );

    const firstRow = screen.getByText('Partition 0').closest('tr')!;
    firstRow.focus();
    expect(firstRow).toHaveFocus();

    // Press Enter to select
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith(SCENARIO_NORMAL_PARTITIONS[0]);

    // Press Space on second row
    const secondRow = screen.getByText('Partition 1').closest('tr')!;
    secondRow.focus();
    await user.keyboard(' ');
    expect(onSelect).toHaveBeenCalledWith(SCENARIO_NORMAL_PARTITIONS[1]);
  });

  // Test 13: fixture mode displays: SYNTHETIC DEMO DATA
  it('13. fixture mode displays: SYNTHETIC DEMO DATA', () => {
    render(
      <RelayProvider defaultSynthetic={true}>
        <SyntheticBanner />
      </RelayProvider>
    );

    expect(screen.getByText('SYNTHETIC DEMO DATA')).toBeInTheDocument();
  });

  // Test 14: network failure does NOT automatically switch to fixture mode
  it('14. network failure does NOT automatically switch to fixture mode', () => {
    const TestConsumer = () => {
      const { isSynthetic, setConnectionStatus } = useRelay();
      return (
        <div>
          <span data-testid="mode">{isSynthetic ? 'SYNTHETIC' : 'LIVE'}</span>
          <button 
            onClick={() => {
              // Simulated 503 network failure
              setConnectionStatus({
                isLive: true,
                isSynthetic: false,
                apiReachable: false,
                readinessPassed: false,
                lastObservedAt: '2026-10-03T02:00:00Z',
                error: '503 Service Unavailable'
              });
            }}
          >
            Trigger Network Error
          </button>
        </div>
      );
    };

    render(
      <RelayProvider defaultSynthetic={false}>
        <TestConsumer />
      </RelayProvider>
    );

    expect(screen.getByTestId('mode')).toHaveTextContent('LIVE');

    fireEvent.click(screen.getByText('Trigger Network Error'));

    // INVARIANT: Mode MUST still be LIVE. Silent fallback is prohibited!
    expect(screen.getByTestId('mode')).toHaveTextContent('LIVE');
    expect(screen.queryByText('SYNTHETIC DEMO DATA')).not.toBeInTheDocument();
  });

  // Test 16: IDs copied exactly
  it('16. IDs copied exactly', async () => {
    const testUUID = '11111111-2222-4333-8444-555555555555';
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: writeTextMock,
      },
      writable: true,
      configurable: true,
    });

    render(<CopyField value={testUUID} label="Partition ID" shorten truncateLength={6} />);

    // Click copy button
    const copyBtn = screen.getByRole('button', { name: /Copy Partition ID/i });
    await userEvent.click(copyBtn);

    // Exact full string must have been passed to clipboard
    expect(writeTextMock).toHaveBeenCalledWith(testUUID);
  });
});
