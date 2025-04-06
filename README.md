# AI Shell

An intelligent command-line interface that understands natural language and provides smart command suggestions.

## Features

- Natural language command translation (prefix with `?`)
- Smart command completion and suggestions
- Setup wizard for common development tasks (prefix with `%%`)
- Error analysis and automatic fix suggestions
- Cross-platform support (Linux, macOS, Windows)

## Prerequisites

- Python 3.6 or higher
- Git
- Administrative privileges for installation

## Installation

### Quick Install (Linux/macOS)

```bash
# Clone the repository
git clone https://github.com/yourusername/aishell.git
cd aishell

# Make the install script executable
chmod +x install_aishell.sh

# Run the installer
sudo ./install_aishell.sh
```

### Linux Installation

#### Add the api_key of hte openrouter
1. Run for the first time:
   ```bash
   aishell
   ```

## Usage

After installation, you can start the AI Shell by typing:
```bash
aishell
```

### Special Commands

- `?` - Natural language command translation
  ```bash
  ? how to list all files recursively
  ```

- `%%` - Setup wizard for common tasks
  ```bash
  %% setup a new python project
  ```

- Direct commands work as normal:
  ```bash
  ls -la
  git status
  ```

### Command Suggestions

- Press TAB or RIGHT ARROW to complete suggestions
- Commands are context-aware and based on your current directory

## Uninstallation

To uninstall AI Shell:
```bash
sudo /usr/local/bin/shell/uninstall.sh
```


## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.