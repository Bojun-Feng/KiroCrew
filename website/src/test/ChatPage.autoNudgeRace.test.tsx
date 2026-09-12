import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { createTestStore, renderWithProviders } from './helpers'
import type { AutoNudgeLoop } from '../components/AutoNudgePopover'
import ChatPage from '../pages/ChatPage'

vi.mock('react-virtuoso', () => ({ Virtuoso: () => null }))
vi.mock('../components/ChatInput', () => ({
  default: ({ autoNudgeLoop, autoNudgeLoadFailed, onRetryAutoNudgeLoopLoad }: {
    autoNudgeLoop: AutoNudgeLoop | null
    autoNudgeLoadFailed?: boolean
    onRetryAutoNudgeLoopLoad?: () => void
  }) => (
    <>
      <output data-testid="loop-state">{autoNudgeLoop?.active ? 'active' : 'none'}</output>
      <output data-testid="loop-load-state">{autoNudgeLoadFailed ? 'failed' : 'ready'}</output>
      <button type="button" onClick={onRetryAutoNudgeLoopLoad}>Retry loading</button>
    </>
  ),
}))
vi.mock('../components/WelcomeView', () => ({ default: () => null }))
vi.mock('../components/MarkdownPanel', () => ({ default: () => null }))
vi.mock('../components/MarkdownRenderer', () => ({ default: () => null }))
vi.mock('../pages/chat/ActivityViewer', () => ({ default: () => null }))
vi.mock('../components/DetailPanel', () => ({ default: () => null }))
vi.mock('../hooks/useBranding', () => ({ useBranding: () => ({ botName: 'Test', avatar: '' }) }))
vi.mock('../hooks/useAgents', () => ({ useAgents: () => ({ agents: [], defaultAgent: 'default' }) }))
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => ({ subscribeLogs: () => {} }) }))

const slot = 'slot-a'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('keeps a live removal when the older slot snapshot resolves later', async () => {
  localStorage.clear()
  sessionStorage.clear()
  const initial = createTestStore().getState()
  const store = createTestStore({
    ...initial,
    dashboard: {
      ...initial.dashboard,
      slots: [{ key: slot, messages: 0, running: false, mode: '', created: '', last_ts: '' }],
    },
    chat: { ...initial.chat, activeSlot: slot },
  })
  let resolveSnapshot!: (response: Response) => void
  const snapshot = new Promise<Response>(resolve => { resolveSnapshot = resolve })
  const originalFetch = globalThis.fetch
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) =>
    input === `/api/autonudge/slot/${slot}` ? snapshot : originalFetch(input, init),
  )
  const view = renderWithProviders(<ChatPage embedded />, { store })
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith(`/api/autonudge/slot/${slot}`))
  expect(screen.getByTestId('loop-state')).toHaveTextContent('none')

  // Establish that the mounted effect consumes live frames before removing it.
  act(() => {
    window.dispatchEvent(new CustomEvent('autonudge_state', {
      detail: { slot, event: 'started', loop: { id: 'loop-a', active: true } },
    }))
  })
  expect(screen.getByTestId('loop-state')).toHaveTextContent('active')
  act(() => {
    window.dispatchEvent(new CustomEvent('autonudge_state', {
      detail: { slot, event: 'removed', loop: { id: 'loop-a', active: false } },
    }))
  })
  expect(screen.getByTestId('loop-state')).toHaveTextContent('none')

  // Flush the response and React updates before checking absence, not a timer.
  await act(async () => {
    resolveSnapshot(new Response(JSON.stringify({ loop: { id: 'loop-a', active: true } })))
    await snapshot
  })
  expect(screen.getByTestId('loop-state')).toHaveTextContent('none')
  view.unmount()
  view.queryClient.clear()
})

it('folds channel slots before applying a live nudge frame', async () => {
  const channelSlot = 'slack_123'
  const initial = createTestStore().getState()
  const store = createTestStore({
    ...initial,
    dashboard: {
      ...initial.dashboard,
      slots: [{ key: channelSlot, messages: 0, running: false, mode: '', created: '', last_ts: '' }],
    },
    chat: { ...initial.chat, activeSlot: channelSlot },
  })
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ loop: null })))
  const view = renderWithProviders(<ChatPage embedded />, { store })
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('/api/autonudge/slot/slack_123'))

  act(() => {
    window.dispatchEvent(new CustomEvent('autonudge_state', {
      detail: { slot: 'slack:123', event: 'started', loop: { id: 'loop-channel', active: true } },
    }))
  })
  expect(screen.getByTestId('loop-state')).toHaveTextContent('active')
  view.unmount()
  view.queryClient.clear()
})

it('retries a failed nudge snapshot before enabling the composer', async () => {
  const initial = createTestStore().getState()
  const store = createTestStore({
    ...initial,
    dashboard: {
      ...initial.dashboard,
      slots: [{ key: slot, messages: 0, running: false, mode: '', created: '', last_ts: '' }],
    },
    chat: { ...initial.chat, activeSlot: slot },
  })
  let attempts = 0
  const originalFetch = globalThis.fetch
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    if (input === '/api/autonudge/slot/slot-a') {
      attempts += 1
      if (attempts === 1) return Promise.reject(new Error('offline'))
      return Promise.resolve(new Response(JSON.stringify({ loop: { id: 'loop-a', active: true } })))
    }
    return originalFetch(input, init)
  })
  const view = renderWithProviders(<ChatPage embedded />, { store })

  await waitFor(() => expect(screen.getByTestId('loop-load-state')).toHaveTextContent('failed'))
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }))
  await waitFor(() => {
    expect(screen.getByTestId('loop-load-state')).toHaveTextContent('ready')
    expect(screen.getByTestId('loop-state')).toHaveTextContent('active')
  })
  view.unmount()
  view.queryClient.clear()
})
