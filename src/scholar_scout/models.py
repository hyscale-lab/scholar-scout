"""
Data models for Scholar Scout.

This module defines the Pydantic models for representing the core data
structures used in the application, such as research papers.
"""

from typing import List
from pydantic import BaseModel


class Paper(BaseModel):
    """
    Represents a research paper with its metadata.

    Attributes:
        title: Paper title
        authors: List of author names
        abstract: Paper abstract
        url: Link to the paper (optional)
        venue: Publication venue (optional)
    """

    title: str
    authors: List[str]
    abstract: str
    url: str = ""
    venue: str = ""
