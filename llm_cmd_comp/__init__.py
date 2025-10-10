import click
import llm
import os
import platform
import shutil
import string
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_input
from prompt_toolkit.output import create_output


SYSTEM_PROMPT = string.Template("""
Return only the command to be executed as a raw string, no string delimiters wrapping it, no yapping, no markdown, no fenced code blocks, what you return will be passed to the shell directly.

Environment: $shell_display on $os_display$env_suffix$pkg_suffix

If there is a lack of details, provide the most logical solution.
If multiple steps are required, try to combine them using '&&' (For PowerShell, use ';' instead).

For example, if the user asks: undo last git commit
You return only: git reset --soft HEAD~1
""".strip())


def detect_shell():
    """Detect current shell cross-platform (using env vars only)"""
    system = platform.system()

    # Check for PowerShell first (cross-platform)
    if os.getenv("PSModulePath"):
        if system == "Windows":
            # On Windows, distinguish PowerShell 5.1 vs 7+
            # PSModulePath contains "WindowsPowerShell" in PS5, but just "PowerShell" in PS7
            ps_module_path = os.getenv("PSModulePath", "")
            if "WindowsPowerShell" in ps_module_path:
                return "powershell", "5"  # Windows PowerShell 5.1

            # Secondary check: PS7 adds "PowerShell\7" to PATH
            path = os.getenv("Path", "")
            if "PowerShell\\7" in path or "PowerShell/7" in path:
                return "pwsh", "7"

            # Tertiary fallback: check which executable is available
            if shutil.which("pwsh"):
                return "pwsh", "7"

            # If PSModulePath exists but no WindowsPowerShell, assume PS7
            return "pwsh", "7"
        else:
            # On Linux/macOS, PowerShell is always pwsh 7+
            # (PowerShell 5.1 is Windows-only)
            return "pwsh", "7"

    # Windows-specific shells
    if system == "Windows":
        # Check for Git Bash/MSYS/Cygwin on Windows
        shell = os.getenv("SHELL")
        if shell:
            shell_name = os.path.basename(shell)
            return shell_name, ""

        # Fall back to cmd.exe
        return "cmd", ""

    # Unix-like systems: $SHELL is reliable
    shell_name = os.path.basename(os.getenv("SHELL") or "sh")
    return shell_name, ""


def detect_os():
    """Detect OS - simplified version info"""
    os_type = platform.system()

    if os_type == "Linux":
        # Just get distro name, skip version/kernel details
        try:
            with open('/etc/os-release') as f:
                for line in f:
                    if line.startswith('NAME='):
                        distro = line.split('=')[1].strip().strip('"')
                        return f"Linux ({distro})"
        except:
            pass
        return "Linux"

    elif os_type == "Darwin":
        # Just "macOS" - version rarely matters for commands
        return "macOS"

    elif os_type == "Windows":
        # Simple: just Windows (no build numbers)
        return "Windows"

    else:
        return os_type


def detect_environment():
    """Detect hybrid environments (WSL, Git Bash, etc.)"""
    os_name = platform.system()

    # WSL detection
    if os_name == "Linux":
        if os.getenv("WSL_DISTRO_NAME"):
            return "wsl"
        try:
            with open('/proc/version', 'r') as f:
                if 'microsoft' in f.read().lower():
                    return "wsl"
        except:
            pass

    # Git Bash / MSYS
    if os.getenv("MSYSTEM"):
        return "gitbash"

    # Cygwin
    if os.getenv("CYGWIN"):
        return "cygwin"

    return "native"


def detect_package_managers():
    """Detect available package managers"""
    managers = []

    # Check common package managers
    for pm in ['apt', 'dnf', 'yum', 'pacman', 'zypper', 'apk',  # Linux
                'snap', 'flatpak',  # Universal Linux
                'brew', 'port',  # macOS
                'choco', 'scoop', 'winget',  # Windows
                'nix', 'guix',  # Alternative
                'pipx', 'uv', 'pip', 'npm', 'cargo', 'gem']:  # Language
        if shutil.which(pm):
            managers.append(pm)

    return managers


def render_system_prompt():
    """Build system prompt with minimal context"""
    shell_name, shell_version = detect_shell()
    os_display = detect_os()
    environment = detect_environment()
    package_managers = detect_package_managers()

    # Format shell display (only show version when it matters)
    if shell_version:
        shell_display = f"{shell_name} {shell_version}"
    else:
        shell_display = shell_name

    # Format template variables
    context = {
        'shell_display': shell_display,
        'os_display': os_display,
        'env_suffix': f' [running in {environment.upper()}]' if environment != 'native' else '',
        'pkg_suffix': f'\nPackage managers: {", ".join(package_managers)}' if package_managers else '',
    }

    return SYSTEM_PROMPT.safe_substitute(context)


@llm.hookimpl
def register_commands(cli):
    @cli.command()
    @click.option(
        "--init",
        type=click.Choice(["bash", "zsh", "fish"]),
        help="Output shell integration code for the specified shell and exit.",
    )
    @click.argument("args", nargs=-1)
    @click.option("-m", "--model", default=None, help="Specify the model to use")
    @click.option("-s", "--system", help="Custom system prompt")
    @click.option("--key", help="API key to use")
    def cmdcomp(init, args, model, system, key):
        """Generate commands directly in your command line (requires shell integration)
        Optionally output shell integration code with --init SHELL (bash, zsh, fish)
        """
        import sys
        from llm.cli import get_default_model

        if init:
            share_dir = os.path.join(os.path.dirname(__file__), "share")
            filename = f"llm-cmd-comp.{init}"
            filepath = os.path.join(share_dir, filename)
            if not os.path.exists(filepath):
                click.echo(f"Error: Integration file for {init} not found.", err=True)
                sys.exit(1)
            with open(filepath) as f:
                click.echo(f.read())
            return

        prompt = " ".join(args)
        model_id = model or get_default_model()
        model_obj = llm.get_model(model_id)
        if model_obj.needs_key:
            model_obj.key = llm.get_key(key, model_obj.needs_key, model_obj.key_env_var)
        conversation = model_obj.conversation()
        system = system or render_system_prompt()
        interactive_exec(conversation, prompt, system)


def interactive_exec(conversation, command, system):
    ttyin = create_input(always_prefer_tty=True)
    ttyout = create_output(always_prefer_tty=True)
    session = PromptSession(input=ttyin, output=ttyout)
    system = system or SYSTEM_PROMPT

    command = conversation.prompt(command, system=system)
    while True:
        ttyout.write("$ ")
        for chunk in command:
            ttyout.write(chunk.replace("\n", "\n> "))
        command = command.text()
        ttyout.write("\n# Provide revision instructions; leave blank to finish\n")
        feedback = session.prompt("> ")
        if feedback == "":
            break
        command = conversation.prompt(feedback, system=system)
    print(command)
