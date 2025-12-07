"""
MCP Server for Scholar Scout

This module implements a Model Context Protocol (MCP) server that exposes
Scholar Scout functionality as resources and tools. It allows AI assistants
and other clients to interact with the Scholar Scout system through a
standardized protocol.

The server provides:
- Resources: Access to emails, papers, and configuration
- Tools: Execute classification, notifications, and workflows
- Prompts: Pre-defined prompts for paper classification
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
from pydantic import AnyUrl

from .classifier import ScholarClassifier
from .config import load_config, AppConfig
from .email_client import EmailClient
from .models import Paper
from .notifications import SlackNotifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ScholarScoutMCPServer:
    """
    MCP Server implementation for Scholar Scout.
    
    This class manages the state and handles requests for the Scholar Scout
    MCP server, providing access to email fetching, paper classification,
    and notification sending capabilities.
    """
    
    def __init__(self, config_path: str = "config/config.yml"):
        """
        Initialize the MCP server.
        
        Args:
            config_path: Path to the configuration file
        """
        self.config: AppConfig = load_config(config_path)
        self.server = Server("scholar-scout")
        
        # Cache for storing fetched emails and classified papers
        # This helps avoid refetching data for multiple requests
        self._email_cache: List[Any] = []
        self._paper_cache: List[tuple[Paper, List[Any]]] = []
        self._cache_timestamp: Optional[datetime] = None
        
        # Register handlers
        self._register_resources()
        self._register_tools()
        self._register_prompts()
        
        logger.info("Scholar Scout MCP Server initialized")
    
    def _register_resources(self):
        """
        Register all resources that can be accessed through the MCP protocol.
        
        Resources are read-only data sources that clients can query.
        They provide access to emails, papers, and configuration data.
        """
        
        @self.server.list_resources()
        async def list_resources() -> list[Resource]:
            """
            List all available resources.
            
            Returns:
                A list of Resource objects describing available data sources
            """
            return [
                Resource(
                    uri=AnyUrl("scholar://emails/list"),
                    name="Scholar Emails",
                    description="List of Google Scholar alert emails from Gmail",
                    mimeType="application/json"
                ),
                Resource(
                    uri=AnyUrl("scholar://papers/recent"),
                    name="Recent Papers",
                    description="Recently classified research papers with their topics",
                    mimeType="application/json"
                ),
                Resource(
                    uri=AnyUrl("scholar://topics/config"),
                    name="Research Topics Configuration",
                    description="Configuration of research topics and keywords being tracked",
                    mimeType="application/json"
                ),
            ]
        
        @self.server.read_resource()
        async def read_resource(uri: AnyUrl) -> str:
            """
            Read and return the content of a specific resource.
            
            Args:
                uri: The URI of the resource to read
                
            Returns:
                The resource content as a JSON string
                
            Raises:
                ValueError: If the URI is not recognized
            """
            uri_str = str(uri)
            logger.info(f"Reading resource: {uri_str}")
            
            if uri_str == "scholar://emails/list":
                # Fetch emails if not cached or cache is old (> 5 minutes)
                if not self._email_cache or self._is_cache_stale():
                    await self._refresh_email_cache()
                
                # Return email metadata (not full content to keep response size manageable)
                email_list = []
                for idx, email_msg in enumerate(self._email_cache):
                    email_list.append({
                        "index": idx,
                        "subject": email_msg.get("subject", "No subject"),
                        "from": email_msg.get("from", "Unknown"),
                        "date": email_msg.get("date", "Unknown date"),
                    })
                
                return json.dumps({
                    "emails": email_list,
                    "count": len(email_list),
                    "last_updated": self._cache_timestamp.isoformat() if self._cache_timestamp else None
                }, indent=2)
            
            elif uri_str == "scholar://papers/recent":
                # Return cached classified papers
                papers_list = []
                for paper, topics in self._paper_cache:
                    papers_list.append({
                        "title": paper.title,
                        "authors": paper.authors,
                        "abstract": paper.abstract[:200] + "..." if len(paper.abstract) > 200 else paper.abstract,
                        "venue": paper.venue,
                        "url": paper.url,
                        "topics": [topic.name for topic in topics]
                    })
                
                return json.dumps({
                    "papers": papers_list,
                    "count": len(papers_list),
                    "last_updated": self._cache_timestamp.isoformat() if self._cache_timestamp else None
                }, indent=2)
            
            elif uri_str == "scholar://topics/config":
                # Return research topics configuration
                topics_config = []
                for topic in self.config.research_topics:
                    topics_config.append({
                        "name": topic.name,
                        "description": topic.description,
                        "keywords": topic.keywords,
                        "slack_channel": topic.slack_channel,
                        "slack_users": topic.slack_users
                    })
                
                return json.dumps({
                    "topics": topics_config,
                    "count": len(topics_config)
                }, indent=2)
            
            else:
                raise ValueError(f"Unknown resource URI: {uri_str}")
    
    def _register_tools(self):
        """
        Register all tools that can be executed through the MCP protocol.
        
        Tools are functions that perform actions like fetching emails,
        classifying papers, or sending notifications.
        """
        
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """
            List all available tools.
            
            Returns:
                A list of Tool objects describing available functions
            """
            return [
                Tool(
                    name="fetch_emails",
                    description=(
                        "Fetch Google Scholar alert emails from Gmail. "
                        "This retrieves new emails based on configured filters and time windows."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "force_refresh": {
                                "type": "boolean",
                                "description": "Force refresh even if cache is recent",
                                "default": False
                            }
                        }
                    }
                ),
                Tool(
                    name="classify_papers",
                    description=(
                        "Parse and classify research papers from fetched emails using AI. "
                        "This extracts paper metadata and matches them to configured research topics."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "fetch_first": {
                                "type": "boolean",
                                "description": "Fetch fresh emails before classifying",
                                "default": False
                            }
                        }
                    }
                ),
                Tool(
                    name="send_notifications",
                    description=(
                        "Send Slack notifications for classified papers. "
                        "This notifies configured users and channels about matching papers."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "weekly_update": {
                                "type": "boolean",
                                "description": "Send as weekly summary instead of individual notifications",
                                "default": False
                            }
                        }
                    }
                ),
                Tool(
                    name="run_pipeline",
                    description=(
                        "Run the complete Scholar Scout pipeline: "
                        "fetch emails → classify papers → send notifications. "
                        "This is the full automated workflow."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "weekly_update": {
                                "type": "boolean",
                                "description": "Send weekly summary instead of individual notifications",
                                "default": True
                            },
                            "delete_old_emails": {
                                "type": "boolean",
                                "description": "Delete old emails after processing",
                                "default": True
                            }
                        }
                    }
                ),
                Tool(
                    name="get_paper_details",
                    description=(
                        "Get detailed information about a specific paper by its index or title. "
                        "Returns full abstract and classification details."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "index": {
                                "type": "integer",
                                "description": "Index of the paper in the recent papers list"
                            },
                            "title": {
                                "type": "string",
                                "description": "Title of the paper to search for (partial match)"
                            }
                        }
                    }
                ),
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
            """
            Execute a tool with the given arguments.
            
            Args:
                name: The name of the tool to execute
                arguments: Dictionary of arguments for the tool
                
            Returns:
                A sequence of content objects with the tool's results
                
            Raises:
                ValueError: If the tool name is not recognized
            """
            logger.info(f"Calling tool: {name} with arguments: {arguments}")
            
            if name == "fetch_emails":
                return await self._tool_fetch_emails(arguments)
            elif name == "classify_papers":
                return await self._tool_classify_papers(arguments)
            elif name == "send_notifications":
                return await self._tool_send_notifications(arguments)
            elif name == "run_pipeline":
                return await self._tool_run_pipeline(arguments)
            elif name == "get_paper_details":
                return await self._tool_get_paper_details(arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")
    
    def _register_prompts(self):
        """
        Register pre-defined prompts for common tasks.
        
        Prompts provide templates that can be used by AI assistants
        to perform paper classification and analysis.
        """
        
        @self.server.list_prompts()
        async def list_prompts() -> list[dict]:
            """
            List all available prompts.
            
            Returns:
                A list of prompt definitions
            """
            return [
                {
                    "name": "classify_paper",
                    "description": "Classify a research paper into relevant topics",
                    "arguments": [
                        {
                            "name": "paper_title",
                            "description": "Title of the paper",
                            "required": True
                        },
                        {
                            "name": "paper_abstract",
                            "description": "Abstract of the paper",
                            "required": True
                        }
                    ]
                }
            ]
    
    # Tool implementation methods
    
    async def _tool_fetch_emails(self, arguments: dict) -> Sequence[TextContent]:
        """
        Implementation of the fetch_emails tool.
        
        Fetches Google Scholar alert emails from Gmail and updates the cache.
        
        Args:
            arguments: Tool arguments (force_refresh)
            
        Returns:
            Results of the email fetching operation
        """
        force_refresh = arguments.get("force_refresh", False)
        
        # Check if we need to refresh
        if not force_refresh and not self._is_cache_stale() and self._email_cache:
            return [TextContent(
                type="text",
                text=f"Using cached emails ({len(self._email_cache)} emails). Last fetched: {self._cache_timestamp}"
            )]
        
        # Fetch fresh emails
        await self._refresh_email_cache()
        
        return [TextContent(
            type="text",
            text=f"Successfully fetched {len(self._email_cache)} emails from Gmail"
        )]
    
    async def _tool_classify_papers(self, arguments: dict) -> Sequence[TextContent]:
        """
        Implementation of the classify_papers tool.
        
        Parses emails and classifies papers using AI.
        
        Args:
            arguments: Tool arguments (fetch_first)
            
        Returns:
            Results of the classification operation
        """
        fetch_first = arguments.get("fetch_first", False)
        
        if fetch_first:
            await self._refresh_email_cache()
        
        if not self._email_cache:
            return [TextContent(
                type="text",
                text="No emails available. Please fetch emails first."
            )]
        
        # Classify papers
        classifier = ScholarClassifier(self.config)
        
        # Run classification in thread pool since it's blocking
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            classifier.classify_papers,
            self._email_cache
        )
        
        self._paper_cache = results
        self._cache_timestamp = datetime.now()
        
        # Summarize results
        total_papers = len(results)
        papers_by_topic = {}
        for paper, topics in results:
            for topic in topics:
                if topic.name not in papers_by_topic:
                    papers_by_topic[topic.name] = []
                papers_by_topic[topic.name].append(paper.title)
        
        summary = f"Successfully classified {total_papers} papers\n\n"
        summary += "Papers by topic:\n"
        for topic_name, papers in papers_by_topic.items():
            summary += f"\n{topic_name} ({len(papers)} papers):\n"
            for title in papers[:3]:  # Show first 3 papers per topic
                summary += f"  - {title}\n"
            if len(papers) > 3:
                summary += f"  ... and {len(papers) - 3} more\n"
        
        return [TextContent(type="text", text=summary)]
    
    async def _tool_send_notifications(self, arguments: dict) -> Sequence[TextContent]:
        """
        Implementation of the send_notifications tool.
        
        Sends Slack notifications for classified papers.
        
        Args:
            arguments: Tool arguments (weekly_update)
            
        Returns:
            Results of the notification operation
        """
        weekly_update = arguments.get("weekly_update", False)
        
        if not self._paper_cache:
            return [TextContent(
                type="text",
                text="No classified papers available. Please classify papers first."
            )]
        
        notifier = SlackNotifier(self.config.slack)
        
        if weekly_update:
            # Send weekly summary
            papers_by_topic = {}
            for paper, topics in self._paper_cache:
                for topic in topics:
                    if topic.name not in papers_by_topic:
                        papers_by_topic[topic.name] = []
                    papers_by_topic[topic.name].append(paper)
            
            # Run in thread pool since it's blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                notifier.send_weekly_update,
                papers_by_topic
            )
            
            return [TextContent(
                type="text",
                text=f"Successfully sent weekly update for {len(papers_by_topic)} topics"
            )]
        else:
            # Send individual notifications
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                notifier.notify_matches,
                self._paper_cache
            )
            
            return [TextContent(
                type="text",
                text=f"Successfully sent notifications for {len(self._paper_cache)} papers"
            )]
    
    async def _tool_run_pipeline(self, arguments: dict) -> Sequence[TextContent]:
        """
        Implementation of the run_pipeline tool.
        
        Runs the complete Scholar Scout workflow.
        
        Args:
            arguments: Tool arguments (weekly_update, delete_old_emails)
            
        Returns:
            Results of the complete pipeline execution
        """
        weekly_update = arguments.get("weekly_update", True)
        delete_old = arguments.get("delete_old_emails", True)
        
        results = []
        
        # Step 1: Fetch emails
        await self._refresh_email_cache()
        results.append(f"✓ Fetched {len(self._email_cache)} emails")
        
        # Step 2: Delete old emails if requested
        if delete_old:
            with EmailClient(self.config.email) as email_client:
                email_client.delete_old_emails()
            results.append("✓ Deleted old emails")
        
        # Step 3: Classify papers
        if self._email_cache:
            classifier = ScholarClassifier(self.config)
            loop = asyncio.get_event_loop()
            classified_results = await loop.run_in_executor(
                None,
                classifier.classify_papers,
                self._email_cache
            )
            self._paper_cache = classified_results
            self._cache_timestamp = datetime.now()
            results.append(f"✓ Classified {len(classified_results)} papers")
        else:
            results.append("⚠ No emails to classify")
            return [TextContent(type="text", text="\n".join(results))]
        
        # Step 4: Send notifications
        if self._paper_cache:
            notifier = SlackNotifier(self.config.slack)
            
            if weekly_update:
                papers_by_topic = {}
                for paper, topics in self._paper_cache:
                    for topic in topics:
                        if topic.name not in papers_by_topic:
                            papers_by_topic[topic.name] = []
                        papers_by_topic[topic.name].append(paper)
                
                await loop.run_in_executor(
                    None,
                    notifier.send_weekly_update,
                    papers_by_topic
                )
                results.append(f"✓ Sent weekly update for {len(papers_by_topic)} topics")
            else:
                await loop.run_in_executor(
                    None,
                    notifier.notify_matches,
                    self._paper_cache
                )
                results.append(f"✓ Sent notifications for {len(self._paper_cache)} papers")
        else:
            results.append("⚠ No papers to notify")
        
        return [TextContent(type="text", text="\n".join(results))]
    
    async def _tool_get_paper_details(self, arguments: dict) -> Sequence[TextContent]:
        """
        Implementation of the get_paper_details tool.
        
        Gets detailed information about a specific paper.
        
        Args:
            arguments: Tool arguments (index or title)
            
        Returns:
            Detailed information about the requested paper
        """
        if not self._paper_cache:
            return [TextContent(
                type="text",
                text="No papers available. Please run classification first."
            )]
        
        paper_info = None
        
        if "index" in arguments:
            idx = arguments["index"]
            if 0 <= idx < len(self._paper_cache):
                paper, topics = self._paper_cache[idx]
                paper_info = (paper, topics)
        
        elif "title" in arguments:
            search_title = arguments["title"].lower()
            for paper, topics in self._paper_cache:
                if search_title in paper.title.lower():
                    paper_info = (paper, topics)
                    break
        
        if not paper_info:
            return [TextContent(
                type="text",
                text="Paper not found. Please check the index or title."
            )]
        
        paper, topics = paper_info
        details = f"""
Title: {paper.title}

Authors: {', '.join(paper.authors)}

Venue: {paper.venue}

URL: {paper.url}

Matched Topics: {', '.join([t.name for t in topics])}

Abstract:
{paper.abstract}
"""
        
        return [TextContent(type="text", text=details.strip())]
    
    # Helper methods
    
    def _is_cache_stale(self) -> bool:
        """
        Check if the cache is stale (older than 5 minutes).
        
        Returns:
            True if cache should be refreshed, False otherwise
        """
        if not self._cache_timestamp:
            return True
        
        age = (datetime.now() - self._cache_timestamp).total_seconds()
        return age > 300  # 5 minutes
    
    async def _refresh_email_cache(self):
        """
        Refresh the email cache by fetching from Gmail.
        
        This method runs the blocking email fetch operation in a thread pool
        to avoid blocking the async event loop.
        """
        def fetch_emails():
            with EmailClient(self.config.email) as email_client:
                return email_client.fetch_scholar_alerts()
        
        # Run in thread pool since it's blocking I/O
        loop = asyncio.get_event_loop()
        emails = await loop.run_in_executor(None, fetch_emails)
        
        self._email_cache = emails
        self._cache_timestamp = datetime.now()
        logger.info(f"Email cache refreshed: {len(emails)} emails")
    
    async def run(self):
        """
        Start the MCP server and listen for requests.
        
        This method runs the server using stdio transport, which allows
        communication through standard input/output streams.
        """
        logger.info("Starting Scholar Scout MCP Server...")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


async def main():
    """
    Main entry point for running the MCP server.
    
    This function creates and runs the Scholar Scout MCP server.
    """
    server = ScholarScoutMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())

