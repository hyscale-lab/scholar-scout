# Scholar Scout

A tool to monitor Google Scholar alerts and classify research papers using Perplexity AI.

## 🆕 NEW: MCP Server Support!

Scholar Scout now supports **Model Context Protocol (MCP)**, allowing AI assistants like Claude Desktop to interact with your research workflow!

**Quick Start with MCP:**
- See [QUICKSTART_MCP.md](QUICKSTART_MCP.md) for 5-minute setup
- See [MCP_README.md](MCP_README.md) for complete documentation

## Features
- Connects to Gmail to fetch Google Scholar alert emails
- Uses Perplexity AI to parse and extract paper information
- Supports multiple research topics and keywords
- Sends notifications to Slack
- **NEW:** MCP Server for AI assistant integration

## Setup
1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment: `source .venv/bin/activate` (Unix) or `.venv\Scripts\activate` (Windows)
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your credentials
6. Copy `config.example.yml` to `config.yml` and customize settings

## Configuration
Create a `.env` file with:
```
GMAIL_USERNAME=your.email@gmail.com
GMAIL_APP_PASSWORD=your-app-specific-password
PPLX_API_KEY=your-perplexity-api-key
SLACK_API_TOKEN=your-slack-api-token
```

### Adding Users to Track
1. Go to [Google Scholar](https://scholar.google.com/)
2. Search for the researcher you want to track
3. Click on their profile
4. Click the "Follow" button (bell icon) to receive email alerts for new papers
5. In Gmail, create a filter to move these alerts to your designated Scholar folder
6. Update your `config.yml` to include any Slack users to notify:

```yaml
research_topics:
  - name: "LLM Inference"
    description: "Papers about large language model inference, optimization, and deployment"
    keywords:
      - "language model inference"
      - "LLM serving"
      - "model optimization"
    slack_users:
      - "@user1"
      - "@user2"
    slack_channel: "#llm-papers"  # optional
```

### HyScale Scholar Account
To add researchers to the HyScale Scholar tracking:
1. Email the admin (hyscale.ntu@gmail.com) with:
   - Researcher's name and Google Scholar profile link
   - Your Slack username to receive notifications
   - Any specific keywords you want to track
2. The admin will:
   - Set up the Google Scholar alert
   - Update the configuration
   - Confirm once tracking is active

## Usage

### Option 1: MCP Server (Recommended for AI Integration)

Run as an MCP server for use with Claude Desktop or other MCP clients:

```bash
# Quick setup
./setup_mcp.sh

# Run the MCP server
python scripts/run_mcp_server.py

# Test the server
python scripts/test_mcp_server.py
```

See [QUICKSTART_MCP.md](QUICKSTART_MCP.md) for detailed setup instructions.

### Option 2: Traditional Script

Run the main script directly:
```bash
python scripts/run_classifier.py
```

## Testing

### Integration Tests
To run the integration tests under the root directory:
```bash
python -m unittest tests/test_integration.py -v
```

The integration tests require a `test_config.yml` file in the `tests/` directory with your Gmail credentials and settings. Example structure:

```yaml
email:
  username: your.email@gmail.com
  password: your-app-specific-password  # Gmail App Password, not your regular password
  folder: "Inbox"      # IMAP folder where Scholar alerts are stored
```

Note: 
- You'll need to [create an App Password](https://support.google.com/accounts/answer/185833) for Gmail
- The tests expect Google Scholar alert emails from January 5th, 2025 in the specified folder
- Make sure your Scholar alerts are being properly filtered to the specified folder, namely provide the correct path to the folder in the `config.yml` file

## License
MIT
# scholar-scout
