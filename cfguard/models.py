"""Shared, immutable evidence and configuration records. No provider I/O."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping


def _utc(*values):
    for value in values:
        if value is not None and (value.tzinfo is None or value.utcoffset().total_seconds() != 0):
            raise ValueError("evidence timestamps must be timezone-aware UTC")


@dataclass(frozen=True)
class ResourceKey:
    account_id: str
    scope: str
    product: str
    resource_id: str | None = None
    zone_id: str | None = None

    def __post_init__(self):
        if not self.account_id or not self.product or self.scope not in {"account", "zone", "resource"}:
            raise ValueError("invalid evidence identity")
        if (self.scope == "account" and (self.resource_id is not None or self.zone_id is not None)
                or self.scope == "zone" and (not self.zone_id or self.resource_id is not None)
                or self.scope == "resource" and (not self.resource_id or self.zone_id is not None)):
            raise ValueError("scope and identity disagree")


@dataclass(frozen=True)
class Observation:
    key: ResourceKey
    metric: str
    value: Decimal | None
    unit: str
    period_start: datetime
    period_end: datetime
    fetched_at: datetime
    data_through: datetime | None
    quality: str
    source: str
    complete: bool
    sampled: bool | None

    def __post_init__(self):
        _utc(self.period_start, self.period_end, self.fetched_at, self.data_through)
        if self.period_start >= self.period_end:
            raise ValueError("empty observation window")


@dataclass(frozen=True)
class RatedCharge:
    key: ResourceKey
    source_key: str
    amount: Decimal | None
    kind: str
    currency: str
    period_start: datetime
    period_end: datetime
    source: str
    quality: str

    def __post_init__(self):
        _utc(self.period_start, self.period_end)
        if self.period_start >= self.period_end:
            raise ValueError("empty charge window")


@dataclass(frozen=True)
class Subscription:
    key: ResourceKey
    source_key: str
    name: str
    amount: Decimal | None
    currency: str
    allowed: bool | None
    quality: str = "good"


@dataclass(frozen=True)
class Snapshot:
    account_id: str
    observations: tuple[Observation, ...]
    rated_charges: tuple[RatedCharge, ...]
    subscriptions: tuple[Subscription, ...]
    coverage: Mapping[str, str]
    collected_at: datetime

    def __post_init__(self):
        _utc(self.collected_at)


@dataclass(frozen=True)
class Decision:
    key: ResourceKey
    status: str
    reason_code: str
    proposed_action: str | None = None
    evidence_ids: tuple[str, ...] = ()
    metric: str = ""
    value: Decimal | None = None
    unit: str = ""
    currency: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None


@dataclass(frozen=True)
class ActionPlan:
    key: ResourceKey
    action: str
    baseline_digest: str
    approval_reference: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ActionResult:
    key: ResourceKey
    status: str
    observed_endpoint_flags: Mapping[str, bool | None]
    verification: Mapping[str, object]
    attempt_id: str


@dataclass(frozen=True)
class ResourceState:
    status: str = "healthy"
    execution_status: str = "not_requested"
    notification_status: str = "not_requested"
    dimensions: Mapping[str, str] = field(default_factory=dict)
    incident_id: str | None = None


@dataclass(frozen=True)
class Threshold:
    metric: str
    limit: Decimal
    unit: str
    warning: Decimal | None = None


@dataclass(frozen=True)
class Price:
    metric: str
    unit: str
    currency: str
    amount: Decimal
    per_quantity: Decimal
    allowance: Decimal
    source: str
    as_of: str


@dataclass(frozen=True)
class AccountConfig:
    key: str
    account_id: str
    read_token_file: Path
    billing_day: int
    budget: Decimal
    currency: str
    expected_subscriptions: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()
    prices: tuple[Price, ...] = ()
    max_data_age_seconds: int = 900
    billing_period_verified: bool = False


@dataclass(frozen=True)
class ResourceConfig:
    key: ResourceKey
    name: str
    zones: tuple[str, ...] = ()
    hostnames: tuple[str, ...] = ()
    thresholds: tuple[Threshold, ...] = ()
    permitted_action: str | None = None
    executor_token_file: Path | None = None
    approved_manifest_file: Path | None = None
    approved_manifest_digest: str | None = None


@dataclass(frozen=True)
class Config:
    mode: str = "observe"
    accounts: tuple[AccountConfig, ...] = ()
    resources: tuple[ResourceConfig, ...] = ()
    state_dir: Path = Path("/var/lib/cloudflare-cost-guard")
    notification: Mapping[str, object] | None = None
    run_timeout_seconds: int = 240
    heartbeat_max_age_seconds: int = 660
