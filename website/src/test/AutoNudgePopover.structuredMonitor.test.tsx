import { type ComponentProps } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AutoNudgePopover, { type AutoNudgeLoop } from '../components/AutoNudgePopover'
import { isReducedMonitorRow } from '../components/autoNudgeLoop'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function renderPopover(props: Partial<ComponentProps<typeof AutoNudgePopover>>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <AutoNudgePopover
        slotKey="chat-1"
        loop={null}
        open={true}
        onChange={() => {}}
        onOpenChange={() => {}}
        {...props}
      />
    </QueryClientProvider>,
  )
}

it('detects reduced monitor transport shapes', () => {
  const plain: AutoNudgeLoop = {
    id: 'plain', slot_key: 'chat-1', message: 'goal', active: true,
    idle_secs: 60, max_cycles: 24, cycle_count: 0, last_fire_ts: 0, next_due_ts: 0,
  }
  const restReduced = { ...plain, message: undefined }
  const websocketReduced = { ...plain, monitor: { agent_turns: 3, budgets: { max_agent_turns: 8 } } }

  expect(isReducedMonitorRow(plain)).toBe(false)
  expect(isReducedMonitorRow(restReduced)).toBe(true)
  expect(isReducedMonitorRow(websocketReduced)).toBe(true)
})

it('limits a reduced active monitor to its supported stop action', () => {
  const reduced: AutoNudgeLoop = {
    id: 'monitor-1', slot_key: 'chat-1', active: true,
    idle_secs: 300, max_cycles: 8, cycle_count: 2,
    last_fire_ts: 0, next_due_ts: 0,
  }

  renderPopover({ loop: reduced })

  expect(screen.getByText('An agent armed a bounded monitor on this session. It is probed and edited through the monitor tools, so the goal fields are not shown here. You can still stop it, or clear the stopped record.')).toBeTruthy()
  expect(screen.queryByRole('textbox', { name: 'Goal description' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Start loop' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Trigger nudge' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Stop loop' })).toBeTruthy()
})

it('keeps a websocket structured monitor reduced when it includes wake instructions', () => {
  const live: AutoNudgeLoop = {
    id: 'monitor-live', slot_key: 'chat-1', message: 'wake instructions', active: true,
    idle_secs: 300, max_cycles: 8, cycle_count: 2, last_fire_ts: 0, next_due_ts: 0,
    monitor: { agent_turns: 3, budgets: { max_agent_turns: 8 } },
  }

  renderPopover({ loop: live })

  expect(screen.getByText('An agent armed a bounded monitor on this session. It is probed and edited through the monitor tools, so the goal fields are not shown here. You can still stop it, or clear the stopped record.')).toBeTruthy()
  expect(screen.queryByRole('textbox', { name: 'Goal description' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Trigger nudge' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Stop loop' })).toBeTruthy()
})

it('blocks loop controls until a failed snapshot is retried', () => {
  const onRetryLoopLoad = vi.fn()
  const { rerender } = renderPopover({ loopLoadFailed: true, onRetryLoopLoad })

  expect(screen.getByText("Couldn't load this session's goal-loop state. Retry loading before starting a loop.")).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Start loop' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }))
  expect(onRetryLoopLoad).toHaveBeenCalledOnce()

  rerender(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}>
      <AutoNudgePopover slotKey="chat-1" loop={null} open={true} onChange={() => {}} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
  expect(screen.getByRole('button', { name: 'Start loop' })).not.toBeDisabled()
})

it('renders the literal {{STOP_FILE}} placeholder in the stop-loop hint (i18next does not re-interpolate the value)', () => {
  renderPopover({})

  // The hint names the SAME token the goal template carries, so a reader can
  // tie the sentence to the visible `{{STOP_FILE}}` in the textarea. The value
  // is passed as an interpolation variable; i18next >= 21 defaults
  // `skipOnVariables: true`, so the inserted moustache must survive verbatim
  // rather than being resolved a second time to an empty string.
  const hint = screen.getByText(/A Stop loop button appears here/)
  expect(hint.textContent).toContain('{{STOP_FILE}} in the goal is replaced with a real file path when the loop starts.')
  expect(hint.textContent).not.toContain('{{stopFile}}')
  expect((screen.getByRole('textbox', { name: 'Goal description' }) as HTMLTextAreaElement).value).toContain('{{STOP_FILE}}')
})
