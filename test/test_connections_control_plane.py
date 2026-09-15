"""Contract, fault, and negative tests for the W01 control-plane seam.

The seam is pure types and zero IO, so these tests check the three things a
type-only single-source has to guarantee: the enum closed sets match the
manifest verbatim (contract), a reflected credential in an error ``detail`` is
scrubbed under the shared discipline (fault), and the additive-only /
no-credential / two-axis invariants hold (negative).
"""

from __future__ import annotations

import pytest

from kiro_crew import connections
from kiro_crew.connections import control_plane as cp
from kiro_crew.connections.control_plane import (
    CREDENTIAL_MODES,
    EFFECTS,
    ERROR_CLASSES,
    MAX_ERROR_CHARS,
    OPERATION_KINDS,
    RESULT_STATUSES,
    SERVICE_IDS,
    OperationContext,
    OperationDescriptor,
    OperationError,
    OperationResult,
    operation_error,
    redacted_detail,
)

# The closed sets as the owning spec (connector-capability-manifest.md) fixes
# them. Duplicated here on purpose: a test that imported the same tuple it
# checks would pass even if a value were silently dropped from both.
_MANIFEST_OPERATION_KINDS = ("single_fetch", "list", "search", "mutation", "stream")
_MANIFEST_EFFECTS = ("read", "write", "delete", "share", "external_send", "admin", "billable")
_MANIFEST_SERVICE_IDS = (
    "github",
    "gmail",
    "google_drive",
    "sharepoint",
    "outlook",
    "onedrive",
    "onenote",
    "teams",
    "excel_shared_engine",
    "office_documents",
    "slack",
    "asana",
    "salesforce",
    "zoom",
)
_RUN01_ERROR_CLASSES = (
    "auth",
    "scope",
    "consent",
    "not_found",
    "forbidden",
    "quota",
    "throttle",
    "conflict",
    "input",
    "temporary",
    "partial",
    "ambiguous",
)
_CREDENTIAL_MODES = ("oauth_user", "fine_grained_pat", "service_to_service")

# The exact set of names ``kiro_crew.connections.__all__`` published BEFORE this
# slice, frozen here as in-repo data rather than read from a git ref. This slice
# is additive-only over the connections export face (16 in-repo modules import
# it), and freezing the baseline as a literal makes that invariant explicit and
# independent of git state -- a shallow/detached CI checkout cannot resolve
# ``origin/main``, so a ref-based baseline would fail to read (exit 128) rather
# than test anything. If a future slice legitimately adds an export, this set
# grows in the same commit; a value must never be REMOVED from it.
_BASE_CONNECTIONS_EXPORTS = frozenset(
    {
        "AUTH_MODE_DCR",
        "AUTH_MODE_PREREGISTERED",
        "CALLBACK_PATH",
        "L0_VERIFICATION_MAX_AGE_DAYS",
        "L0_VERIFICATION_WARN_AGE_DAYS",
        "AuthConfig",
        "L0Expectations",
        "Provider",
        "REGISTRY_PATH",
        "REVOKE_VERIFICATION_MAX_AGE_DAYS",
        "RegistryValidationError",
        "SmokeFixture",
        "auth_mode",
        "declared_tool_aliases",
        "derived_alias",
        "exposed_declared_tools",
        "get_all_providers",
        "get_all_registry_providers",
        "get_preregistered_providers",
        "get_provider",
        "get_tier",
        "get_visible_providers",
        "is_local_host",
        "is_preregistered",
        "natural_tool_names",
        "redirect_uri",
        "resolve_tool_aliases",
        "stale_l0_baselines",
        "statically_visible_tool_names",
    }
)


# --- Contract --------------------------------------------------------------


def test_operation_kinds_match_manifest_verbatim() -> None:
    assert OPERATION_KINDS == _MANIFEST_OPERATION_KINDS


def test_effects_match_manifest_verbatim() -> None:
    assert EFFECTS == _MANIFEST_EFFECTS


def test_service_ids_match_manifest_verbatim() -> None:
    assert SERVICE_IDS == _MANIFEST_SERVICE_IDS


def test_run01_error_classes_are_the_twelve_value_closed_set() -> None:
    assert ERROR_CLASSES == _RUN01_ERROR_CLASSES
    assert len(ERROR_CLASSES) == 12


def test_credential_mode_is_the_three_value_axis_b_set() -> None:
    assert CREDENTIAL_MODES == _CREDENTIAL_MODES


def test_result_status_success_axis_is_ok_and_partial() -> None:
    assert RESULT_STATUSES == ("ok", "partial")


def test_every_module_carries_a_schema_version_constant() -> None:
    # The precedent l0_probe/l1_smoke/status all pin a module-level version.
    assert cp.OPERATION_SCHEMA_VERSION >= 1
    assert cp.CONTEXT_SCHEMA_VERSION >= 1
    assert cp.RESULT_SCHEMA_VERSION >= 1
    assert cp.ERRORS_SCHEMA_VERSION >= 1


def test_typed_dicts_have_every_declared_field() -> None:
    descriptor: OperationDescriptor = {
        "operation_id": "github.list_issues",
        "service_id": "github",
        "operation_kind": "list",
        "effect": "read",
        "credential_mode": "oauth_user",
    }
    assert set(descriptor) == set(OperationDescriptor.__annotations__)

    context: OperationContext = {
        "binding_ref": "binding://gh/acct-1",
        "tenant_ref": "tenant://org-1",
        "subject_ref": "subject://user-1",
        "deadline": 1_800_000_000.0,
    }
    assert set(context) == set(OperationContext.__annotations__)

    result: OperationResult = {"status": "partial", "next_cursor": "opaque-cursor"}
    assert set(result) == set(OperationResult.__annotations__)

    error: OperationError = operation_error("throttle", "slow down")
    assert set(error) == set(OperationError.__annotations__)


# --- Fault -----------------------------------------------------------------


def test_reflected_credential_in_detail_is_redacted() -> None:
    leaked = "github pat ghp_" + "a" * 40 + " was rejected"
    error = operation_error("auth", leaked)
    assert "ghp_" + "a" * 40 not in error["detail"]
    assert error["error_class"] == "auth"


def test_detail_is_redacted_before_truncation_not_after() -> None:
    # A credential straddling the cap must not survive as a bisected prefix:
    # redaction runs over the whole string first.
    secret = "ghp_" + "z" * 40
    detail = "x" * (MAX_ERROR_CHARS - 4) + secret
    out = redacted_detail(detail)
    assert secret not in out
    assert secret[:8] not in out  # not even a bisected prefix leaks


def test_detail_is_capped_at_max_error_chars() -> None:
    out = redacted_detail("y" * 5000)
    assert len(out) <= MAX_ERROR_CHARS


def test_operation_error_never_stores_raw_detail() -> None:
    # The constructor redacts on the way in; there is no un-redacted path.
    exfil = "authorization: Bearer sk-live-" + "q" * 32
    error = operation_error("forbidden", exfil)
    assert "sk-live-" + "q" * 32 not in error["detail"]


# --- Negative --------------------------------------------------------------


def test_connections_all_is_additive_only_over_the_base() -> None:
    # Every export the base __init__ published must still be published: the 16
    # in-repo importers of kiro_crew.connections must not break. Baseline is a
    # frozen in-repo literal (see _BASE_CONNECTIONS_EXPORTS) -- not a git ref,
    # which a shallow CI checkout cannot resolve.
    now_all = set(connections.__all__)
    missing = _BASE_CONNECTIONS_EXPORTS - now_all
    assert missing == set(), f"an existing connections export was removed: {sorted(missing)}"


def test_registration_mode_api_is_untouched() -> None:
    # Axis A stays exactly where it was; the seam adds Axis B without moving it.
    assert connections.AUTH_MODE_DCR == "dcr"
    assert connections.AUTH_MODE_PREREGISTERED == "preregistered"
    assert callable(connections.auth_mode)
    assert callable(connections.is_preregistered)


def test_container_anchor_is_vendors_not_providers() -> None:
    import kiro_crew.connections.vendors as vendors

    assert vendors.__name__.endswith(".vendors")
    with pytest.raises(ModuleNotFoundError):
        __import__("kiro_crew.connections.providers")


def test_context_fields_are_references_typed_as_str() -> None:
    # The four context fields are references; three are str, deadline is a float
    # timestamp. None is a credential-value type. This pins the "refs, never a
    # token value" invariant at the type level.
    from typing import get_type_hints

    hints = get_type_hints(OperationContext)
    assert hints["binding_ref"] is str
    assert hints["tenant_ref"] is str
    assert hints["subject_ref"] is str
    assert hints["deadline"] is float


def test_success_partial_and_error_partial_are_distinct_concepts() -> None:
    # result.partial (usable-but-incomplete success) and errors.partial
    # (a failure that partially applied) share a word, not a set.
    assert "partial" in RESULT_STATUSES
    assert "partial" in ERROR_CLASSES
    assert set(RESULT_STATUSES).isdisjoint(set(ERROR_CLASSES) - {"partial"})
