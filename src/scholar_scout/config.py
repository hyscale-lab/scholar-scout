"""
Configuration module for Scholar Scout.

This module defines the Pydantic models for loading and validating the application
configuration from a YAML file. It ensures that the configuration is well-formed
and provides type hints for better code completion and analysis.
"""

import os
from string import Template
from typing import Dict, List, Optional

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
    channel_topics: Dict[str, List[str]] = Field(default_factory=dict)


class PerplexityConfig(BaseModel):
    """Perplexity AI client configuration."""
    api_key: str
    model: str = "sonar-pro"


class ResearchTopic(BaseModel):
    """Research topic configuration."""
    name: str
    keywords: List[str]
    slack_users: List[str]
    slack_channel: Optional[str] = None
    description: str


class AppConfig(BaseModel):
    """Main application configuration."""
    email: EmailConfig
    slack: SlackConfig
    perplexity: PerplexityConfig
    research_topics: List[ResearchTopic]


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
