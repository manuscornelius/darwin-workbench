"""
CIM - Common Information Model
===============================

Pydantic state model conforming to darwin://schemas/cim/v1.0.

The CIM is the engagement-level data contract. Every council agent reads and
writes state through this model. It captures:

  - What we're doing (implementation type, process scope)
  - For whom (engagement identifiers)
  - Against which systems (source + target platforms)
  - With what constraints (must-haves, complexity flags)
  - And where we are in the process (phase tracking)

This is v0.1 - intentionally a working skeleton. Fields will be added as
agent implementations reveal what they actually need. The schema version is
pinned; additive changes bump the minor, breaking changes bump the major
and require an ADR documenting the migration plan.

Spec references:
  - Section 02: "Full Pydantic model conforming to darwin://schemas/cim/v1.0"
  - Section 06: Hive output fields (derived from CIM via SELECT-not-FILTER)
  - Section 12: intake validates CIM completeness; extraction verifies
    CIM metrics against live EPM systems
  - Section 17: CIM occupies ~2000 tokens in assembled context
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


CIM_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ImplementationType(str, Enum):
    """What kind of engagement this is."""
    MIGRATION = "migration"
    GREENFIELD = "greenfield"
    EXTENSION = "extension"
    UPGRADE = "upgrade"


class OperationType(str, Enum):
    """One-time engagement vs recurring pipeline. See Section 01."""
    ENGAGEMENT = "engagement"
    PIPELINE = "pipeline"


class EPMPlatform(str, Enum):
    """Platforms covered by the unified tool registry.

    Codes match Section 13 (MCP Platform Coverage). Keep in sync with
    mcp/registry.yaml once that exists.
    """
    SAP_BPC_MS = "SAP_BPC_MS"
    SAP_BPC_NW = "SAP_BPC_NW"
    ONESTREAM = "ONESTREAM"
    TM1 = "TM1"
    VENA = "VENA"
    ANAPLAN = "ANAPLAN"
    TAGETIK = "TAGETIK"
    ORACLE_EPBCS = "ORACLE_EPBCS"
    ORACLE_HFM = "ORACLE_HFM"
    ORACLE_HYPERION = "ORACLE_HYPERION"
    SAP_SAC = "SAP_SAC"


class ProcessScope(str, Enum):
    """Business processes in scope for this engagement.

    Used for Hive aggregation (Section 06 process_scope field) - values
    must stay stable and non-identifying.
    """
    CONSOLIDATION = "consolidation"
    PLANNING = "planning"
    FORECASTING = "forecasting"
    REPORTING = "reporting"
    CLOSE = "close"
    ELIMINATION = "elimination"
    ALLOCATION = "allocation"
    INTERCOMPANY = "intercompany"
    CASH_FLOW = "cash_flow"
    ACCOUNT_RECONCILIATION = "account_reconciliation"


class ComplexityFlag(str, Enum):
    """Structural complexity markers used for execution tier routing
    and Hive telemetry (Section 06). Structural, never business-identifying.
    """
    MULTI_CURRENCY = "multi_currency"
    MULTI_GAAP = "multi_gaap"
    INTERCOMPANY = "intercompany"
    CASH_FLOW_STATEMENT = "cash_flow_statement"
    IFRS = "ifrs"
    US_GAAP = "us_gaap"
    MULTI_ENTITY_ROLLUP = "multi_entity_rollup"
    CUSTOM_CALC_LOGIC = "custom_calc_logic"
    HISTORICAL_RESTATEMENT = "historical_restatement"


class EngagementPhase(str, Enum):
    """Ordered phases a supervised engagement passes through.

    Maps to the council agent nodes in Section 12. Also the sort key in
    darwin-engagement-state (Section 23).
    """
    INTAKE = "intake"
    EXTRACTION = "extraction"
    TRANSFORMATION = "transformation"
    CODING = "coding"
    RISK = "risk"
    VALIDATION = "validation"
    DOCUMENTATION = "documentation"
    CLOSE = "close"


class MustHaveStatus(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    WAIVED = "waived"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    """Timezone-aware UTC now. Naive datetimes are a footgun."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Nested models
# ---------------------------------------------------------------------------

class PlatformRef(BaseModel):
    """Reference to an EPM platform involved in this engagement.

    credential_ref is a pointer into Secrets Manager (Section 04) - never
    the credential itself. Preserves the Prime Directive: Darwin Analytics
    never holds customer credentials in state.
    """
    model_config = ConfigDict(extra="forbid")

    platform: EPMPlatform
    version: str | None = None
    role: str = Field(..., description="'source' | 'target' | 'both'")
    credential_ref: str | None = Field(
        None,
        description="Secrets Manager path, e.g. 'darwin/acme/bpc_ms/prod'",
    )


class MustHave(BaseModel):
    """Acceptance criterion that must pass before engagement close."""
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    verification_method: str
    status: MustHaveStatus = MustHaveStatus.PENDING
    notes: str | None = None


class Risk(BaseModel):
    """Entry in the engagement's risk register."""
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    severity: RiskSeverity
    mitigation: str | None = None
    resolved: bool = False
    raised_at: datetime = Field(default_factory=_utcnow)


class PhaseTransition(BaseModel):
    """Audit record of a phase change - feeds the resumability check in
    AC-03 and the audit trail."""
    model_config = ConfigDict(extra="forbid")

    from_phase: EngagementPhase | None
    to_phase: EngagementPhase
    transitioned_at: datetime = Field(default_factory=_utcnow)
    agent: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------

class CIM(BaseModel):
    """Common Information Model - root engagement state.

    Mutations during graph execution should go through typed helpers
    (to be added as nodes are implemented) rather than direct attribute
    assignment, so the audit trail stays complete.
    """
    model_config = ConfigDict(extra="forbid")

    # --- Schema contract ---------------------------------------------------
    schema_version: str = Field(
        default=CIM_SCHEMA_VERSION,
        description="darwin://schemas/cim/{version}. Pinned for migration safety.",
    )

    # --- Identifiers -------------------------------------------------------
    engagement_id: str = Field(
        default_factory=lambda: f"eng_{uuid4().hex[:12]}",
        description="Anonymous engagement id. Never contains client info.",
    )
    workspace_id: str = Field(
        ...,
        description="Layer 2 workspace (org) this engagement belongs to.",
    )
    engagement_name: str = Field(
        ...,
        description="Human-readable name for UI. May contain client info "
                    "(stays workspace-local, never enters Hive).",
    )
    operation_type: OperationType = OperationType.ENGAGEMENT

    # --- Scope -------------------------------------------------------------
    implementation_type: ImplementationType
    process_scope: list[ProcessScope] = Field(default_factory=list)
    complexity_flags: list[ComplexityFlag] = Field(default_factory=list)

    # --- Client context ----------------------------------------------------
    entity_count: int | None = Field(
        None,
        ge=1,
        description="Actual entity count. NEVER sent to Hive - the Hive "
                    "receives entity_count_range (bucketed) only.",
    )
    fiscal_year_end_month: int | None = Field(None, ge=1, le=12)
    currencies: list[str] = Field(
        default_factory=list,
        description="ISO 4217 codes in scope, e.g. ['USD', 'EUR']",
    )

    # --- Platform inventory ------------------------------------------------
    platforms: list[PlatformRef] = Field(default_factory=list)

    # --- Engagement execution state ---------------------------------------
    current_phase: EngagementPhase = EngagementPhase.INTAKE
    phase_history: list[PhaseTransition] = Field(default_factory=list)

    # --- Quality & governance ---------------------------------------------
    must_haves: list[MustHave] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)

    # --- Audit hooks (filled by infrastructure) ---------------------------
    prompt_versions_used: dict[str, str] = Field(
        default_factory=dict,
        description="{agent_name: prompt_version} stamped per Bedrock call.",
    )
    approved_models_used: list[str] = Field(default_factory=list)
    token_usage_by_agent: dict[str, int] = Field(default_factory=dict)

    # --- Timestamps --------------------------------------------------------
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # --- Pragmatic escape hatch -------------------------------------------
    # Fields promoted to the root schema should bump CIM_SCHEMA_VERSION.
    # This avoids blocking agent development on schema debates.
    extensions: dict[str, Any] = Field(default_factory=dict)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def entity_count_range(self) -> str | None:
        """Bucketed entity count for Hive telemetry (Section 06).

        Returns None if entity_count isn't set. Bucketing is intentionally
        coarse to prevent triangulation of customer identity.
        """
        if self.entity_count is None:
            return None
        n = self.entity_count
        if n <= 10:
            return "1_10"
        if n <= 50:
            return "11_50"
        if n <= 200:
            return "51_200"
        if n <= 1000:
            return "201_1000"
        return "1001_plus"

    def advance_phase(
        self,
        to_phase: EngagementPhase,
        agent: str,
        reason: str | None = None,
    ) -> None:
        """Transition to a new phase and record the transition."""
        self.phase_history.append(
            PhaseTransition(
                from_phase=self.current_phase,
                to_phase=to_phase,
                agent=agent,
                reason=reason,
            )
        )
        self.current_phase = to_phase
        self.updated_at = _utcnow()
