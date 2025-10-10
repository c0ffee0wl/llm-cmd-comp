# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is `llm-cmd-comp`, an LLM plugin for the [LLM CLI tool](https://llm.datasette.io/) that provides interactive command completion in shells. It allows users to type commands in natural language or provide feedback on generated commands, which the LLM then converts to proper shell syntax.

The plugin works by:
1. Providing a `cmdcomp` subcommand to the `llm` CLI
2. Installing shell-specific integrations (bash, zsh, fish) that bind Alt+\ to trigger command completion
3. Using an interactive prompt loop that lets users refine commands before execution

## Key Commands

### Development Setup
```bash
# Set up development environment
python3 -m venv venv
source venv/bin/activate
pip install llm
llm install -e .
```

### Testing
```bash
# Run integration test (builds package, installs in clean venv, tests shell integration)
./test_integration.sh
```

### Building and Publishing
```bash
# Build wheel package
python -m pip install build
python -m build --wheel

# Publish to PyPI (requires argc and cog tools)
cog bump -a  # Uses Argcfile.sh to publish
```

### Version Management
This project uses [cocogitto](https://github.com/cocogitto/cocogitto) for conventional commits and versioning:
- All commits must follow conventional commit format (enforced by CI)
- Use `cog bump` to create version bumps and publish
- The version in `pyproject.toml` is automatically updated during bump

## Architecture

### Core Components

**`llm_cmd_comp/__init__.py`** (single file implementation):
- `register_commands()`: LLM plugin hook that registers the `cmdcomp` subcommand
- `interactive_exec()`: Main interactive loop using `prompt_toolkit` for TTY I/O
- `SYSTEM_PROMPT`: Template that instructs LLM to return raw shell commands

### Shell Integrations

Located in `llm_cmd_comp/share/`:
- `llm-cmd-comp.bash`: Bash keybinding using `bind -x`
- `llm-cmd-comp.zsh`: Zsh keybinding using `bindkey` and `zle`
- `llm-cmd-comp.fish`: Fish keybinding using `bind` and `commandline`

These files are distributed with the package (via `package-data` in `pyproject.toml`) and output by `llm cmdcomp --init SHELL` for users to source in their shell configs.

### Interactive Flow

1. User presses Alt+\ with partial command in shell
2. Shell integration calls `llm cmdcomp` with current command line text
3. Plugin sends user's text to LLM with system prompt requesting raw command output
4. LLM response is displayed with `$ ` prefix
5. User can provide feedback to refine, or press Enter to accept
6. Conversation history is maintained for iterative refinement
7. Final command replaces the command line buffer in the shell

### Key Design Decisions

- **No markdown/fencing in output**: System prompt explicitly tells LLM to return raw commands that can be passed directly to shell
- **TTY I/O handling**: Uses `prompt_toolkit` with `always_prefer_tty=True` to handle I/O separately from shell integration
- **Streaming output**: Command is streamed token-by-token as it's generated
- **Conversation context**: Full conversation history maintained across refinement iterations

## Important Development Notes

- Shell integration files must be included in package distribution via `tool.setuptools.package-data` in `pyproject.toml`
- The plugin registers via `project.entry-points.llm` to hook into the LLM CLI
- System prompt uses `string.Template` to inject shell type and platform dynamically
