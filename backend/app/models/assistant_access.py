"""Additive pilot access metadata; existing assistant ledgers stay unchanged."""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.assistant import TABLE_OPTIONS


class AssistantPolicy(Base):
    __tablename__ = 'assistant_policies'
    __table_args__ = (UniqueConstraint('version', name='uq_assistant_policies_version'), TABLE_OPTIONS)
    version: Mapped[str] = mapped_column(String(64, collation='utf8mb4_bin'), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sql_text('0'), index=True)


class AssistantAccess(Base):
    __tablename__ = 'assistant_access'
    __table_args__ = (UniqueConstraint('user_id', name='uq_assistant_access_user_id'),
        CheckConstraint('generation >= 1', name='ck_assistant_access_generation'), TABLE_OPTIONS)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sql_text('0'))
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sql_text('1'))


class AssistantConsent(Base):
    __tablename__ = 'assistant_consents'
    __table_args__ = (UniqueConstraint('user_id', 'generation', 'policy_id', name='uq_assistant_consents_binding'), TABLE_OPTIONS)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_id: Mapped[int] = mapped_column(ForeignKey('assistant_policies.id'), nullable=False, index=True)


class AssistantRunAccess(Base):
    __tablename__ = 'assistant_run_access'
    __table_args__ = (UniqueConstraint('run_id', name='uq_assistant_run_access_run_id'), TABLE_OPTIONS)
    run_id: Mapped[int] = mapped_column(ForeignKey('assistant_runs.id', ondelete='CASCADE'), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_id: Mapped[int] = mapped_column(ForeignKey('assistant_policies.id'), nullable=False, index=True)
