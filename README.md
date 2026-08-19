# CardDAV to FritzBox Sync Utility

This project provides a command-line utility to synchronize contacts from multiple
CardDAV sources (like Nextcloud) to a FritzBox address book. It normalizes phone
numbers and handles vCard image processing for FritzBox compatibility.

Note that newer FritzBoxes support a carddav sync natively. This project is unique
in that it can take several sources and merge into a single phone book, where it
intelligently merges the same contact from multiple sources into a single one.


## Features

- **Multi-Source CardDAV Support**: Sync contacts from multiple CardDAV sources
- **Phone Number Normalization**: Strip international codes and apply regional formatting
- **vCard Image Processing**: Convert contact photos to FritzBox-compatible JPG format
- **Mirror Sync**: Completely overwrite FritzBox address book (prune old contacts)
- **Non-Interactive**: Designed for cron job execution
- **Secure Credential Handling**: Support for environment variables or config files
- **Comprehensive Logging**: Detailed progress and error reporting

## Project Structure

```
src/
├── __init__.py
├── __main__.py
├── config/
│   ├── __init__.py
│   └── loader.py
├── models/
│   ├── __init__.py
│   └── contact.py
├── services/
│   ├── __init__.py
│   ├── carddav_fetcher.py
│   ├── converter.py
│   └── fritzbox_uploader.py
├── utils/
│   ├── __init__.py
│   └── logger.py
└── main.py

tests/
├── __init__.py
├── integration/
│   └── test_sync_workflow.py
├── unit/
│   ├── __init__.py
│   ├── test_converter.py
│   └── test_logger.py
└── contract/
    └── (future contract tests)

specs/
└── 001-carddav-fritzbox-sync/
    ├── plan.md
    ├── research.md
    ├── data-model.md
    ├── spec.md
    └── quickstart.md
```

## Quickstart

### 1. Setup Python Virtual Environment

Create and activate a Python virtual environment to isolate dependencies and ensure consistent testing environment:

```bash
# Create virtual environment
cd /path/to/project
python3 -m venv .venv

# Activate virtual environment
# On Linux/macOS
source .venv/bin/activate
# On Windows
.venv\\Scripts\\activate

# Upgrade pip
pip install --upgrade pip

# Install project dependencies
pip install -r requirements.txt
```

# Note for the AI
Executing commands within the venv must be from the .venv/bin.

### 2. Configuration

Create a `config.ini` file with your configuration:

```ini
[general]
name_order = first_name_first

[fritzbox]
url = https://fritz.box
username = your_username
password = your_password
target_book = CardDAV Sync
country = DE
region = DE
country_code = +49
region_code = 30

[regional]
country_code = +49
region_code = 30

source_1
url = https://nextcloud.example.com
username = user1
password = pass1
priority = 1

source_2
url = https://caldav.example.com
username = user2
password = pass2
priority = 2
```

### 3. Running the Utility

```bash
python3 src/main.py --config config.ini
```

Or for non-interactive cron execution:

```bash
python3 src/main.py --config config.ini --log-level INFO
```

### 4. Dry Run Mode

Validate configuration and see what would be synced without actual upload:

```bash
python3 src/main.py --config config.ini --dry-run
```

## Configuration

### File Format

The utility uses INI format for configuration. Required sections:

- `[general]`: Global settings (name ordering)
- `[fritzbox]`: FritzBox connection details
- `[regional]`: Phone number normalization settings
- `[source_X]`: CardDAV source configurations (X = 1, 2, 3...)

### Required FritzBox Configuration

- `url`: FritzBox hostname or IP address
- `username`: FritzBox web interface username
- `password`: FritzBox web interface password
- `target_book`: Name of the address book to sync

### Optional Settings

- `country`: FritzBox country code (default: DE)
- `region`: FritzBox region code (default: DE)
- `country_code`: Default country code for normalization (default: +49)
- `region_code`: Default region code for normalization (default: 30)

### CardDAV Source Configuration

Each source requires:
- `url`: CardDAV source URL
- `username`: CardDAV username
- `password`: CardDAV password
- `priority`: Source priority (1 = highest, 2 = next, etc.)

## Usage Examples

### Example 1: Sync from Nextcloud

```bash
python3 src/main.py --config myconfig.ini
```

### Example 2: Debug Mode

```bash
python3 src/main.py --config config.ini --log-level DEBUG
```

### Example 3: Validate Only

```bash
python3 src/main.py --config config.ini --validate-only
```

### Example 4: Cron Job Entry

```bash
0 2 * * * /usr/bin/python3 /home/user/carddav2fritzbox/src/main.py --config /home/user/carddav2fritzbox/config.ini >> /var/log/carddav_sync.log 2>&1
```

## Testing

### Virtual Environment Requirement

All Python testing operations must be performed within a properly configured Python virtual environment to ensure:

- **Dependency isolation**: Tests run with exact dependency versions
- **Environment consistency**: Prevents conflicts with system Python packages
- **Reproducible results**: Same environment across different developer machines
- **Safe testing**: Protection against accidental system-wide changes

### Setup Virtual Environment (Required)

```bash
# Create virtual environment
cd /path/to/project
python3 -m venv .venv

# Activate virtual environment
# On Linux/macOS
source .venv/bin/activate
# On Windows
.venv\\Scripts\\activate

# Install project dependencies
pip install -r requirements.txt
```

### Unit Tests

Run unit tests to verify individual components:

```bash
# Ensure virtual environment is active
source .venv/bin/activate  # Linux/macOS

pytest tests/unit/ -v
```

### Integration Tests

Run integration tests to verify complete workflows:

```bash
# Ensure virtual environment is active
source .venv/bin/activate  # Linux/macOS

pytest tests/integration/ -v
```

### All Tests

```bash
# Ensure virtual environment is active
source .venv/bin/activate  # Linux/macOS

pytest -v
```

### Testing in CI/CD

For continuous integration, include virtual environment setup in your pipeline:

```yaml
# Example GitHub Actions step
- name: Setup virtual environment
  run: |
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

- name: Run tests
  run: |
    source .venv/bin/activate
    pytest -v
```

## Development

### Virtual Environment Management

The project requires Python virtual environments for testing. This ensures:

1. **Dependency consistency**: Same dependencies across all environments
2. **Isolation**: Prevents conflicts with system Python packages
3. **Reproducible builds**: CI/CD pipelines can reliably reproduce test environments
4. **Safe development**: Protects system Python installation

### Environment Setup Scripts

Consider adding an environment setup script to streamline virtual environment creation:

```bash
#!/bin/bash
# setup-env.sh - Setup Python virtual environment and install dependencies

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not installed."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r "$PROJECT_DIR/requirements.txt"

# Verify installation
echo "Virtual environment setup complete"
```

### Development Workflow

```bash
# Standard development workflow
./setup-env.sh  # Create and setup virtual environment
source .venv/bin/activate  # Activate environment for current session

# Run tests in the virtual environment
.venv/bin/pytest -v

# Deactivate when done
deactivate
```

## Virtual Environment Best Practices

1. **Never commit virtual environment to Git**: Add `.venv/` to `.gitignore`
2. **Document environment setup**: Include in README or setup scripts
3. **Use consistent naming**: Standard `venv`, `.venv`, or `env` directory names
4. **Version pin dependencies**: Use `requirements.txt` for consistent environments
5. **Consider containerization**: Docker for complex environments with multiple services
6. **Cache virtual environments in CI**: Speed up CI/CD pipeline runs
7. **Test locally before CI**: Ensure your local environment works before committing
8. **Handle environment-specific configuration**: Use environment variables or config files
