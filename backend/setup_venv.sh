#!/bin/bash

# Setup script for Python virtual environment on server
# This script creates and sets up the virtual environment for the backend
# Usage: ./setup_venv.sh

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR"
BACKEND_VENV="$BACKEND_DIR/venv"
REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Python Virtual Environment Setup${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check Python
if ! command -v python3 > /dev/null 2>&1; then
    echo -e "${RED}❌ Python 3 is not installed. Please install Python 3.10+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${BLUE}ℹ️  Python version: $PYTHON_VERSION${NC}"

# Check if python3-venv is installed (required for venv module)
if ! python3 -m venv --help > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  python3-venv module not found.${NC}"
    echo -e "${YELLOW}   On Debian/Ubuntu, install it with: sudo apt install python3-venv python3-full${NC}"
    exit 1
fi

# Check if requirements.txt exists
if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo -e "${RED}❌ requirements.txt not found at: $REQUIREMENTS_FILE${NC}"
    exit 1
fi

# Remove existing venv if it exists (optional - comment out if you want to keep it)
if [ -d "$BACKEND_VENV" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment already exists at: $BACKEND_VENV${NC}"
    read -p "Remove and recreate? (y/N): " confirm
    if [[ $confirm =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}ℹ️  Removing existing virtual environment...${NC}"
        rm -rf "$BACKEND_VENV"
    else
        echo -e "${BLUE}ℹ️  Using existing virtual environment${NC}"
    fi
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$BACKEND_VENV" ]; then
    echo -e "${BLUE}ℹ️  Creating Python virtual environment...${NC}"
    python3 -m venv "$BACKEND_VENV"
    echo -e "${GREEN}✅ Virtual environment created${NC}"
else
    echo -e "${GREEN}✅ Virtual environment already exists${NC}"
fi

# Use venv's pip directly (avoids externally-managed-environment error)
VENV_PIP="$BACKEND_VENV/bin/pip"
VENV_PYTHON="$BACKEND_VENV/bin/python"

if [ ! -f "$VENV_PIP" ]; then
    echo -e "${RED}❌ Virtual environment pip not found. Something went wrong.${NC}"
    exit 1
fi

# Upgrade pip first
echo -e "${BLUE}ℹ️  Upgrading pip...${NC}"
if ! "$VENV_PIP" install --upgrade pip --quiet 2>&1; then
    # If upgrade fails with externally-managed-environment, the venv is broken
    if "$VENV_PIP" install --upgrade pip 2>&1 | grep -q "externally-managed-environment"; then
        echo -e "${RED}❌ Virtual environment is broken (still using system pip)${NC}"
        echo -e "${YELLOW}   Recreating virtual environment...${NC}"
        rm -rf "$BACKEND_VENV"
        python3 -m venv "$BACKEND_VENV"
        VENV_PIP="$BACKEND_VENV/bin/pip"
        VENV_PYTHON="$BACKEND_VENV/bin/python"
        echo -e "${BLUE}ℹ️  Upgrading pip in new venv...${NC}"
        "$VENV_PIP" install --upgrade pip --quiet
    else
        echo -e "${RED}❌ Failed to upgrade pip${NC}"
        exit 1
    fi
fi

# Install dependencies
echo -e "${BLUE}ℹ️  Installing Python dependencies from requirements.txt...${NC}"
if "$VENV_PIP" install -r "$REQUIREMENTS_FILE"; then
    echo -e "${GREEN}✅ All dependencies installed successfully${NC}"
else
    echo -e "${RED}❌ Failed to install dependencies${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Virtual environment setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Virtual environment location: $BACKEND_VENV"
echo ""
echo "To activate the virtual environment, run:"
echo "  source $BACKEND_VENV/bin/activate"
echo ""
echo "Or use the venv's Python directly:"
echo "  $VENV_PYTHON your_script.py"
echo ""
echo "To install additional packages:"
echo "  $VENV_PIP install package_name"
echo ""

