# Connector capability manifest

The field-level schema for a connector capability manifest entry, and the
work-stream DAG that sequences the connector campaign's implementation rounds.
This spec is **documentation only**: no validator, no runner, and no CI
script ship from it. It is the parent base every later connector-campaign
round (schema validation, provider-capabilities discovery, the live
conformance runner) is built against, and it is deliberately structural
enough for a validator to be written directly against it — field names,
types, required/optional-when rules, and the version relationships between
fields — without that validator's *implementation* shipping here.

Scope note: this spec governs the *campaign contract* — the shape a manifest
entry must have, and the order the campaign's provider streams unlock in. It
does not implement `src/kiro_crew/connections/**` (see
[connections.md](connections.md) for that subsystem's shipped behavior) and
does not implement `src/kiro_crew/knowledge/connectors/**` (see
[knowledge.md](knowledge.md)). A future round implements against this spec.
When that implementation changes what this spec documents, the owning-spec
rule applies exactly as it does everywhere else in this tree: the spec is
updated in the same commit as the code, the same way `connections.md` is
updated when `connections/` changes. Nothing here freezes the schema —
scoped, controlled evolution of it in a later round is the expected path, not
an exception to ask permission for.

Traceability note: the manifest is derived from campaign evidence, and that
evidence has its own provenance trail (which research pass observed which
vendor endpoint, on what date, in which workspace). That trail belongs in the
campaign's own evidence-catalog artifacts, not in this spec — a public,
in-repo contract states what a field means and how it is validated, in one
neutral sentence of provenance per concept, so a reader with only this repo
checked out can understand and implement it. It does not narrate a private
preparation process.

## Two axes, never collapsed into one

A manifest entry answers two independent questions, and collapsing them into
one field loses information a validator needs:

- **Evidence axis** — how well-sourced is the claim that this operation
  exists and has this shape? (`source_status`)
- **Implementation axis** — how far has Kiro Crew actually gotten building
  and verifying it? (`status`)

These mirror, deliberately, the two-axis shape the campaign's own evidence
catalog already uses (`evidence_status` × `implementation_status`) — a
manifest entry that flattened them back into one field would be a regression
against a distinction the campaign already established, not a simplification.

### `source_status` — the evidence axis

| Value | Meaning |
|---|---|
| `user_required` | The user (or the campaign's own mission brief) named this operation as required directly — the highest-authority source. A `user_required` entry outranks anything derived from a vendor-documentation sweep: user-stated scope is the boundary of the requirement, not a floor a catalog sweep can trim. |
| `official_baseline` | Confirmed against the vendor's own official documentation, API reference, or MCP server source. |
| `unverified` | Proposed (by a research pass, by inference from a sibling operation, or by any other non-authoritative route) but not yet confirmed against either the user's own statement or an official vendor source. |

An entry's `source_status` is never deleted for lack of an enum value to hold
it. If a real finding does not fit `user_required` / `official_baseline` /
`unverified`, the fix is to add a fourth value in a later, explicitly-scoped
revision of this spec — never to drop the entry the value would have held.
This applies with equal force to a `blocked` entry: a blocked capability is
evidence Kiro Crew already possesses, and a `source_status` or `status`
enum's shape is a schema question, never a reason to discard it.

### `status` — the implementation axis

| Value | Meaning |
|---|---|
| `planned` | In the manifest, not yet started. |
| `implementing` | Adapter code is being written; not yet passing its own tests. |
| `code_complete` | Adapter code is written and passes its own unit/contract tests, but has not yet run a live `ConformanceRun` against a real account. |
| `contract_verified` | A `ConformanceRun` has produced a `runtime_verified: true` `EvidenceReceipt` against at least one real, authorized account. |
| `live_verified` | Verified across the account/mode/surface matrix this operation's manifest entry declares (see "Per-mode, per-surface evidence" below) — not just the one account `contract_verified` required. |
| `merged` | The adapter's implementation PR has merged to the default branch. |
| `release_verified` | Confirmed working in a shipped release, not merely on the default branch. |
| `blocked` | Progress on this operation is stopped by something outside this entry's own implementation (see the `blocker` field below). A `blocked` entry can sit at any point on the `planned`→`release_verified` ladder — blocked is a stall on top of wherever the entry was, not a replacement state that erases the ladder position. Manifest storage of a blocked entry therefore keeps both the last-reached ladder value and the `blocked` flag; this spec treats `status` as carrying the ladder position and `blocker != null` as the orthogonal stall marker, rather than overloading one enum slot for both. |

Every entry produced by this campaign's current round (the W00-S1 slice, and
the evidence catalog it draws on) is `planned`: nothing has begun
implementation yet. A future round moves entries along this ladder; it does
not invent new rungs without a scoped revision of this spec, and it does not
skip a rung silently (an entry does not jump from `planned` to `merged`
without passing through the rungs a validator can check for).

## Manifest entry: one row per required operation

Every required operation the connector campaign tracks — one row per
`operation_id` — carries this field set in the manifest:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `operation_id` | string | yes | Stable identifier. Does not change across campaign rounds once assigned. |
| `provider` | string | yes | The vendor's own name for its surface (e.g. `github`), matching that vendor's own official branding. |
| `service_id` | string | yes | The campaign's neutral service-range identifier (e.g. `github`, `gmail`, `excel_shared_engine`) — one of the fixed set the campaign's evidence catalog defines. |
| `required` | boolean | yes | Whether the operation is in the campaign's required scope. |
| `category` | enum | yes | One of `baseline_alignment`, `production_requirement`, `user_extension`. This field renames evidence into a requirement class; it never shrinks scope on its own. |
| `source_status` | enum | yes | `user_required` / `official_baseline` / `unverified` — see "Two axes" above. |
| `source` | object | yes | `{source_kind, source_id, observed_at, snapshot_ref}`. `source_kind` is one of `official_docs`, `repo_path`, `format_spec`, `search_snippet_corroborated`. `snapshot_ref` points at a URL or local path+version a reader can independently re-check. |
| `observed_at` | string | yes | When the entry's shape was last confirmed against its source, so drift is detectable later. |
| `effect` | enum | yes | One of `read`, `write`, `delete`, `share`, `external_send`, `admin`, `billable`. A closed vocabulary so a governance policy hook can match on it without a free-text field. |
| `input_schema` | object | yes | `{schema_ref, schema_version}` — where the operation's input shape is defined and which version of it this entry targets. Distinct from `output_schema`: an operation's request and response shapes version independently and a validator must be able to check each on its own. |
| `output_schema` | object | yes | `{schema_ref, schema_version}` — same shape as `input_schema`, for the operation's response. |
| `tool_names` | array | yes | The concrete tool name(s) (MCP tool name, REST-wrapper function name, etc.) this operation is invoked through. A validator checks this against the live tool inventory; a manifest entry naming no tool is not yet implementable. |
| `auth_modes` | array | yes | Every auth mode this specific operation supports (e.g. `oauth_user`, `fine_grained_pat`, `service_to_service`). Declared per operation — a manifest entry never assumes every operation on one provider shares one auth mode. |
| `scopes` | array | yes | The minimal vendor-side scope(s) this operation needs. A manifest entry never requests a broader scope than the operation itself uses. |
| `account_types` | array | yes | Which account types (`personal`, `organization`, `enterprise_cloud`, `work_school`, …) the operation is available under. Each entry here is one row this operation's per-mode/per-surface evidence matrix (below) must separately cover. |
| `surfaces` | array | yes | Which entry points (chat, App, workflow, background) can reach this operation. Each entry here is a column of that same matrix. |
| `policy` | object | yes | The governance hook-point structure this operation's policy attaches to — the platform ∩ workspace ∩ session ∩ connection ∩ provider intersection model. This field declares the hook shape; it carries no policy VALUE. |
| `pagination` | string | when the operation lists or searches | The operation's own pagination contract (`page`/`perPage`, a cursor, `@odata.nextLink`, `queryMore`, …). Declared per operation: two operations on the same provider are not assumed to share one pagination contract. |
| `retry` | object | when the operation writes | Which idempotency/retry class the operation actually has: `base_sha_guard`, `generate_ids_preallocation`, `external_id_upsert`, or `none_verify_by_readback`. A manifest entry never claims a generic exactly-once guarantee an operation does not have. |
| `adapter` | object | yes | `{module_ref, version}` — a placeholder pointing at the implementation module that will back this operation and the version of it a given manifest entry targets. Left with an explicit placeholder value (never silently blank) until an implementation round assigns a real module — this spec does not assign adapters. |
| `code_refs` | array | when applicable | Pointers into an existing reusable subsystem (e.g. `connections/mint.py`) an implementation round should start from. |
| `runner_version` | string | yes | The version of the conformance-runner contract (see below) this entry's verification evidence was produced against. Distinct from `adapter.version` and from `input_schema`/`output_schema` versions — all four can advance independently and a validator must not assume they move together. |
| `verification_contract` | object | yes | Points at the operation's `ConformanceRun`/`EvidenceReceipt` requirement (see below) — not the receipt itself, just the pointer. |
| `evidence_by_mode_and_surface` | array | yes | One row per `(account_type, surface)` pair this operation declares in `account_types` × `surfaces`. See "Per-mode, per-surface evidence" below. An entry with an empty array here is only honest at `status: planned` — anything past `code_complete` needs at least one populated row. |
| `tested_sha` | string or null | yes | The commit SHA this operation's implementation was last tested against. `null` until `status` reaches `code_complete`. |
| `merged_sha` | string or null | yes | The commit SHA at which this operation's implementation merged to the default branch. `null` until `status` reaches `merged`. |
| `release_sha` | string or null | yes | The commit SHA (or tag) of the release this operation was confirmed working in. `null` until `status` reaches `release_verified`. |
| `status` | enum | yes | The operation's current implementation state — see "Two axes" above. |
| `blocker` | object or null | when `status` carries a stall | `{reason, owner, unblock_action}` — see below. Independent of where on the `status` ladder the entry sits; see the `blocked` row above. |

### Per-mode, per-surface evidence

`account_types` and `surfaces` together define a matrix: an operation
declared for `[personal, organization]` × `[chat, workflow]` has four cells,
and a manifest entry's evidence must be checkable cell-by-cell, not asserted
once for the whole operation. `evidence_by_mode_and_surface` is that matrix,
flattened to rows:

```
evidence_by_mode_and_surface: [
  {
    account_type: string     // one value from this entry's own account_types
    surface: string          // one value from this entry's own surfaces
    verification_contract_ref: string   // the ConformanceRun/EvidenceReceipt for THIS cell
    status: enum              // same ladder as the entry's own top-level `status`, for this cell only
  }
]
```

A top-level `status` of `live_verified` requires every declared
`(account_type, surface)` cell to itself be at `contract_verified` or later —
`live_verified` is defined as "the matrix is covered," not as a separate
claim asserted independently of the matrix. A validator checks this
relationship directly: it is a structural rule (an aggregate over a set of
rows), not a runtime behavior.

### `blocker` structure

```
blocker: {
  reason: string          // e.g. "BLOCKED_POLICY", "no_live_fixture_account", "no_console_registration"
  owner: string            // who can unblock it
  unblock_action: string   // the concrete action that unblocks it
}
```

### Discovery is a separate protocol from the manifest

The manifest (above) answers "which operations does Kiro Crew intend to
support for this provider." A separate, run-time question — "which
capabilities does a specific authorized account binding actually expose right
now" — is answered by a **provider-capabilities discovery** exchange, not by
this manifest. The two must not be merged into one schema: the manifest is
static and version-controlled; discovery is a live protocol.

Discovery request:

```
discovery_request: {
  provider: string
  account_binding: string       // a verified account/tenant binding reference; never empty
  requested_scope_hint: array   // optional, narrows the probe
}
```

Discovery response:

```
discovery_response: {
  provider: string
  observed_at: timestamp
  scope_snapshot: array          // the scopes this binding actually holds at probe time
  capability_rows: [
    {
      operation_id: string | null       // maps to a manifest operation_id when recognizable; null when the vendor exposes something the manifest does not yet cover
      raw_capability_signature: string  // the vendor's own capability identifier (a scope name, a tool name, …)
      matches_manifest: boolean
    }
  ]
  version_snapshot: string       // the vendor API/MCP surface's own version marker, for drift detection
}
```

`capability_rows[].matches_manifest` is the only field connecting a discovery
response back to the manifest. A `matches_manifest: false` row is recorded as
a gap; it must not be silently dropped, and it must not be auto-written into
the manifest — a human registers a genuinely new vendor capability.

### Conformance and evidence: the structural contract lives here

`verification_contract` and `evidence_by_mode_and_surface[].verification_contract_ref`
on a manifest entry point at that operation's `ConformanceRun` and
`EvidenceReceipt`. Both are defined structurally in this spec — field names,
types, and which fields are required — so a validator can be built directly
against this document. Neither is implemented here, and neither requires any
file outside this repository to be read to understand: a public spec that
pointed at an unpublished, out-of-repo concept would not be a contract a
reader could act on, so the full field set is inlined below rather than
referenced elsewhere.

`ConformanceRun` — one replayable record per verification attempt:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `run_id` | string | yes | Unique identifier for this run. |
| `operation_id` | string | yes | The manifest operation this run verifies. |
| `account_binding_ref` | string | yes | Which authorized account/tenant binding this run used — never a raw credential. |
| `account_type` | string | yes | Which of the operation's declared `account_types` this run covers. |
| `surface` | string | yes | Which of the operation's declared `surfaces` this run covers. |
| `executed_at` | timestamp | yes | When the run executed. |
| `request_shape_hash` | string | yes | A hash of the request shape sent — never the literal request, so no account-specific parameter value is retained. |
| `response_summary` | object | yes | A structural summary of the response (which fields were present, whether types matched) — never a full unredacted response dump. |
| `verdict` | enum | yes | `pass` / `fail` / `inconclusive`. |
| `evidence_receipt_ref` | string | yes | Points at this run's `EvidenceReceipt`. |

`EvidenceReceipt` — the record a `status` transition to `contract_verified`
or later is checked against:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `receipt_id` | string | yes | Unique identifier. |
| `conformance_run_ref` | string | yes | Points back at the `ConformanceRun` this receipt evidences. |
| `claim` | string | yes | A one-sentence, human-readable statement of what this receipt verifies. |
| `runtime_verified` | boolean | yes | `true` only when this receipt is the direct product of a real, live call. `false` marks a design-time placeholder — a `false` receipt can never satisfy a `status` transition past `code_complete`. |
| `readback_result` | object or null | required when the operation's `effect` is `write`/`delete`/`share`/`admin` | The independent read-back confirming the write actually took effect; `null` is only valid for a read-only operation. |
| `negative_test_refs` | array | yes | Pointers at the negative-path test(s) this operation's conformance coverage includes (permission-denied, ACL-denied, idempotent-retry — at least one, chosen per the operation's own `effect`/`auth_modes`). |
| `cleanup_confirmed` | boolean | yes | Whether any test-state this run created was verified removed, not merely assumed removed. |

A validator can check every relationship stated above directly against these
two tables: whether a required field is present, whether `runtime_verified`
is `true` before a `status` transition depends on it, whether
`readback_result` is populated when `effect` demands it. That is the
structural contract this slice commits to shipping; the runner that
*produces* a real `ConformanceRun`/`EvidenceReceipt` is a distinct,
separately-scoped implementation round.

## The work-stream DAG

The connector campaign's work is sequenced into numbered streams, `W00`
through `W16`. This section is the authoritative numbering. **It supersedes
the numbering that an earlier campaign document
(`contract-and-dag.md`, §2) assigned** — that document remains accepted and is
not reopened for its other sections, but its §2 stream numbering is
superseded by this section wherever the two disagree.

### The numbering

| Stream | Scope |
|---|---|
| `W00` | Campaign contract and DAG (this document plus the manifest schema above) — the range and sequencing every other stream consumes. |
| `W01` | Shared control plane: binding, auth, policy, reliability. **`W01` is a prerequisite of every provider stream below it** — no provider stream starts ahead of `W01`. |
| `W02` | GitHub. |
| `W03` | Gmail, plus the shared Google auth layer Gmail and Drive both need. |
| `W04` | Google Drive: enumeration, content, metadata, delta (`drive.changes`), permissions/ACL, and upload (simple/multipart/resumable) against the Drive v3 API, sequenced after the Google auth contract in `W03` stabilizes. This scope is fixed by the campaign's own evidence catalog (the `google_drive` service-range operations); it is not open for this document to redefine, narrow, or leave unstated. |
| `W05` | The shared Microsoft Graph runtime base: the auth/token layer and the RUN-family mechanisms (pagination, rate-limit bucketing, write idempotency, concurrency/ETag handling) every Graph-backed stream below reuses rather than re-deriving. |
| `W06` | SharePoint and Outlook. |
| `W07` | OneDrive, OneNote, Teams, Excel, and the other Office capabilities. |
| `W08` | Asana. |
| `W09` | Slack. |
| `W10` | Salesforce. |
| `W11` | Zoom. |
| `W12` | The three cloud knowledge-base connectors: enumeration/content/metadata/delta/ACL for the cloud-KB-eligible providers. |
| `W13` | GitHub's and Salesforce's own structured data sources, treated as data sources in their own right — each provider's schema/object-model discovery, refresh/sync cadence, query interface, ACL model, and lineage tracking. Not a cross-provider scenario: GitHub's structured-data contract and Salesforce's structured-data contract are two independent deliverables inside this stream, each fully specified against its own provider's data model. |
| `W14` | Product entry points (surfaces) for the campaign's capabilities. |
| `W15` | Independent acceptance: conformance, scale, permissions, end-to-end. |
| `W16` | Release: migration, packaging, post-merge regression, final review. |

### The structural corrections this section makes

An earlier campaign document's DAG made errors this section corrects, stated
explicitly so a reader comparing the two documents can see exactly what
changed and why:

1. **Nine cross-cutting requirement families are not stream numbers.** AUTH,
   GOV, RUN, KB, ACL, DATA, UX, SURF, and OPS are requirement families that
   the provider streams *consume* — each family's contracts (e.g. `AUTH-01`
   through `AUTH-11`) are inputs a stream like `W02` or `W08` draws on, not
   streams themselves. An earlier revision assigned some of these family
   names to stream slots instead: governance to `W03`, generic runtime to
   `W05`, knowledge base to `W08`, ACL to `W09`, UX to `W10`, surfaces to
   `W11`, OPS to `W14`, and multi-account to `W13`. That assignment is
   corrected here for every family it misplaced. `W14`'s own meaning —
   product entry points — is not itself an error to correct: it is the
   original contract's correct definition for that slot, and this section
   preserves it; the error was OPS occupying that slot alongside it, not
   `W14`'s definition. `W02`–`W14` are provider streams, provider-group
   streams, or capability-delivery streams, full stop, and a requirement
   family is referenced from inside a stream's own dependency edges (see
   below), never given its own stream slot.
2. **`W01` is a prerequisite, not a sibling.** An earlier revision drew `W00`
   branching directly to `W02` through `W14`, bypassing `W01`. That is
   corrected here: every provider stream depends on `W01` first. `W01`
   establishes the shared binding/auth/policy/reliability control plane every
   provider stream's own contracts (its `AUTH-*`, `GOV-*`, `RUN-*` edges)
   assume is already in place.
3. **`W13` is not a cross-provider scenario.** An earlier revision described
   `W13` as a scenario spanning GitHub and Salesforce together. It is
   corrected here to what the campaign's own scope actually is: GitHub's
   structured-data source and Salesforce's structured-data source are each
   their own deliverable (schema, refresh, query, ACL, lineage, specified
   against that provider's own data model), sequenced in the same stream
   because they share no cross-provider interaction — describing them as one
   scenario implied a joint data flow between GitHub and Salesforce that this
   campaign does not define.
4. **`W04`'s scope is defined, not open.** An earlier revision of this
   document described `W04` as unscoped, deferring its definition to a
   future chartering step. That was incorrect: the user has already defined
   `W04`'s scope (Google Drive's enumeration/content/metadata/delta/
   permissions/upload surface, per the numbering table above), and this
   section states it rather than deferring it.

### Edges

Each edge names the specific contract or interface it depends on — never an
empty arrow between two stream numbers.

| Edge | Depends on |
|---|---|
| `W00 → W01` | The full required-range index this document and the campaign evidence catalog define (the acceptance index, the shared-contract families, the cross-service scenarios). `W01` consumes this range; it does not redefine it. |
| `W01 → W02..W14` (each provider stream) | The shared control-plane primitives `W01` produces: the binding/auth/policy/reliability contracts (`AUTH-*`, `GOV-*`, `RUN-*` family entries) each provider stream's own operations reference through their manifest `policy`/`auth_modes`/`retry` fields. |
| `W03 → W04` | Google's shared auth layer (the OAuth/token contract `W03` establishes for Gmail) is the same auth contract Drive's operations authenticate through — Drive does not derive a separate Google auth mechanism. |
| `W05 → W06` | The unified typed error taxonomy (`RUN-01`: auth/scope/consent/not-found/forbidden/quota/throttle/conflict/input/temporary/partial/ambiguous) must be a concrete module before `W06` can consume one error shape instead of mapping each vendor's native errors independently. |
| `W05 → W07` | The pagination (`RUN-02`), rate-limit bucketing (`RUN-03`), write idempotency (`RUN-04`), and concurrency/ETag (`RUN-05`) mechanisms must be concrete before `W07`'s operations can declare a real `pagination`/`retry` value rather than a placeholder. |
| `W04 + W05 → W12` | `W12` (the three cloud-KB connectors) needs both Drive's own concrete mechanism (`W04`) and the `RUN` family's concrete mechanism (`W05`). |
| `W06 + W07 → W12` | The SharePoint/OneDrive file-interface operations `W06` and `W07` establish (content, metadata, delta) are the concrete file surface `W12`'s cloud-KB coverage for the Microsoft-side providers consumes — `W12` does not re-derive a separate Microsoft file interface. |
| `W02 + W10 → W13` | `W13` needs GitHub's account-binding mechanism (`W02`) and Salesforce's (`W10`) both concrete before either provider's own structured-data contract (schema/refresh/query/ACL/lineage) can authenticate its calls. |
| every stream's ready operations → `W15` | Each operation flows into `W15` individually, the moment its own acceptance criterion is met — not gated on a whole stream finishing. |
| all required-live streams + `W15` → `W16` | `W16` is the final integration once every provider stream (`W02`, `W03`, `W05`, `W08`, `W09`, `W10`, `W11`, `W14`, plus the streams layered on them) has reached its own ready state and `W15` has completed independent acceptance. |

### What "the required range" means, and what this section does not claim

The operation and contract counts a reader will find in the campaign's
evidence catalog — 232 operations recorded directly, 40 more recorded as
demoted-but-tracked candidates, 1 contract-attachment entry (273 total), and
72 cross-cutting contract entries across the nine requirement families — are
**a snapshot of what one research pass has confirmed so far, not a proven
ceiling on the campaign's required scope.** This document does not restate
them as a completed denominator, and a future revision of this DAG must not
treat a renumbering as license to narrow them either. Two things are true at
once and this document holds both:

- **The user's own stated requirement is the boundary, not the catalog.** A
  service-range sweep is a derived lower bound built from what one pass
  managed to confirm; it is not the definition of what is required. Where
  the user has stated a requirement directly (a `source_status:
  user_required` manifest entry, or an explicit scope statement like this
  document's own `W04` correction above), that statement outranks anything a
  catalog sweep did or did not find.
- **A gap discovered on the same day the catalog was produced is a
  correction to that catalog, not a note for a future round.** If a
  same-day pass finds an operation the catalog missed, the fix is to add it
  to the required range now, not to file it as a follow-up gap ticket for a
  later slice to pick up. Deferring a same-day miss to "next round" is how a
  snapshot gets mistaken for a ceiling.

This document therefore states the range in two parts, both of which persist
across every future revision: the **known-required set** (what the catalog
and the user's own statements currently establish — the counts above), and
the **acknowledged-incomplete boundary** (the explicit fact that a
service-range sweep has not been proven exhaustive, so the true required set
may be larger than 273 operations / 72 contracts). Recording only the first
and dropping the second is what turns a snapshot into a false ceiling; this
spec keeps both stated, permanently, rather than treating "the catalog says
273" as itself the requirement.

## What this spec deliberately does not contain

- No validator implementation for the manifest schema above (the schema is
  specified structurally enough for one to be written directly against it).
- No provider-capabilities discovery runner implementation.
- No live conformance runner implementation (the `ConformanceRun` /
  `EvidenceReceipt` structural contract above is specified for a runner to
  target; the runner itself is a separate round).
- No specific manifest entries (which operations, which providers) — those
  live in the campaign's evidence catalog and are populated by a later round.

Each of these is a distinct, separately-accepted follow-up round, sequenced
by the DAG in this document.
