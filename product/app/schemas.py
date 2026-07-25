from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


EngineChoice = Literal["auto", "codex", "api"]
ReviewMode = Literal["single", "team"]


class Profile(BaseModel):
    owner_name: str = Field(default="老板", max_length=30)
    primary_markets: list[str] = Field(default_factory=lambda: ["A股", "港股"], max_length=10)
    reference_markets: list[str] = Field(default_factory=lambda: ["美股", "日本", "韩国"], max_length=10)
    focus_sectors: list[str] = Field(default_factory=list, max_length=20)
    analysis_framework: str = Field(
        default="全球局势 → 市场 → 板块 → 公司 → 估值与验证信号",
        max_length=300,
    )
    reference_investors: list[str] = Field(default_factory=list, max_length=20)
    investment_horizon: str = Field(default="长期为主", max_length=100)
    risk_preference: str = Field(default="稳健", max_length=300)
    preferred_metrics: list[str] = Field(default_factory=list, max_length=20)
    excluded_sectors: list[str] = Field(default_factory=list, max_length=20)
    report_style: str = Field(default="先给结论，再给证据和风险", max_length=300)
    data_permissions: list[str] = Field(default_factory=list, max_length=20)
    privacy_boundaries: list[str] = Field(default_factory=list, max_length=20)
    report_time: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    auto_brief_enabled: bool = False
    last_auto_brief_date: str = ""

    @field_validator(
        "primary_markets",
        "reference_markets",
        "focus_sectors",
        "reference_investors",
        "preferred_metrics",
        "excluded_sectors",
        "data_permissions",
        "privacy_boundaries",
    )
    @classmethod
    def clean_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class WatchlistCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=80)
    market: Literal["A股", "港股", "美股", "日本", "韩国", "其他"]
    thesis: str = Field(default="", max_length=800)
    notes: str = Field(default="", max_length=1200)


class ResearchRequest(BaseModel):
    question: str = Field(default="", max_length=5000)
    context: str = Field(default="", max_length=10000)
    watchlist_id: int | None = None
    engine: EngineChoice = "auto"
    review_mode: ReviewMode = "single"


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", max_length=100)
    watchlist_id: int | None = None


class ConversationMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    use_web: bool = True
    engine: EngineChoice = "auto"


class ScheduledJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    job_type: Literal["hourly_news", "daily_brief", "weekly_review", "company_tracking"] = "daily_brief"
    frequency: Literal["interval", "daily", "weekly", "monthly", "yearly"]
    interval_minutes: int = Field(default=60, ge=15, le=10080)
    time_of_day: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int = Field(default=-1, ge=-1, le=6)
    day_of_month: int = Field(default=1, ge=1, le=28)
    month_of_year: int = Field(default=1, ge=1, le=12)
    active_start: str = Field(default="00:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    active_end: str = Field(default="23:59", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    enabled: bool = False
    prompt: str = Field(default="", max_length=3000)
    engine: EngineChoice = "auto"
    frameworks: list[str] = Field(default_factory=list, max_length=10)
    watchlist_id: int | None = None

    @field_validator("frameworks")
    @classmethod
    def clean_frameworks(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class ScheduledJobUpdate(ScheduledJobCreate):
    pass


class CompanyResearchRequest(BaseModel):
    company: str = Field(min_length=1, max_length=100)
    symbol: str = Field(default="", max_length=30)
    market: str = Field(default="", max_length=30)
    context: str = Field(default="", max_length=10000)
    engine: EngineChoice = "auto"
    watchlist_id: int | None = None
    review_mode: ReviewMode = "single"


class CompanyTrackingUpdate(BaseModel):
    enabled: bool = False
    frequency: Literal["daily", "weekly", "monthly", "yearly"] = "weekly"
    time_of_day: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int = Field(default=0, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=28)
    month_of_year: int = Field(default=1, ge=1, le=12)
    engine: EngineChoice = "auto"
    frameworks: list[str] = Field(default_factory=list, max_length=10)


class HypothesisCreate(BaseModel):
    watchlist_id: int
    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(default="", max_length=3000)
    status: Literal["tracking", "supported", "challenged", "invalidated", "closed"] = "tracking"
    support_evidence: list[str] = Field(default_factory=list, max_length=30)
    counter_evidence: list[str] = Field(default_factory=list, max_length=30)
    validation_signals: list[str] = Field(default_factory=list, max_length=30)
    invalidation_signals: list[str] = Field(default_factory=list, max_length=30)
    next_review_at: str = Field(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$")

    @field_validator(
        "support_evidence",
        "counter_evidence",
        "validation_signals",
        "invalidation_signals",
    )
    @classmethod
    def clean_hypothesis_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class HypothesisUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(default="", max_length=3000)
    status: Literal["tracking", "supported", "challenged", "invalidated", "closed"] = "tracking"
    support_evidence: list[str] = Field(default_factory=list, max_length=30)
    counter_evidence: list[str] = Field(default_factory=list, max_length=30)
    validation_signals: list[str] = Field(default_factory=list, max_length=30)
    invalidation_signals: list[str] = Field(default_factory=list, max_length=30)
    next_review_at: str = Field(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$")

    @field_validator(
        "support_evidence",
        "counter_evidence",
        "validation_signals",
        "invalidation_signals",
    )
    @classmethod
    def clean_hypothesis_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class ReportEnvelope(BaseModel):
    id: int
    report_type: str
    title: str
    query: str
    content: str
    sources: list[dict[str, str]]
    model: str
    engine: str
    status: str
    created_at: str
