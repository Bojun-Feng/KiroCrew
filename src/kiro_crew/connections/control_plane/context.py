"""W01 · L01: the per-call context a connector operation is dispatched with.

Where :mod:`kiro_crew.connections.control_plane.operation` describes what is
true of an operation in the abstract, this module carries the four things that
vary from one invocation to the next: which binding, which tenant, which
subject, and by when.

**Every field is a REFERENCE, never a value.** This is the load-bearing
invariant of the whole seam and it follows directly from the subsystem's
credential boundary -- "Kiro Crew never holds a connection's credential"
(``connections.md``). A context object is passed around, logged, and may end up
in an error's structured detail, so it must not be able to carry a token, a
client secret, a bearer, or any credential plaintext. ``binding_ref`` names an
authorized account/tenant binding (the same "never a raw credential" discipline
the manifest's ``ConformanceRun.account_binding_ref`` states); ``tenant_ref``
and ``subject_ref`` name a tenant and a subject; none of the three is the thing
it points at. A future leaf resolves a ref to a live credential inside kiro-cli
custody -- that resolution is explicitly NOT in this slice, and nothing here
reads or holds what it would return.

``deadline`` is an absolute wall-clock cutoff expressed as a POSIX timestamp
(seconds since the epoch, UTC), not a relative budget: a relative duration
would restart every time the context crossed a hop, and the point of a deadline
is that it does not. It is a plain float so this module stays dependency-free
and zero-IO; the code that eventually enforces it (a later leaf) converts it to
whatever its clock wants.
"""

from __future__ import annotations

from typing import TypedDict

#: Bumped when this context's shape changes, mirroring the module-level
#: schema-version constant the sibling result / operation modules carry.
CONTEXT_SCHEMA_VERSION = 1


class OperationContext(TypedDict):
    """The references one operation invocation is dispatched under.

    A ``TypedDict`` with every field present, matching the sibling descriptors'
    shape. All four fields are references (see the module docstring): a context
    NEVER carries a token value or any credential plaintext.

    ``binding_ref`` -- an authorized account/tenant binding reference (never a
    raw credential). ``tenant_ref`` -- the tenant this call acts within.
    ``subject_ref`` -- the subject (user/principal) on whose behalf it acts.
    ``deadline`` -- an absolute POSIX-seconds UTC cutoff for the call.
    """

    binding_ref: str
    tenant_ref: str
    subject_ref: str
    deadline: float
