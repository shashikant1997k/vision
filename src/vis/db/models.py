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


class RejectOutputRow(Base):
    __tablename__ = "reject_outputs"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    name: Mapped[str] = mapped_column(String(64))  # lane name (== region.reject_output)
    channel: Mapped[int] = mapped_column(Integer)
    eject_delay_ms: Mapped[int] = mapped_column(Integer, default=0)
    pulse_ms: Mapped[int] = mapped_column(Integer, default=100)
