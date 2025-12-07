#!/usr/bin/env python3
"""
Test script for the Scholar Scout MCP Server.

This script provides a simple way to test the MCP server functionality
without needing a full MCP client like Claude Desktop.

Usage:
    python scripts/test_mcp_server.py [--test-all | --test-resources | --test-tools]
"""

import argparse
import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from scholar_scout.mcp_server import ScholarScoutMCPServer


async def test_resources(server: ScholarScoutMCPServer):
    """Test all available resources."""
    print("\n" + "="*60)
    print("Testing Resources")
    print("="*60)
    
    resources = [
        "scholar://emails/list",
        "scholar://papers/recent",
        "scholar://topics/config"
    ]
    
    for resource_uri in resources:
        print(f"\n📖 Testing resource: {resource_uri}")
        try:
            from pydantic import AnyUrl
            content = await server.server._read_resource_handler(AnyUrl(resource_uri))
            data = json.loads(content)
            print(f"✓ Success! Retrieved {len(data)} fields")
            print(f"  Preview: {json.dumps(data, indent=2)[:200]}...")
        except Exception as e:
            print(f"✗ Error: {e}")


async def test_tools(server: ScholarScoutMCPServer):
    """Test available tools."""
    print("\n" + "="*60)
    print("Testing Tools")
    print("="*60)
    
    # Test 1: Fetch emails
    print("\n🛠️  Testing tool: fetch_emails")
    try:
        results = await server._tool_fetch_emails({"force_refresh": True})
        for result in results:
            print(f"✓ {result.text}")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    # Test 2: Classify papers (only if we have emails)
    if server._email_cache:
        print("\n🛠️  Testing tool: classify_papers")
        try:
            results = await server._tool_classify_papers({"fetch_first": False})
            for result in results:
                print(f"✓ {result.text}")
        except Exception as e:
            print(f"✗ Error: {e}")
    else:
        print("\n⚠️  Skipping classify_papers (no emails available)")
    
    # Test 3: Get paper details (if we have papers)
    if server._paper_cache:
        print("\n🛠️  Testing tool: get_paper_details")
        try:
            results = await server._tool_get_paper_details({"index": 0})
            for result in results:
                print(f"✓ Retrieved paper details:")
                print(f"  {result.text[:300]}...")
        except Exception as e:
            print(f"✗ Error: {e}")
    else:
        print("\n⚠️  Skipping get_paper_details (no papers available)")


async def test_integration(server: ScholarScoutMCPServer):
    """Test the complete pipeline."""
    print("\n" + "="*60)
    print("Testing Complete Pipeline")
    print("="*60)
    
    print("\n🚀 Running complete pipeline (without notifications)")
    print("   This will:")
    print("   1. Fetch emails from Gmail")
    print("   2. Classify papers using AI")
    print("   3. Display summary (skip notifications)")
    
    try:
        # Fetch emails
        print("\n[1/3] Fetching emails...")
        await server._refresh_email_cache()
        print(f"✓ Fetched {len(server._email_cache)} emails")
        
        # Classify papers
        if server._email_cache:
            print("\n[2/3] Classifying papers...")
            from scholar_scout.classifier import ScholarClassifier
            classifier = ScholarClassifier(server.config)
            
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                classifier.classify_papers,
                server._email_cache
            )
            server._paper_cache = results
            
            print(f"✓ Classified {len(results)} papers")
            
            # Display summary
            print("\n[3/3] Summary by topic:")
            papers_by_topic = {}
            for paper, topics in results:
                for topic in topics:
                    if topic.name not in papers_by_topic:
                        papers_by_topic[topic.name] = []
                    papers_by_topic[topic.name].append(paper.title)
            
            for topic_name, papers in papers_by_topic.items():
                print(f"\n  {topic_name} ({len(papers)} papers):")
                for i, title in enumerate(papers[:3], 1):
                    print(f"    {i}. {title}")
                if len(papers) > 3:
                    print(f"    ... and {len(papers) - 3} more")
            
            print("\n✓ Pipeline completed successfully!")
        else:
            print("⚠️  No emails to classify")
            
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(
        description="Test the Scholar Scout MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--test-all",
        action="store_true",
        help="Run all tests (default)"
    )
    
    parser.add_argument(
        "--test-resources",
        action="store_true",
        help="Test only resources"
    )
    
    parser.add_argument(
        "--test-tools",
        action="store_true",
        help="Test only tools"
    )
    
    parser.add_argument(
        "--test-integration",
        action="store_true",
        help="Test complete integration"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yml",
        help="Path to configuration file"
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
    
    # Load environment variables
    load_dotenv()
    
    # Check environment variables
    required_vars = ["GMAIL_USERNAME", "GMAIL_APP_PASSWORD", "PPLX_API_KEY", "SLACK_API_TOKEN"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("Please set them in your .env file")
        return 1
    
    # Check config file
    if not os.path.exists(args.config):
        print(f"❌ Configuration file not found: {args.config}")
        return 1
    
    print("="*60)
    print("Scholar Scout MCP Server Test Suite")
    print("="*60)
    print(f"Configuration: {args.config}")
    print(f"Debug mode: {'enabled' if args.debug else 'disabled'}")
    
    try:
        # Create MCP server instance
        server = ScholarScoutMCPServer(config_path=args.config)
        
        # Determine what to test
        run_all = args.test_all or not (args.test_resources or args.test_tools or args.test_integration)
        
        if run_all or args.test_resources:
            await test_resources(server)
        
        if run_all or args.test_tools:
            await test_tools(server)
        
        if run_all or args.test_integration:
            await test_integration(server)
        
        print("\n" + "="*60)
        print("✓ All tests completed!")
        print("="*60)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

