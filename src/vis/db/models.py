from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, JSONType


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- access / users -----------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    password_hash: Mapped[str] = mapped_column(String(256), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    permissions: Mapped[list | None] = mapped_column(JSONType, default=list)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)


# --- products / recipes (versioned) -------------------------------------------
class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (UniqueConstraint("product_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/approved/retired
    image_rotation: Mapped[int] = mapped_column(Integer, default=0)
    camera_settings: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_signature_id: Mapped[int | None] = mapped_column(ForeignKey("esignatures.id"))
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
    regions: Mapped[list["RegionRow"]] = relationship(
        cascade="all, delete-orphan", back_populates="recipe"
    )


class RegionRow(Base):
    __tablename__ = "regions"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"))
    key: Mapped[str] = mapped_column(String(64))  # region_id string
    name: Mapped[str] = mapped_column(String(128), default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    roi: Mapped[dict] = mapped_column(JSONType)
    reject_output: Mapped[str] = mapped_column(String(64), default="default")
    pass_logic: Mapped[str] = mapped_column(String(8), default="all")
    fixture: Mapped[dict | None] = mapped_column(JSONType, default=None)  # part locator
    recipe: Mapped[Recipe] = relationship(back_populates="regions")
    tools: Mapped[list["ToolRow"]] = relationship(
        cascade="all, delete-orphan", back_populates="region"
    )


class ToolRow(Base):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"))
    key: Mapped[str] = mapped_column(String(64))  # tool_id string
    tool_type: Mapped[str] = mapped_column(String(32))
    roi: Mapped[dict] = mapped_column(JSONType)
    config: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    region: Mapped[RegionRow] = relationship(back_populates="tools")


# --- batches / results --------------------------------------------------------
class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"))
    recipe_version: Mapped[int | None] = mapped_column(Integer)
    batch_no: Mapped[str] = mapped_column(String(64))
    mfg_date: Mapped[str | None] = mapped_column(String(16))
    exp_date: Mapped[str | None] = mapped_column(String(16))
    mrp: Mapped[str | None] = mapped_column(String(32))
    variable_data: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    # operator-entered reconciliation figures (units_in, samples_removed,
    # recovered, destroyed, reject_bin_count, tolerance_pct) — see db/reconciliation
    recon_data: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    # OEE parameters (target_rate_per_min for the ideal cycle time) — see db/oee
    oee_data: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open")
    started_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
    closed_at: Mapped[str | None] = mapped_column(String(40))


class InspectionResult(Base):
    __tablename__ = "inspection_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    camera_id: Mapped[str] = mapped_column(String(64))
    frame_id: Mapped[int] = mapped_column(Integer)
    region_key: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    reject_output: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
    tool_results: Mapped[list["ToolResultRow"]] = relationship(
        cascade="all, delete-orphan", back_populates="inspection"
    )


class ToolResultRow(Base):
    __tablename__ = "tool_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_result_id: Mapped[int] = mapped_column(ForeignKey("inspection_results.id"))
    tool_key: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    measured_value: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    inspection: Mapped[InspectionResult] = relationship(back_populates="tool_results")
    code_read: Mapped["CodeReadRow | None"] = relationship(
        cascade="all, delete-orphan", back_populates="tool_result", uselist=False
    )
    grade: Mapped["GradeResultRow | None"] = relationship(
        cascade="all, delete-orphan", back_populates="tool_result", uselist=False
    )


class CodeReadRow(Base):
    __tablename__ = "code_reads"
    id: Mapped[int] = mapped_column(primary_key=True)
    tool_result_id: Mapped[int] = mapped_column(ForeignKey("tool_results.id"))
    symbology: Mapped[str | None] = mapped_column(String(32))
    raw_data: Mapped[str | None] = mapped_column(Text)
    # Parsed GS1 AIs — the serialization-ready hook (Phase 2 reads from here).
    gtin: Mapped[str | None] = mapped_column(String(32))
    batch: Mapped[str | None] = mapped_column(String(64))
    expiry: Mapped[str | None] = mapped_column(String(16))
    serial: Mapped[str | None] = mapped_column(String(64))
    tool_result: Mapped[ToolResultRow] = relationship(back_populates="code_read")


class GradeResultRow(Base):
    __tablename__ = "grade_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    tool_result_id: Mapped[int] = mapped_column(ForeignKey("tool_results.id"))
    iso_standard: Mapped[str] = mapped_column(String(32), default="approx")
    overall_grade: Mapped[str | None] = mapped_column(String(4))
    certified: Mapped[bool] = mapped_column(Boolean, default=False)  # always False inline (D-012)
    parameters: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    tool_result: Mapped[ToolResultRow] = relationship(back_populates="grade")


# --- integrity (Part 11) ------------------------------------------------------
class ESignature(Base):
    __tablename__ = "esignatures"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    meaning: Mapped[str] = mapped_column(String(128))
    ts: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    signature_id: Mapped[int | None] = mapped_column(ForeignKey("esignatures.id"))
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))


class DowntimeEvent(Base):
    """A line stop with a classified reason (OEE Six Big Losses). Auto-opened
    when the line stops running and closed when it resumes; the operator picks
    the reason. oee_component is which OEE factor the loss hits."""

    __tablename__ = "downtime_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    station: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(48))
    oee_component: Mapped[str] = mapped_column(String(16), default="availability")
    note: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
    ended_at: Mapped[str | None] = mapped_column(String(40))
    duration_s: Mapped[float | None] = mapped_column(Float)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DefectLibraryItem(Base):
    """A catalogued known-defect sample used for challenge tests (e.g. wrong
    GTIN, expired date, no code, low-grade print). expected_verdict is what the
    system must return when this sample is presented (normally 'reject')."""

    __tablename__ = "defect_library"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True)
    defect_class: Mapped[str] = mapped_column(String(48), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    expected_verdict: Mapped[str] = mapped_column(String(8), default="reject")  # reject/pass
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class ChallengeTest(Base):
    """A challenge (known-bad sample) verification test: prove the system detects
    and physically rejects seeded defects, recorded with an operator e-signature
    and gating the line. trigger_reason ∈ line_start/batch_start/shift_start/
    shift_end/after_break/after_changeover/after_maintenance/periodic."""

    __tablename__ = "challenge_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_reason: Mapped[str] = mapped_column(String(24), default="line_start")
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"))
    recipe_version: Mapped[int | None] = mapped_column(Integer)
    station: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(8), default="pending")  # pass/fail/pending
    line_gate_action: Mapped[str | None] = mapped_column(String(16))  # unlocked/blocked
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    signature_id: Mapped[int | None] = mapped_column(ForeignKey("esignatures.id"))
    started_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
    completed_at: Mapped[str | None] = mapped_column(String(40))
    shots: Mapped[list["ChallengeShot"]] = relationship(
        cascade="all, delete-orphan", back_populates="test"
    )


class ChallengeShot(Base):
    """One presented sample within a challenge test: the expected vs actual
    verdict and whether the 24V reject actuator physically confirmed."""

    __tablename__ = "challenge_shots"
    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("challenge_tests.id"))
    defect_item_id: Mapped[int | None] = mapped_column(ForeignKey("defect_library.id"))
    label: Mapped[str] = mapped_column(String(96), default="")
    expected_verdict: Mapped[str] = mapped_column(String(8), default="reject")
    actual_verdict: Mapped[str] = mapped_column(String(8), default="")
    reject_io_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    test: Mapped[ChallengeTest] = relationship(back_populates="shots")


class SerialRecord(Base):
    """A unique serial seen within a batch (pharma serialization). The unique
    (batch_id, serial) constraint is the anti-duplicate control: a second sight
    of the same serial in a batch is a duplicate (printer double-fire, reprint,
    or counterfeit re-injection). status drives batch-close reconciliation."""

    __tablename__ = "serial_records"
    __table_args__ = (UniqueConstraint("batch_id", "serial"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    serial: Mapped[str] = mapped_column(String(64))
    gtin: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="good")  # good/rejected/duplicate
    camera_id: Mapped[str | None] = mapped_column(String(64))
    first_frame: Mapped[int | None] = mapped_column(Integer)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class AuditReview(Base):
    """A review-by-exception of the audit trail (21 CFR 11 / Annex 11 / PIC-S
    PI 041): a qualified reviewer signs off the audit entries for a batch/window
    before disposition. Itself an attributable, e-signed record. The watermark
    (reviewed_to_id = last audit-entry id covered) makes the next review
    incremental. chain_verified records verify_chain() over the window."""

    __tablename__ = "audit_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    scope: Mapped[str] = mapped_column(String(16), default="batch")  # batch/period
    reviewed_from_id: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_to_id: Mapped[int] = mapped_column(Integer, default=0)
    entries_total: Mapped[int] = mapped_column(Integer, default=0)
    entries_flagged: Mapped[int] = mapped_column(Integer, default=0)
    chain_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    flags: Mapped[list | None] = mapped_column(JSONType, default=list)
    outcome: Mapped[str] = mapped_column(String(24), default="accepted")
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    signature_id: Mapped[int | None] = mapped_column(ForeignKey("esignatures.id"))
    ruleset_version: Mapped[str] = mapped_column(String(16), default="v1")
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class SettingRow(Base):
    """Application key/value settings (JSON values) — e.g. comms config."""

    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class EventRow(Base):
    """Operational event/alarm log (run/stop, alarms, batch events) — the
    line-side log operators read, distinct from the Part-11 audit trail."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
    severity: Mapped[str] = mapped_column(String(8), default="info")  # info/warn/alarm
    source: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))


class FontModelRow(Base):
    """A trained OCV font: per-character glyph templates for one print
    technology/size (docs/11-ocv-fonts.md). glyphs = {char: [b64 PNG, ...]}."""

    __tablename__ = "font_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(96), unique=True)
    print_type: Mapped[str] = mapped_column(String(24), default="cij")
    dot_kernel: Mapped[int] = mapped_column(Integer, default=0)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    glyphs: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


# --- station / hardware config ------------------------------------------------
class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    line: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class CameraRow(Base):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    name: Mapped[str] = mapped_column(String(64))
    identifier: Mapped[str] = mapped_column(String(128), default="")  # IP / serial
    vendor: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    interface: Mapped[str] = mapped_column(String(32), default="GigE Vision")
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)  # CameraSettings.to_dict()
    default_recipe_id: Mapped[int | None] = mapped_column(Integer)  # recipe this camera runs


class RejectOutputRow(Base):
    __tablename__ = "reject_outputs"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    name: Mapped[str] = mapped_column(String(64))  # lane name (== region.reject_output)
    channel: Mapped[int] = mapped_column(Integer)
    eject_delay_ms: Mapped[int] = mapped_column(Integer, default=0)
    pulse_ms: Mapped[int] = mapped_column(Integer, default=100)


class LightOutputRow(Base):
    __tablename__ = "light_outputs"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    name: Mapped[str] = mapped_column(String(64))
    channel: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)  # LightSettings.to_dict()


class CameraAssignment(Base):
    """Binds a camera to the recipe it runs for a batch (multi-camera run)."""

    __tablename__ = "camera_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    recipe_ref: Mapped[str] = mapped_column(String(64))  # recipe identifier
    recipe_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)


class FrameCapture(Base):
    """One acquired frame's provenance + optional archived image path."""

    __tablename__ = "frame_captures"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    camera_id: Mapped[str] = mapped_column(String(64))  # camera_id string from the frame
    frame_id: Mapped[int] = mapped_column(Integer)
    image_ref: Mapped[str | None] = mapped_column(String(256))  # filesystem path, not a blob
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow_iso)
