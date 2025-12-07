#!/usr/bin/env python3
"""
Script to run the Scholar Scout MCP Server.

This script initializes and starts the MCP server, which can then be
connected to by MCP clients (like Claude Desktop or other AI assistants).

Usage:
    python scripts/run_mcp_server.py [--config CONFIG_FILE]

Environment Variables:
    GMAIL_USERNAME: Gmail account username
    GMAIL_APP_PASSWORD: Gmail app-specific password
    PPLX_API_KEY: Perplexity AI API key
    SLACK_API_TOKEN: Slack API token
"""

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from scholar_scout.mcp_server import ScholarScoutMCPServer


def main():
    """Main entry point for the MCP server script."""
    parser = argparse.ArgumentParser(
        description="Run the Scholar Scout MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default configuration
  python scripts/run_mcp_server.py
  
  # Run with custom configuration file
  python scripts/run_mcp_server.py --config my_config.yml
  
  # Run with debug logging
  python scripts/run_mcp_server.py --debug

Environment variables must be set in .env file or exported:
  GMAIL_USERNAME, GMAIL_APP_PASSWORD, PPLX_API_KEY, SLACK_API_TOKEN
        """
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yml",
        help="Path to configuration file (default: config/config.yml)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Verify required environment variables
    required_env_vars = [
        "GMAIL_USERNAME",
        "GMAIL_APP_PASSWORD", 
        "PPLX_API_KEY",
        "SLACK_API_TOKEN"
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set them in your .env file or environment")
        sys.exit(1)
    
    # Verify configuration file exists
    if not os.path.exists(args.config):
        logger.error(f"Configuration file not found: {args.config}")
        logger.error("Please create a configuration file based on config.example.yml")
        sys.exit(1)
    
    logger.info(f"Starting Scholar Scout MCP Server")
    logger.info(f"Configuration: {args.config}")
    logger.info(f"Debug mode: {'enabled' if args.debug else 'disabled'}")
    
    try:
        # Create and run the MCP server
        server = ScholarScoutMCPServer(config_path=args.config)
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

