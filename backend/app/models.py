from datetime import datetime, timezone
from typing import Optional

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Merchant(SQLModel, table=True):
    id: str = Field(primary_key=True)
    shop_name: str
    owner_name: str  # synthetic
    category: str
    city: str  # Noida / Delhi NCR
    locality: str = ""  # e.g. "Sector 62"
    lat: float
    lng: float
    turnover_band: str
    in_ckycr: bool = False
    qr_status: str = "PAUSED"  # PAUSED | IN_PROGRESS | LIVE | ESCALATED
    has_soundbox: bool = True
    monthly_gmv: float = 0
    subscription_per_month: float = 0
    has_active_loan: bool = False
    loan_outstanding: float = 0  # rupees; 0 when no active loan
    paused_since: Optional[NaiveDatetime] = None  # local (IST) wall-clock
    hourly_txn_histogram: list = Field(default_factory=list, sa_column=Column(JSON))  # 7x24 counts
    open_hours: dict = Field(default_factory=dict, sa_column=Column(JSON))
    risk_features: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # payer_diversity, spike_ratio, round_amount_share, night_share
    docs_status: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Employee(SQLModel, table=True):
    id: str = Field(primary_key=True)  # E01..E06
    name: str  # synthetic
    home_base: str
    home_lat: float
    home_lng: float


class Journey(SQLModel, table=True):
    merchant_id: str = Field(primary_key=True, foreign_key="merchant.id")
    current_step: str = "TRIAGE"
    priority_score: float = 0
    priority_reasons: list = Field(default_factory=list, sa_column=Column(JSON))
    mule_risk_score: float = 0
    visit_slot: Optional[NaiveDatetime] = None
    assigned_employee: Optional[str] = None
    attempts: dict = Field(default_factory=dict, sa_column=Column(JSON))  # per channel
    escalation_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    merchant_id: str = Field(index=True, foreign_key="merchant.id")
    doc_type: str  # PAN | FORM60 | OVD | CKYCR (a fetched CKYCR record, not an upload)
    file_path: str
    extracted_fields: dict = Field(default_factory=dict, sa_column=Column(JSON))
    quality_metrics: dict = Field(default_factory=dict, sa_column=Column(JSON))
    decision: str = "REJECTED"  # ACCEPTED | REJECTED
    reason: Optional[str] = None
    attempt_no: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class Visit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    merchant_id: str = Field(index=True, foreign_key="merchant.id")
    employee_id: str
    scheduled_at: NaiveDatetime
    route_order: int = 0
    geo_tag: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    signboard_photo: Optional[str] = None
    confirmed_by: Optional[str] = None
    completed_at: Optional[NaiveDatetime] = None


class AuditEntry(SQLModel, table=True):
    # one successor per entry: two processes appending at once cannot fork a merchant's chain
    __table_args__ = (UniqueConstraint("merchant_id", "prev_hash"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    merchant_id: str = Field(index=True)
    ts: datetime = Field(default_factory=utcnow)
    actor: str  # agent | llm | policy | rules_engine | human:<name> | system
    action: str
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    prev_hash: str = ""
    hash: str = ""


class ReviewCase(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    merchant_id: str = Field(index=True, foreign_key="merchant.id")
    reason: str
    evidence: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "OPEN"  # OPEN | DECIDED
    decided_by: Optional[str] = None
    decision: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class ChatMessage(SQLModel, table=True):
    """WhatsApp / IVR traffic with the shopkeeper; the ShopSimulator renders this."""
    id: Optional[int] = Field(default=None, primary_key=True)
    merchant_id: str = Field(index=True)
    ts: datetime = Field(default_factory=utcnow)
    sender: str  # agent | shopkeeper
    channel: str  # WHATSAPP | IVR
    text_hi: str = ""
    text_en: str = ""
    attachment: Optional[str] = None  # uploaded file path
    meta: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Event(SQLModel, table=True):
    """Outbox for /api/events (SSE). A table, not an in-memory queue, so the MCP tool process can publish too."""
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow)
    type: str
    merchant_id: Optional[str] = Field(default=None, index=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))


class SimClock(SQLModel, table=True):
    """Simulated wall clock (naive IST) for retries and visit booking. Single row, id 1."""
    id: int = Field(default=1, primary_key=True)
    now: NaiveDatetime
