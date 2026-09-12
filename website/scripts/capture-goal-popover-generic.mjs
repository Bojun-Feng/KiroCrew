/**
 * Screenshot harness for the composer's GENERIC goal-loop popover.
 *
 * Opens the real built SPA (website/dist) against the shared API stub, clicks
 * the composer's "Set a goal" trigger and photographs the popover that opens.
 * It asserts, not just photographs: the popover must carry the generic goal
 * textarea and must NOT carry a pull-request URL field, so a regression back to
 * a pull-request-only form fails this script instead of shipping quietly.
 *
 * Five states are photographed, driven by what the stubbed
 * `GET /api/autonudge/slot/<slot>` returns for the frame:
 *   01 no loop          -- the "Start loop" form a fresh session shows
 *   02 active loop      -- Stop loop, Trigger nudge and the countdown line
 *   03 stopped record   -- "Clear stopped goal", then its confirm row after one press
 *   04 reduced monitor  -- an agent-armed structured monitor: the slot returns a
 *                          loop WITHOUT `message`, so the popover hides the goal
 *                          form and offers only the notice plus Stop loop
 *   05 snapshot failed  -- the slot endpoint answers HTTP 500: the inline error
 *                          notice and its "Retry loading" button, Start loop disabled
 *
 * Build first (`npm run build`), then: node scripts/capture-goal-popover-generic.mjs [outDir]
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { serveDist } from './lib/serve-dist.mjs'
import { logPageProblems, stubDashboardApi, json } from './lib/stub-dashboard-api.mjs'

const OUT = process.argv[2] || '../temp-screenshots/goal-popover-generic'
const SLOT = 'chat-goal'
const PROJECT = '/home/user/workspace/notes'

mkdirSync(OUT, { recursive: true })

const slots = [{
  key: SLOT,
  title: 'Keep the nightly build green',
  running: false,
  last_message: 'Ready when you are.',
  messages: 1,
  agent: 'kirocrew',
  memory_mode: 'persistent',
  project: PROJECT,
  folder_id: '',
  modified: Math.floor(Date.now() / 1000),
  source_links: [],
  source_links_total: 0,
}]

const detail = {
  running: false,
  has_more: false,
  total: 1,
  queue: [],
  project: PROJECT,
  messages: [
    { role: 'assistant', ts: Date.now() / 1000 - 30, content: 'Ready when you are.' },
  ],
}

const GOAL = 'Keep the nightly build green: rerun the failing shard, bisect a real red, open a fix PR.'
const now = Date.now() / 1000
const loopBase = {
  id: 'loop-1', slot_key: SLOT, message: GOAL, idle_secs: 300, max_cycles: 24,
  cycle_count: 3, last_fire_ts: now - 120, next_due_ts: now + 180,
}
// A structured monitor armed by an agent is reported through the same slot
// route with NO `message` / `banner` / `stop_sentinel_path` keys -- that
// absence is what the popover keys its reduced row on.
const reducedMonitor = {
  id: 'monitor-1', slot_key: SLOT, active: true, idle_secs: 300, max_cycles: 8,
  cycle_count: 2, last_fire_ts: 0, next_due_ts: now + 240, stopped_reason: '',
}
/**
 * One frame per loop state the popover can be opened onto.
 *   loop      -- body of `{ loop }` the slot route returns (`null` = no loop)
 *   status    -- HTTP status for the slot route (default 200)
 *   reduced   -- the frame is the reduced structured-monitor row
 *   failed    -- the frame is the snapshot-failed row
 *   confirm   -- also press "Clear stopped goal" and shoot the confirm row
 */
const frames = [
  { name: '01-generic-goal-popover', loop: null },
  { name: '02-active-loop', loop: { ...loopBase, active: true } },
  { name: '03-stopped-record', loop: { ...loopBase, active: false, next_due_ts: 0, stopped_reason: 'max_cycles' }, confirm: true },
  { name: '04-reduced-monitor-active', loop: reducedMonitor, reduced: true },
  { name: '05-snapshot-failed', loop: null, status: 500, failed: true },
]

let failed = false
function check(name, ok, detail) {
  console.log(`${name}: ${ok ? 'OK' : 'MISMATCH'} ${detail}`)
  if (!ok) failed = true
  return ok
}

const SCALE = 2
const MARGIN = 40
/** Longest edge a review frame may have, in device pixels (the image readers downscale past it). */
const MAX_EDGE = 2000

/**
 * Photograph the open popover together with the composer trigger it hangs off,
 * not the whole 1400x900 viewport: at deviceScaleFactor 2 a full frame is
 * 2800x1800, past what the review lanes read at full resolution. The clip is
 * the union of the popover and its trigger plus a margin, clamped to the
 * viewport, and the resulting frame is asserted to stay under MAX_EDGE.
 */
async function shootPopover(page, name, path) {
  const viewport = page.viewportSize()
  const popover = await page.getByRole('dialog').first().boundingBox()
  const trigger = await page.getByRole('button', { name: /^(Set a goal|Goal (active|loop armed))/ }).first().boundingBox()
  const boxes = [popover, trigger].filter(Boolean)
  if (boxes.length === 0) return check(`${name} frame`, false, 'no popover or trigger box to clip to')
  const x0 = Math.max(0, Math.min(...boxes.map(b => b.x)) - MARGIN)
  const y0 = Math.max(0, Math.min(...boxes.map(b => b.y)) - MARGIN)
  const x1 = Math.min(viewport.width, Math.max(...boxes.map(b => b.x + b.width)) + MARGIN)
  const y1 = Math.min(viewport.height, Math.max(...boxes.map(b => b.y + b.height)) + MARGIN)
  const clip = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 }
  await page.screenshot({ path, clip })
  const w = Math.round(clip.width * SCALE), h = Math.round(clip.height * SCALE)
  return check(`${name} frame`, w < MAX_EDGE && h < MAX_EDGE, `${w}x${h}px`)
}

async function main() {
  const { srv, base } = await serveDist()
  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: SCALE })

  for (const frame of frames) {
    const extra = async (path, route) => {
      if (path.startsWith('/api/chat/slots/')) { await json(route, detail); return true }
      if (path.startsWith('/api/autonudge/slot/')) {
        if (frame.status && frame.status !== 200) { await json(route, { error: 'snapshot unavailable' }, frame.status); return true }
        await json(route, { loop: frame.loop }); return true
      }
      if (path.startsWith('/api/autonudge')) { await json(route, { loops: frame.loop ? [frame.loop] : [] }); return true }
      return false
    }

    for (const theme of ['dark', 'light']) {
      const page = await context.newPage()
      logPageProblems(page)
      await stubDashboardApi(page, { folders: [], slots, theme, extra })
      await page.addInitScript(slot => { localStorage.setItem('mc-active-slot', slot) }, SLOT)
      await page.goto(base + '/', { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(2000)

      // An armed loop relabels the trigger "Goal active (cycle 3/24)"; match on
      // either spelling so one selector opens every frame.
      const trigger = page.getByRole('button', { name: /^(Set a goal|Goal (active|loop armed))/ }).first()
      await trigger.waitFor({ timeout: 10_000 })
      await trigger.click()
      await page.waitForTimeout(600)

      const goalField = await page.getByRole('textbox', { name: /goal/i }).count()
      const prField = await page.getByText(/pull request url/i).count()
      const legacyCta = await page.getByText(/legacy goal loop/i).count()
      // The reduced row hides the goal form on purpose; every other frame must show it.
      const wantGoalField = frame.reduced ? goalField === 0 : goalField >= 1
      let ok = check(
        `${frame.name}-${theme}`,
        wantGoalField && prField === 0 && legacyCta === 0,
        `goalField=${goalField}${frame.reduced ? ' (withheld on purpose)' : ''} prUrlField=${prField} legacyCta=${legacyCta}`,
      )

      if (frame.reduced) {
        const notice = await page.getByText(/An agent armed a bounded monitor on this session/).count()
        const stopBtn = await page.getByRole('button', { name: 'Stop loop' }).count()
        const nudgeBtn = await page.getByRole('button', { name: 'Trigger nudge' }).count()
        const startBtn = await page.getByRole('button', { name: 'Start loop' }).count()
        const saveBtn = await page.getByRole('button', { name: 'Save' }).count()
        ok = check(
          `${frame.name}-${theme} controls`,
          notice === 1 && stopBtn === 1 && nudgeBtn === 0 && startBtn === 0 && saveBtn === 0,
          `notice=${notice} stopLoop=${stopBtn} triggerNudge=${nudgeBtn} startLoop=${startBtn} save=${saveBtn}`,
        ) && ok
      } else if (frame.failed) {
        const errorNotice = page.locator('[data-testid="auto-nudge-snapshot-error"]')
        const errorVisible = await errorNotice.isVisible().catch(() => false)
        const retryBtn = await page.getByRole('button', { name: 'Retry loading' }).count()
        const startLoop = page.getByRole('button', { name: /^(Start loop|Save)$/ })
        const startCount = await startLoop.count()
        const startDisabled = startCount === 1 ? await startLoop.isDisabled() : false
        ok = check(
          `${frame.name}-${theme} controls`,
          errorVisible && retryBtn === 1 && startCount === 1 && startDisabled,
          `snapshotError=${errorVisible} retryLoading=${retryBtn} startOrSave=${startCount} disabled=${startDisabled}`,
        ) && ok
      } else if (frame.loop?.active) {
        const stopBtn = await page.getByRole('button', { name: 'Stop loop' }).count()
        const nudgeBtn = await page.getByRole('button', { name: 'Trigger nudge' }).count()
        ok = check(`${frame.name}-${theme} controls`, stopBtn === 1 && nudgeBtn === 1, `stopLoop=${stopBtn} triggerNudge=${nudgeBtn}`) && ok
      }
      if (frame.loop && !frame.loop.active) {
        const clearBtn = await page.getByRole('button', { name: 'Clear stopped goal' }).count()
        ok = check(`${frame.name}-${theme} controls`, clearBtn === 1, `clearStoppedGoal=${clearBtn}`) && ok
      }
      if (ok) await shootPopover(page, `${frame.name}-${theme}`, `${OUT}/${frame.name}-${theme}.png`)

      if (ok && frame.confirm) {
        await page.getByRole('button', { name: 'Clear stopped goal' }).click()
        await page.waitForTimeout(300)
        const forGood = await page.getByRole('button', { name: 'Clear goal for good' }).count()
        const cancel = await page.getByRole('button', { name: 'Cancel' }).count()
        const startLoop = await page.getByRole('button', { name: 'Start loop' }).count()
        const confirmOk = check(
          `${frame.name}-confirm-${theme}`,
          forGood === 1 && cancel === 1 && startLoop === 0,
          `clearForGood=${forGood} cancel=${cancel} startLoopWithheld=${startLoop === 0}`,
        )
        if (confirmOk) await shootPopover(page, `${frame.name}-confirm-${theme}`, `${OUT}/${frame.name}-confirm-${theme}.png`)
      }
      await page.close()
    }
  }

  await browser.close()
  srv.close()
  process.exit(failed ? 1 : 0)
}

main().catch(err => { console.error(err); process.exit(2) })
