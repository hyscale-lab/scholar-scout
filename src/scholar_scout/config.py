"""
Configuration module for Scholar Scout.

This module defines the Pydantic models for loading and validating the application
configuration from a YAML file. It ensures that the configuration is well-formed
and provides type hints for better code completion and analysis.
"""

import os
from string import Template
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel, Field


class EmailConfig(BaseModel):
    """Email server configuration."""

    username: str
    password: str
    folder: str = "INBOX"


class SlackConfig(BaseModel):
    """Slack notifier configuration."""

    api_token: str
    default_channel: str
    pending_user_id: Optional[str] = Field(default=None, pattern=r"^U[A-Z0-9]+$")


class GeminiConfig(BaseModel):
    """Gemini AI client configuration."""

    api_key: Union[str, dict]
    gen_ai_model: str = "gemini-3.8-flash"


class ResearchTopic(BaseModel):
    """Research topic configuration."""

    name: str
    slack_users: List[str]
    slack_channel: Optional[str] = None


class StateStorageConfig(BaseModel):
    branch: str = Field(default="scholar-state", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    file: str = Field(default="state.json", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.json$")


class PendingPolicy(BaseModel):
    max_attempts: int = Field(default=5, ge=1)
    max_age_days: int = Field(default=30, ge=1)


class SourceRecoveryConfig(BaseModel):
    max_rounds: int = Field(default=2, ge=0)
    max_wait_seconds: float = Field(default=180, ge=0, allow_inf_nan=False)


class AppConfig(BaseModel):
    """Main application configuration."""

    email: EmailConfig
    slack: SlackConfig
    gemini: GeminiConfig
    research_topics: List[ResearchTopic]
    state_storage: StateStorageConfig = Field(default_factory=StateStorageConfig)
    pending_policy: PendingPolicy = Field(default_factory=PendingPolicy)
    source_recovery: SourceRecoveryConfig = Field(default_factory=SourceRecoveryConfig)
    state_dir: str = ".scholar-scout"


def load_config(config_file: str = "config/config.yml") -> AppConfig:
    """
    Load and process the configuration file with environment variable substitution.

    Args:
        config_file: Path to the YAML configuration file.

    Returns:
        AppConfig: The parsed and validated configuration.
    """
    with open(config_file) as f:
        template = Template(f.read())

    config_str = template.safe_substitute(os.environ)
    config_data = yaml.safe_load(config_str)

    return AppConfig(**config_data)
