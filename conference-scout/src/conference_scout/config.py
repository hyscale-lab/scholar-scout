"""
Configuration module for Conference Scout.

This module defines the Pydantic models for loading and validating the application
configuration from a YAML file. It ensures that the configuration is well-formed
and provides type hints for better code completion and analysis.
"""

import os
from string import Template
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel


class SlackConfig(BaseModel):
    """Slack notifier configuration."""
    api_token: str
    default_channel_id: str


class GeminiConfig(BaseModel):
    """Gemini AI client configuration."""
    api_key: Union[str, dict]
    gen_ai_model: str = "gemini-2.5-flash"
    embedding_model: str = "gemini-embedding-001"


class ConferencesConfig(BaseModel):
    """Conference scraping configuration."""
    urls: List[str]
    max_volumes: int
    volume_date_filter_days: int
    semantic_scholar_api_key: Optional[str] = ""


class ResearchTopic(BaseModel):
    """Research topic configuration."""
    name: str
    keywords: List[str]
    description: str
    taxonomy: List[str]


class AppConfig(BaseModel):
    """Main application configuration."""
    slack: SlackConfig
    gemini: GeminiConfig
    conferences: ConferencesConfig
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
