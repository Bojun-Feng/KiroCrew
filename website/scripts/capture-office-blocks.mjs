/**
 * Screenshot harness for the side panel's STRUCTURED Office preview: a .docx
 * rendered as headings / lists / a table / an embedded picture, and a .pptx
 * rendered as one card per slide with a speaker-notes fold.
 *
 * Same house pattern as `capture-pierre-files-tab.mjs`: the REAL built SPA
 * (`website/dist`) behind the shared in-process static server, with every
 * `/api/**` answered from fixtures via Playwright route interception —
 * gateway-free (no kiro-cli, no live backend, no token). The client code under
 * test is unmodified.
 *
 * NEW FIXTURES (no sibling script stubbed these before):
 *   /api/file-office-preview?format=blocks → the structured block list
 *   /api/file-office-preview               → the plaintext fallback shape
 *   /api/file-office-media                 → one embedded picture's PNG bytes
 *
 * The picture is rendered by the browser this harness already launched, so the
 * bytes are a real PNG with no encoder of our own and no committed binary
 * fixture — the same reasoning as `lib/mock-shot.mjs`.
 *
 * `.docx` and `.pptx` are RICH file types (`RICH_FILE_TYPES` in
 * MarkdownPanel.tsx), so the viewer never queries `/api/file-read` for them and
 * there is no cold-tab content hydration to fixture. The panel state is still
 * pre-seeded through localStorage, because the tab strip and the panel's open
 * flag are PERSISTED stores rather than props:
 *   `mc-activity-open:<slot>`  chatSlice's per-slot panel open flag
 *   `mc-panel-tabs:<slot>`     usePanelTabs' bucket ({activeId, tabs})
 *
 * Frames:
 *   10-docx-blocks-dark      a report: H1, body paragraph, bulleted list,
 *   11-docx-blocks-light     numbered list, 4x3 table, the embedded chart, and
 *                            a closing paragraph with bold + italic runs
 *   12-pptx-slides-dark      a two-slide deck as cards, "Slide N" headers, the
 *   13-pptx-slides-light     title beside each, bullets and a table inside
 *   14-pptx-notes-open-dark  the same deck with slide 1's speaker-notes fold
 *                            OPEN — the notes body is mounted only while open,
 *                            so a closed fold contributes no text nodes and a
 *                            find cannot report a match the reader cannot see
 *   15-docx-text-fallback-dark  blocks came back EMPTY (a container the
 *                            structured extractor could not read), so the
 *                            viewer re-requests text mode and renders the flat
 *                            preview — never worse than before this change —
 *                            behind a marker saying so, so a table this preview
 *                            flattened is not mistaken for the document's own
 *   16-preview-failure-dark  the request FAILED rather than being refused by
 *                            format: ErrorNotice with the agent hand-off and a
 *                            next-step line, ALONGSIDE the download card so a
 *                            failed preview does not also take away the bytes
 *
 * Every frame is an ELEMENT screenshot of the side panel. Dimensions are
 * asserted after each write against the 2000px-per-edge PR-media budget, and
 * each frame's own content is probed BEFORE the write so a blank or wrong
 * surface throws instead of being saved as evidence.
 *
 * Usage: node scripts/capture-office-blocks.mjs [outDir]
 */
import { chromium } from 'playwright'
import { mkdirSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { serveDist } from './lib/serve-dist.mjs'
import { logPageProblems, stubDashboardApi, json } from './lib/stub-dashboard-api.mjs'
import { chromiumExecutable } from './lib/chromium-executable.mjs'

const OUT = process.argv[2] || '../temp-screenshots/office-blocks'
/** Repo root, derived from this script's own location: the fixture paths show a
 *  real project path in the panel header without pinning frames to one worktree. */
const PROJECT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const SLOT = 'chat-office-blocks'

/** Hard ceiling for a PR-attached PNG, on BOTH edges. */
const MAX_EDGE = 2000
/** Milli-bytes per pixel below which a PNG is almost certainly a blank surface. */
const MIN_MBPP = 15

const DOCX = `${PROJECT}/reports/Q3-platform-review.docx`
const PPTX = `${PROJECT}/reports/Q3-platform-review.pptx`
/** A container the structured extractor cannot read, so `blocks` comes back
 *  empty and the viewer falls back to the text shape. */
const ODD_DOCX = `${PROJECT}/reports/legacy-export.docx`
/** A path the fixture answers with a 500, to photograph the failure surface. */
const FAILING_DOCX = `${PROJECT}/reports/server-error.docx`
/** A document whose pictures cannot be shown: one the backend refused to serve
 *  (`member: null` -- a metafile, an SVG, a missing part) and one it named but
 *  the media endpoint then 404s, which the <img> reports through `onError`. Both
 *  land on the same placeholder, so one frame is evidence for both entry
 *  points. */
const UNSERVABLE_DOCX = `${PROJECT}/reports/vector-charts.docx`

const MEDIA_MEMBER = 'word/media/image1.png'

mkdirSync(OUT, { recursive: true })

// ── Fixtures ────────────────────────────────────────────────────────────────

/** The block list `format=blocks` returns for a .docx. Shape and field names
 *  come from `kiro_crew.doc_blocks.extract_blocks`; this is one real document's
 *  worth of every block type the renderer handles. */
const DOCX_BLOCKS = [
  { type: 'heading', level: 1, text: 'Q3 platform review' },
  { type: 'paragraph', runs: [{
    text: 'Adoption grew across every region this quarter. The detail below is the '
      + 'same data the weekly dashboard reports, restated once so it can be read offline.',
    bold: false, italic: false,
  }] },
  { type: 'heading', level: 2, text: 'Highlights' },
  { type: 'list', ordered: false, items: [
    'Weekly active workspaces passed the 10,000 mark in August.',
    'Median time-to-first-agent-run fell from 14 minutes to under 4.',
    'Two regions are now above the retention target for the first time.',
  ] },
  { type: 'heading', level: 2, text: 'Rollout order' },
  { type: 'list', ordered: true, items: [
    'Enable for internal workspaces.',
    'Extend to design partners.',
    'General availability.',
  ] },
  { type: 'heading', level: 2, text: 'Signups by region' },
  { type: 'table', rows: [
    ['Region', 'Signups', 'Change'],
    ['EMEA', '4,182', '+18%'],
    ['Americas', '3,904', '+11%'],
    ['APAC', '2,671', '+27%'],
  ] },
  { type: 'heading', level: 2, text: 'Trend' },
  { type: 'image', member: MEDIA_MEMBER },
  { type: 'paragraph', runs: [
    { text: 'Note: ', bold: true, italic: false },
    { text: "APAC's jump follows the regional launch and is not expected to repeat. ", bold: false, italic: false },
    { text: 'Figures are provisional.', bold: false, italic: true },
  ] },
]

/** Prose around two unshowable pictures. The text reads as complete, which is
 *  exactly why the gap has to be visible: without the placeholder a reader has
 *  no way to tell a picture was dropped. */
const UNSERVABLE_BLOCKS = [
  { type: 'heading', level: 1, text: 'Regional trend charts' },
  { type: 'paragraph', runs: [{
    text: 'The charts below were pasted from the source workbook.',
    bold: false, italic: false,
  }] },
  // The backend could not serve this one at all.
  { type: 'image', member: null },
  { type: 'paragraph', runs: [{
    text: 'Signups continue to track the regional launch dates.',
    bold: false, italic: false,
  }] },
  // Named, but the media endpoint refuses it: the <img> onError path.
  { type: 'image', member: 'word/media/image9.emf' },
]

/** One `slide` block per slide, `index` being the PRESENTATION position — the
 *  backend resolves that from `p:sldIdLst`, not from the part filenames. */
const PPTX_BLOCKS = [
  {
    type: 'slide', index: 1, title: 'Q3 platform review',
    blocks: [
      { type: 'paragraph', runs: [{
        text: 'Adoption, rollout and what changes next quarter',
        bold: false, italic: false,
      }] },
      { type: 'list', ordered: false, items: [
        '10,000 weekly active workspaces',
        'Time-to-first-run under 4 minutes',
        'Two regions above the retention target',
      ] },
    ],
    notes: 'Keep this to 30 seconds — the detail is on the next slide.',
  },
  {
    type: 'slide', index: 2, title: 'Signups by region',
    blocks: [
      { type: 'table', rows: [
        ['Region', 'Signups', 'Change'],
        ['EMEA', '4,182', '+18%'],
        ['Americas', '3,904', '+11%'],
        ['APAC', '2,671', '+27%'],
      ] },
    ],
  },
]

/** What `format=text` returns for the fallback document: the flat extraction
 *  the preview showed before this change, and still shows when the structured
 *  extractor gets nothing out of a container. */
const FALLBACK_TEXT = [
  'Legacy export',
  '',
  'This container came from an older writer, so the structured extractor found '
    + 'nothing it could resolve and the preview falls back to flat text.',
  '',
  'Region\tSignups\tChange',
  'EMEA\t4,182\t+18%',
  'Americas\t3,904\t+11%',
].join('\n')

const slots = [{
  key: SLOT,
  title: 'Q3 platform review',
  running: false,
  last_message: 'Q3 platform review',
  messages: 2,
  agent: 'kirocrew',
  memory_mode: 'persistent',
  project: PROJECT,
  modified: Math.floor(Date.now() / 1000),
  source_links: [],
  source_links_total: 0,
}]

const t0 = Math.floor(Date.now() / 1000) - 900
const slotDetail = {
  running: false, has_more: false, total: 2, queue: [],
  messages: [
    { role: 'user', content: 'Open the Q3 review and the deck that goes with it.', ts: String(t0) },
    { role: 'assistant', content: 'Both are in the side panel.', ts: String(t0 + 60) },
  ],
}

// ── Panel state seeds (persisted stores, not props) ─────────────────────────

const fileTab = (path, title) => ({
  id: `file:${path}`,
  kind: 'file',
  title,
  path,
  slot: SLOT,
  diffMode: false,
})

/** Bucket shape `usePanelTabs` rehydrates from `mc-panel-tabs:<slot>`. */
const bucket = (tabs, activeId) => JSON.stringify({ activeId, tabs })

// ── Harness ─────────────────────────────────────────────────────────────────

/** PNG width/height straight out of the IHDR chunk — no image dependency. */
function pngSize(path) {
  const b = readFileSync(path)
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) }
}

/** A bar-chart PNG at an exact size, rendered by the browser the caller already
 *  launched. Real PNG bytes with no encoder and no committed binary fixture —
 *  the reasoning in `lib/mock-shot.mjs` applies here too. A chart is the fixture
 *  because the block being proved is a picture EMBEDDED IN A REPORT, and a
 *  recognisable one makes the frame readable as evidence. */
async function chartPng(browser, w, h) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 })
  await page.setContent(`<!doctype html><style>
    html,body{margin:0;height:100%;background:#f4f6fb;font:600 13px system-ui,sans-serif;color:#1f2937}
    .t{position:absolute;left:14px;top:10px}
    .plot{position:absolute;left:26px;right:16px;bottom:22px;top:42px;
          display:flex;align-items:flex-end;gap:22px;
          border-bottom:2px solid #98a2b3}
    .b{flex:1;border-radius:3px 3px 0 0}
  </style><div class="t">Signups by region</div><div class="plot">
    <div class="b" style="height:82%;background:#4f7cff"></div>
    <div class="b" style="height:58%;background:#3ec7a0"></div>
    <div class="b" style="height:96%;background:#f0a63c"></div>
    <div class="b" style="height:41%;background:#e2617a"></div>
  </div>`)
  const buf = await page.screenshot()
  await page.close()
  return buf
}

async function main() {
  const { srv, base } = await serveDist()
  const executablePath = chromiumExecutable()
  console.log('chromium:', executablePath || '(playwright default)')
  const browser = await chromium.launch({ executablePath })
  const chart = await chartPng(browser, 420, 180)

  const wrote = []

  /** Assert each probe is visible with non-empty text; return what was found.
   *  A probe may name an ATTRIBUTE instead (`attr`) — an icon-only control
   *  carries no innerText, so demanding text there would fail on a perfectly
   *  rendered node. A failed probe THROWS rather than saving a lookalike: the
   *  point of these frames is evidence, and one nobody can trust is worse than
   *  a missing one. */
  async function assertRendered(name, probes) {
    const found = []
    for (const { selector, locator, min = 1, attr } of probes) {
      const count = await locator.count()
      if (count < min) {
        throw new Error(`frame ${name}: probe \`${selector}\` matched ${count} node(s), need >= ${min} — surface did not render; fix the fixture, do not save the frame`)
      }
      const texts = []
      for (let i = 0; i < Math.min(count, min + 2); i++) {
        const v = attr
          ? await locator.nth(i).getAttribute(attr).catch(() => null)
          : await locator.nth(i).innerText().catch(() => '')
        const t = (v || '').trim()
        if (t) texts.push(`${attr ? `${attr}=` : ''}${t.replace(/\s+/g, ' ').slice(0, 70)}`)
      }
      if (texts.length === 0) {
        throw new Error(`frame ${name}: probe \`${selector}\` matched ${count} node(s) but every one is EMPTY — blank surface; fix the fixture, do not save the frame`)
      }
      found.push({ selector, count, text: texts.join(' ⏐ ') })
    }
    return found
  }

  /** Record a written PNG: edge budget + blank-frame density gate. A PNG of a
   *  blank surface compresses to almost nothing, so bytes-per-pixel catches the
   *  frame that exists on disk and shows nothing. */
  function record(file, evidence) {
    const { w, h } = pngSize(file)
    const bytes = readFileSync(file).length
    const mbpp = Math.round((bytes * 1000) / (w * h))
    const over = w > MAX_EDGE || h > MAX_EDGE
    const blank = mbpp < MIN_MBPP
    console.log(`wrote ${file}  ${w}x${h}  ${bytes}B  ${mbpp} milli-bytes/px${over ? '  ⚠️ OVER 2000px' : ''}${blank ? `  ⚠️ LIKELY BLANK (< ${MIN_MBPP})` : ''}`)
    for (const e of evidence) console.log(`      asserted ${e.selector}  ×${e.count}  →  ${e.text}`)
    wrote.push({ file, w, h, bytes, mbpp, over, blank, evidence })
    if (blank) throw new Error(`frame ${file}: ${mbpp} milli-bytes/px is below the ${MIN_MBPP} blank-frame floor — re-shoot, do not ship`)
  }

  const probe = (selector, locator, opts = {}) => ({ selector, locator, min: opts.min, attr: opts.attr })

  /**
   * Open one document in the side panel on one theme, and hand back the page.
   *
   * A fresh context per frame rather than one shared page: the theme is read
   * from localStorage at boot, so switching it in place would need a reload
   * anyway, and a clean context is what keeps one frame's expanded notes fold
   * out of the next frame.
   *
   * `?sid=` selects the slot deterministically (the restore key is per-MODE,
   * `mc-active-slot-chat`, so a bare `mc-active-slot` does nothing). The other
   * seeds keep the frame clean:
   *   mc-activity-open:<slot>          the side panel is OPEN
   *   mc-panel-tabs:<slot>             the tab strip and which tab is active
   *   mc-files-rail-open               rail closed: this feature is the VIEWER
   *   mc-side-panel-width              wide enough to read a table
   *   mc-chat-config.pinLastPrompt     the pinned-prompt banner steals height
   *   mc-git-panel-opened:<slot>:<dir> ChatPage creates and FOCUSES a Git tab
   *                                    for any repo project dir; this marker is
   *                                    the "already did this" flag that effect
   *                                    checks, without which every frame
   *                                    captures the Git panel instead
   */
  async function open(path, title, theme) {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      // Table type and the 11px slide labels render soft at 1x on GitHub.
      deviceScaleFactor: 2,
    })
    const page = await context.newPage()

    const extra = async (apiPath, route) => {
      const url = new URL(route.request().url())
      const q = url.searchParams.get('path') || ''
      const format = url.searchParams.get('format') || 'text'

      if (apiPath === '/api/chat/slots') return json(route, slots), true
      if (/^\/api\/chat\/slots\/[^/]+/.test(apiPath)) return json(route, slotDetail), true

      // repo:false so ChatPage creates no Git tab and the rail needs no
      // status fixture — this harness is about the viewer column.
      if (apiPath === '/api/project/tree') {
        return json(route, { root: PROJECT, paths: [], repo: false, truncated: false }), true
      }
      if (apiPath === '/api/project/git') {
        return json(route, { path: PROJECT, repo: false }), true
      }
      if (apiPath === '/api/project/git/status') return json(route, { repo: false, files: [] }), true
      if (apiPath === '/api/recent-projects') return json(route, { dirs: [PROJECT] }), true

      if (apiPath === '/api/file-office-preview') {
        // A real fault, not a format refusal: 500 is what the viewer must turn
        // into an ErrorNotice rather than a bare download card.
        if (q === FAILING_DOCX) {
          return route.fulfill({
            status: 500,
            contentType: 'application/json',
            body: '{"error":"failed to extract preview","code":"preview_extraction_failed"}',
          }), true
        }
        if (format === 'blocks') {
          if (q === DOCX) return json(route, { blocks: DOCX_BLOCKS, truncated: false }), true
          if (q === UNSERVABLE_DOCX) {
            // truncated: true — a dropped picture IS an incomplete extraction,
            // and the backend says so on the same flag the caps use.
            return json(route, { blocks: UNSERVABLE_BLOCKS, truncated: true }), true
          }
          if (q === PPTX) return json(route, { blocks: PPTX_BLOCKS, truncated: false }), true
          // The fallback document: the endpoint answers 200 with an EMPTY list,
          // which is the backend saying "nothing structured here".
          return json(route, { blocks: [], truncated: false }), true
        }
        return json(route, { text: FALLBACK_TEXT, truncated: false }), true
      }
      if (apiPath === '/api/file-office-media') {
        const member = url.searchParams.get('member') || ''
        // Mirrors the endpoint: only an allowlisted media member is served, and
        // the response carries the sniffed type plus nosniff.
        if (member !== MEDIA_MEMBER) {
          return route.fulfill({ status: 404, contentType: 'application/json', body: '{"code":"not_found"}' }), true
        }
        return route.fulfill({
          status: 200,
          contentType: 'image/png',
          headers: { 'X-Content-Type-Options': 'nosniff' },
          body: chart,
        }), true
      }
      return false
    }

    await stubDashboardApi(page, {
      slots,
      theme,
      extra,
      localStorageEntries: {
        'mc-active-slot-chat': SLOT,
        [`mc-activity-open:${SLOT}`]: 'true',
        [`mc-panel-tabs:${SLOT}`]: bucket([fileTab(path, title)], `file:${path}`),
        // '1'/'0', NOT 'true'/'false': these are read through `usePersistedBool`,
        // whose getter is `v === '1'`.
        'mc-files-rail-open': '0',
        'mc-side-panel-width': '860',
        'kirocrew:comment-hint-dismissed': '1',
        [`mc-git-panel-opened:${SLOT}:${PROJECT}`]: '1',
        'mc-chat-config': JSON.stringify({ pinLastPrompt: false, streamMode: 'immediate' }),
      },
    })
    logPageProblems(page)

    await page.goto(`${base}/?sid=${encodeURIComponent(SLOT)}`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2600)
    return { context, page }
  }

  /** The side panel's own root: the only element with `.side-panel-strip` as a
   *  direct child (see SidePanel's render). */
  const panelOf = page => page.locator('div:has(> .side-panel-strip)').last()

  /** Open, wait for the surface, assert, shoot, close. */
  async function frame(name, { path, title, theme, probes, before }) {
    const { context, page } = await open(path, title, theme)
    const panel = panelOf(page)
    await panel.waitFor({ state: 'visible', timeout: 20000 })
    if (before) await before(page, panel)
    await page.waitForTimeout(900)
    const evidence = await assertRendered(name, probes(page, panel))
    const file = `${OUT}/${name}.png`
    await panel.screenshot({ path: file })
    record(file, evidence)
    await context.close()
  }

  // ── Frames 10/11: the docx report, dark and light ──────────────────────────
  for (const [name, theme] of [['10-docx-blocks-dark', 'dark'], ['11-docx-blocks-light', 'light']]) {
    await frame(name, {
      path: DOCX, title: 'Q3-platform-review.docx', theme,
      before: async page => {
        await page.getByRole('heading', { name: 'Q3 platform review' }).first()
          .waitFor({ state: 'visible', timeout: 20000 })
        // The picture arrives over a second request; wait for it to decode so
        // the frame is not shot mid-load.
        await page.locator('img[src*="file-office-media"]').first()
          .waitFor({ state: 'visible', timeout: 20000 })
      },
      probes: (page, panel) => [
        probe('h1 "Q3 platform review"', panel.locator('h1', { hasText: 'Q3 platform review' })),
        probe('h2 headings', panel.locator('h2'), { min: 3 }),
        probe('unordered list items', panel.locator('ul > li'), { min: 3 }),
        probe('ordered list items', panel.locator('ol > li'), { min: 3 }),
        probe('table header cells', panel.locator('th'), { min: 3 }),
        probe('table body cells', panel.locator('td'), { min: 9 }),
        probe('embedded picture src=…file-office-media', panel.locator('img[src*="file-office-media"]'), { attr: 'src' }),
        probe('bold run "Note:"', panel.locator('strong', { hasText: 'Note:' })),
        probe('italic run', panel.locator('em', { hasText: 'provisional' })),
        probe('download-original affordance', panel.getByText('Download original')),
      ],
    })
  }

  // ── Frames 12/13: the deck as slide cards, dark and light ─────────────────
  for (const [name, theme] of [['12-pptx-slides-dark', 'dark'], ['13-pptx-slides-light', 'light']]) {
    await frame(name, {
      path: PPTX, title: 'Q3-platform-review.pptx', theme,
      before: async page => {
        await page.getByText('Slide 1').first().waitFor({ state: 'visible', timeout: 20000 })
      },
      probes: (page, panel) => [
        probe('slide header "Slide 1"', panel.getByText('Slide 1')),
        probe('slide header "Slide 2"', panel.getByText('Slide 2')),
        probe('slide 1 title', panel.getByText('Q3 platform review')),
        probe('slide 2 title', panel.getByText('Signups by region')),
        probe('slide bullets', panel.locator('ul > li'), { min: 3 }),
        probe('slide table cells', panel.locator('td'), { min: 9 }),
        probe('notes fold toggle (collapsed)', panel.getByRole('button', { name: /Speaker notes/i })),
        probe('download-original affordance', panel.getByText('Download original')),
      ],
    })
  }

  // ── Frame 14: the notes fold OPEN ─────────────────────────────────────────
  // The notes body is mounted only while open, so this frame is also the proof
  // that a CLOSED fold contributes no text nodes — frames 12/13 above assert the
  // toggle exists while its text is absent from the DOM.
  await frame('14-pptx-notes-open-dark', {
    path: PPTX, title: 'Q3-platform-review.pptx', theme: 'dark',
    before: async (page, panel) => {
      await page.getByText('Slide 1').first().waitFor({ state: 'visible', timeout: 20000 })
      const toggle = panel.getByRole('button', { name: /Speaker notes/i }).first()
      if (await page.getByText('Keep this to 30 seconds', { exact: false }).count() !== 0) {
        throw new Error('frame 14: the notes text is in the DOM before the fold was opened — the mount-on-open contract is broken, do not save the frame')
      }
      await toggle.click()
      await page.getByText('Keep this to 30 seconds', { exact: false }).first()
        .waitFor({ state: 'visible', timeout: 10000 })
    },
    probes: (page, panel) => [
      probe('notes toggle aria-expanded=true', panel.locator('button[aria-expanded="true"]'), { attr: 'aria-expanded' }),
      probe('notes body text', panel.getByText('Keep this to 30 seconds', { exact: false })),
      probe('slide header "Slide 1"', panel.getByText('Slide 1')),
    ],
  })

  // ── Frame 15: the text fallback ───────────────────────────────────────────
  await frame('15-docx-text-fallback-dark', {
    path: ODD_DOCX, title: 'legacy-export.docx', theme: 'dark',
    before: async page => {
      await page.getByText('came from an older writer', { exact: false }).first()
        .waitFor({ state: 'visible', timeout: 20000 })
    },
    probes: (page, panel) => [
      probe('flat text preview (<pre>)', panel.locator('pre')),
      probe('fallback body text', panel.getByText('came from an older writer', { exact: false })),
      probe('plain-text marker', panel.locator('[data-testid="office-plain-text-notice"]')),
      probe('download-original affordance', panel.getByText('Download original')),
    ],
  })

  // ── Frame 16: a real request failure ──────────────────────────────────────
  // Distinct from an unsupported format, which the download card answers on its
  // own: this is a fault the reader cannot diagnose, so it carries the hand-off.
  await frame('16-preview-failure-dark', {
    path: FAILING_DOCX, title: 'server-error.docx', theme: 'dark',
    before: async page => {
      await page.locator('[data-testid="office-preview-error"]').first()
        .waitFor({ state: 'visible', timeout: 20000 })
      // The card's own hint asserts a preview "isn't available for this file",
      // which is right for a 415 and wrong here — the format IS supported and a
      // retry may work. Two lines telling the reader opposite things about one
      // file is what this frame has to prove is gone, so assert the ABSENCE
      // rather than leaving it to a reader of the pixels.
      const hint = page.getByText("Preview isn't available for this file", { exact: false })
      if (await hint.count()) {
        throw new Error('frame 16: the download hint is on screen beside the failure notice — they contradict each other, do not save the frame')
      }
    },
    probes: (page, panel) => [
      probe('ErrorNotice', panel.locator('[data-testid="office-preview-error"]')),
      probe('failure sentence', panel.getByText("Couldn't load the preview", { exact: false })),
      // The recovery the prose used to describe: a real button that refetches in
      // place, so the hand-off is no longer the only thing to press.
      probe('inline Retry', panel.locator('[data-testid="office-preview-retry"]')),
      probe('agent hand-off', panel.getByRole('button', { name: /Ask the agent/i })),
      // The bytes stay reachable: the notice never replaces the download card.
      probe('download card', panel.getByText('Download original', { exact: true })),
    ],
  })

  // ── Frame 17: a picture that cannot be shown ──────────────────────────────
  // The UX lane reads the placeholder off the frames, not off the diff: without
  // this shot the copy ships unread. Both triggers are in one document, so the
  // frame proves the refused member and the failed load land on one state.
  await frame('17-docx-image-unavailable-dark', {
    path: UNSERVABLE_DOCX, title: 'vector-charts.docx', theme: 'dark',
    before: async page => {
      // TWO placeholders: the `member: null` block renders on first paint, the
      // `.emf` one only after its media request 404s and onError fires. Waiting
      // for the second is what keeps the frame off the mid-load state.
      await page.locator('[data-testid="office-image-unavailable"]').nth(1)
        .waitFor({ state: 'visible', timeout: 20000 })
    },
    probes: (page, panel) => [
      probe('placeholder (refused member + failed load)',
        panel.locator('[data-testid="office-image-unavailable"]'), { min: 2 }),
      probe('placeholder copy', panel.getByText('Picture unavailable', { exact: false })),
      // The surrounding prose still renders: the gap is local to the picture.
      probe('heading still renders', panel.getByText('Regional trend charts')),
      probe('body text still renders',
        panel.getByText('pasted from the source workbook', { exact: false })),
      // The bytes stay reachable, which is what the copy tells them to do.
      probe('download-original affordance', panel.getByText('Download original')),
    ],
  })

  // ── Frame 18: the document's END, where the picture actually renders ──────
  // Frames 10/11 are shot from the top and the report is taller than the panel,
  // so the embedded chart lands at the fold as a sliver and the bold/italic
  // closing paragraph falls past it. The success render of OfficeImage and
  // /api/file-office-media is the one state a reader cannot judge from the other
  // frames, so it gets its own, scrolled to the end.
  await frame('18-docx-blocks-end-dark', {
    path: DOCX, title: 'Q3-platform-review.docx', theme: 'dark',
    before: async page => {
      await page.locator('img[src*="file-office-media"]').first()
        .waitFor({ state: 'visible', timeout: 20000 })
      // The scrollable preview region, by the same role+name the component gives
      // it for keyboard users.
      const region = page.getByRole('region', { name: 'Q3-platform-review.docx' }).first()
      await region.evaluate(el => { el.scrollTop = el.scrollHeight })
      // Settle the scroll before shooting, and confirm the picture is fully in
      // view rather than clipped at the fold -- the whole point of this frame.
      await page.waitForTimeout(400)
      const clipped = await page.locator('img[src*="file-office-media"]').first().evaluate(
        (img, ) => {
          const r = img.getBoundingClientRect()
          const host = img.closest('[role="region"]')
          if (!host) return true
          const h = host.getBoundingClientRect()
          return r.top < h.top || r.bottom > h.bottom
        },
      )
      if (clipped) {
        throw new Error('frame 18: the picture is still clipped by the scroll region — this frame exists to show it whole, do not save it')
      }
    },
    probes: (page, panel) => [
      probe('embedded picture src=…file-office-media', panel.locator('img[src*="file-office-media"]'), { attr: 'src' }),
      probe('bold run "Note:"', panel.locator('strong', { hasText: 'Note:' })),
      probe('italic run', panel.locator('em', { hasText: 'provisional' })),
      probe('closing paragraph text', panel.getByText('not expected to repeat', { exact: false })),
      probe('download-original affordance', panel.getByText('Download original')),
    ],
  })

  console.log('\n── SUMMARY ─────────────────────────────')
  for (const w of wrote) {
    console.log(`${w.over || w.blank ? 'FAIL' : ' ok '}  ${w.w}x${w.h}  ${String(w.mbpp).padStart(4)} mB/px  ${w.file}`)
    for (const e of w.evidence) console.log(`        ${e.selector} → ${e.text}`)
  }
  const bad = wrote.filter(w => w.over || w.blank)
  console.log(bad.length
    ? `FAIL: ${bad.length} frame(s) over ${MAX_EDGE}px or below the ${MIN_MBPP} mB/px blank floor`
    : `all ${wrote.length} frames within ${MAX_EDGE}px and above the ${MIN_MBPP} mB/px blank floor`)

  await browser.close()
  srv.close()
  if (bad.length) process.exit(1)
}

main().catch(err => { console.error(err); process.exit(1) })
