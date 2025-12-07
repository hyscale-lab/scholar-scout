#!/bin/bash
# Setup script for Scholar Scout MCP Server
# This script helps you set up the MCP server quickly

set -e  # Exit on error

echo "================================================"
echo "Scholar Scout MCP Server Setup"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required_version="3.8"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" = "$required_version" ]; then 
    print_success "Python $python_version is installed"
else
    print_error "Python $required_version or higher is required (found $python_version)"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    print_info "Creating virtual environment..."
    python3 -m venv .venv
    print_success "Virtual environment created"
else
    print_info "Virtual environment already exists"
fi

# Activate virtual environment
print_info "Activating virtual environment..."
source .venv/bin/activate
print_success "Virtual environment activated"

# Install dependencies
print_info "Installing dependencies..."
if pip install -r requirements.txt -q; then
    print_success "Dependencies installed"
else
    print_error "Failed to install dependencies"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    print_info "Creating .env file from template..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        print_success ".env file created"
        print_info "Please edit .env file and add your credentials"
    else
        print_error ".env.example not found"
        echo "Please create .env file manually with:"
        echo "  GMAIL_USERNAME=your.email@gmail.com"
        echo "  GMAIL_APP_PASSWORD=your-app-password"
        echo "  PPLX_API_KEY=your-perplexity-key"
        echo "  SLACK_API_TOKEN=your-slack-token"
    fi
else
    print_success ".env file already exists"
fi

# Check if config file exists
if [ ! -f "config/config.yml" ]; then
    print_info "Creating config file from template..."
    if [ -f "config/config.example.yml" ]; then
        cp config/config.example.yml config/config.yml
        print_success "config.yml created"
        print_info "Please edit config/config.yml and customize your settings"
    else
        print_error "config/config.example.yml not found"
    fi
else
    print_success "config.yml already exists"
fi

# Make scripts executable
print_info "Making scripts executable..."
chmod +x scripts/run_mcp_server.py
chmod +x scripts/test_mcp_server.py
print_success "Scripts are now executable"

echo ""
echo "================================================"
print_success "Setup completed!"
echo "================================================"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your credentials"
echo "2. Edit config/config.yml with your research topics"
echo "3. Test the server:"
echo "   python scripts/test_mcp_server.py"
echo ""
echo "4. For Claude Desktop integration:"
echo "   - Edit your Claude Desktop config file"
echo "   - Add the MCP server configuration"
echo "   - See MCP_README.md for details"
echo ""
echo "5. Run the MCP server:"
echo "   python scripts/run_mcp_server.py"
echo ""
print_info "For more information, see MCP_README.md"

