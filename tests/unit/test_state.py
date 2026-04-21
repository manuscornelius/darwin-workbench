"""Unit tests for orchestration.state (CIM v0.1)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestration.state import (
    CIM,
    EPMPlatform,
    EngagementPhase,
    ImplementationType,
    PlatformRef,
)


def test_cim_minimal_construction() -> None:
    """A CIM can be created with only the required fields."""
    cim = CIM(
        workspace_id="ws_test_001",
        engagement_name="Test engagement",
        implementation_type=ImplementationType.MIGRATION,
    )
    assert cim.schema_version == "1.0"
    assert cim.engagement_id.startswith("eng_")
    assert cim.current_phase == EngagementPhase.INTAKE
    assert cim.operation_type.value == "engagement"
    assert cim.phase_history == []
    assert cim.must_haves == []


def test_entity_count_range_bucketing() -> None:
    """The bucketing helper enforces Hive Prime Directive at the model level."""
    def _range(n: int | None) -> str | None:
        cim = CIM(
            workspace_id="ws_test_001",
            engagement_name="Test",
            implementation_type=ImplementationType.MIGRATION,
            entity_count=n,
        )
        return cim.entity_count_range()

    assert _range(None) is None
    assert _range(1) == "1_10"
    assert _range(10) == "1_10"
    assert _range(11) == "11_50"
    assert _range(47) == "11_50"
    assert _range(200) == "51_200"
    assert _range(500) == "201_1000"
    assert _range(5000) == "1001_plus"


def test_advance_phase_records_transition() -> None:
    """advance_phase() records the transition for the audit trail."""
    cim = CIM(
        workspace_id="ws_test_001",
        engagement_name="Test",
        implementation_type=ImplementationType.MIGRATION,
    )
    assert len(cim.phase_history) == 0

    cim.advance_phase(
        to_phase=EngagementPhase.EXTRACTION,
        agent="intake",
        reason="CIM validated, proceeding to source extraction",
    )

    assert cim.current_phase == EngagementPhase.EXTRACTION
    assert len(cim.phase_history) == 1
    assert cim.phase_history[0].from_phase == EngagementPhase.INTAKE
    assert cim.phase_history[0].to_phase == EngagementPhase.EXTRACTION
    assert cim.phase_history[0].agent == "intake"


def test_extra_forbid_catches_typos() -> None:
    """extra='forbid' on PlatformRef rejects unknown fields at construction."""
    with pytest.raises(ValidationError):
        PlatformRef(
            platform=EPMPlatform.SAP_BPC_MS,
            role="source",
            typo_field="should fail",  # type: ignore[call-arg]
        )


def test_extra_forbid_on_root_cim() -> None:
    """extra='forbid' on CIM root also rejects unknown fields."""
    with pytest.raises(ValidationError):
        CIM(  # type: ignore[call-arg]
            workspace_id="ws_test_001",
            engagement_name="Test",
            implementation_type=ImplementationType.MIGRATION,
            unknown_field="oops",
        )


def test_engagement_id_is_anonymous() -> None:
    """engagement_id must not leak any caller-supplied info by default."""
    cim = CIM(
        workspace_id="ws_acme_corp",
        engagement_name="Acme Q4 close migration",
        implementation_type=ImplementationType.MIGRATION,
    )
    # Anonymous format: eng_<12 hex chars>
    assert cim.engagement_id.startswith("eng_")
    assert len(cim.engagement_id) == len("eng_") + 12
    # Must not contain anything from workspace_id or engagement_name
    assert "acme" not in cim.engagement_id.lower()
