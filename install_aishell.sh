#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Define installation directory
INSTALL_DIR="/usr/local/bin/shell"

echo -e "${BLUE}Installing AI Shell...${NC}"

# Check if running with sudo
# if [ "$EUID" -ne 0 ]; then 
#     echo "Please run with sudo"
#     exit 1
# fi

# Create installation directory
echo "Creating installation directory..."
mkdir -p "$INSTALL_DIR"

# Copy all necessary files
echo "Copying files..."
cp shell.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"

# Create the main shell script in the installation directory
cat > "$INSTALL_DIR/aishell" << 'EOF'
#!/bin/bash

# Store the current directory
CURRENT_DIR="$(pwd)"

# Change to the installation directory temporarily
cd /usr/local/bin/shell

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python3 is not installed. Installing Python..."
    if command -v apt &> /dev/null; then
        sudo apt update && sudo apt install -y python3 python3-pip
    elif command -v yum &> /dev/null; then
        sudo yum install -y python3 python3-pip
    elif command -v brew &> /dev/null; then
        brew install python3
    else
        echo "Could not install Python. Please install Python3 manually."
        exit 1
    fi
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
if [ ! -f "venv/requirements_installed" ]; then
    echo "Installing required packages..."
    pip install -r requirements.txt
    touch venv/requirements_installed
fi

# Setup .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Setting up .env file..."
    echo -n "Please enter your deepseek API key: "
    read api_key
    echo "deepseek_api=\"$api_key\"" > .env
    echo ".env file created successfully!"
fi

# Change back to the user's original directory
cd "$CURRENT_DIR"

# Run the shell with the full path to shell.py
echo "Starting AI Shell..."
python3 /usr/local/bin/shell/shell.py
EOF

# Make the script executable
chmod +x "$INSTALL_DIR/aishell"

# Create symbolic link in /usr/local/bin
ln -sf "$INSTALL_DIR/aishell" /usr/local/bin/aishell

# Set proper permissions
chown -R root:root "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

echo -e "${GREEN}Installation completed!${NC}"
echo -e "${BLUE}You can now run the AI Shell from anywhere by typing:${NC} aishell"

# Create uninstall script
cat > "$INSTALL_DIR/uninstall.sh" << 'EOF'
#!/bin/bash
rm -f /usr/local/bin/aishell
rm -rf /usr/local/bin/shell
echo "AI Shell has been uninstalled."
EOF

chmod +x "$INSTALL_DIR/uninstall.sh"

echo -e "${BLUE}To uninstall, run:${NC} sudo $INSTALL_DIR/uninstall.sh"
