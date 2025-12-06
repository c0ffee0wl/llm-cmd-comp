import click
import llm
import os
import string
import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_input
from prompt_toolkit.output import create_output

from .system_info import detect_shell, detect_os, detect_environment, detect_package_managers


SYSTEM_PROMPT = string.Template("""
Return only the command to be executed as a raw string, no string delimiters wrapping it, no yapping, no markdown, no fenced code blocks, what you return will be passed to the shell directly.

Environment: $shell_display on $os_display$env_suffix$pkg_suffix

If there is a lack of details, provide the most logical solution.
Ensure the output is a valid shell command for the environment.
If multiple steps are required, try to combine them using '&&' (For PowerShell, use ';' instead).

For example, if the user asks: undo last git commit
You return only: git reset --soft HEAD~1
""".strip())


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
    system = system or SYSTEM_PROMPT

    # Try prompt_toolkit first (works in regular terminal)
    try:
        ttyin = create_input(always_prefer_tty=True)
        ttyout = create_output(always_prefer_tty=True)
        session = PromptSession(input=ttyin, output=ttyout)

        # Interactive mode with prompt_toolkit
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
        return
    except Exception:
        pass  # Try manual console I/O fallback

    # Windows fallback: Direct console I/O using CONIN$/CONOUT$ devices
    # This bypasses prompt_toolkit and works in PSReadLine context
    try:
        conin = open('CONIN$', 'r')
        conout = open('CONOUT$', 'w', buffering=1)

        # Get initial command from LLM
        command = conversation.prompt(command, system=system)

        # Manual interactive loop
        while True:
            # Display suggested command
            conout.write("$ ")
            cmd_text = command.text()
            # Handle multiline commands
            conout.write(cmd_text.replace("\n", "\n> "))
            conout.write("\n# Provide revision instructions; leave blank to finish\n> ")
            conout.flush()

            # Read user feedback
            feedback = conin.readline().strip()
            if feedback == "":
                break

            # Get revised command from LLM
            command = conversation.prompt(feedback, system=system)

        # Output final command to stdout (captured by shell)
        print(cmd_text)

        # Clean up
        conin.close()
        conout.close()
        return
    except Exception:
        pass  # Fall back to non-interactive

    # Non-interactive fallback: Single LLM call without revisions
    command = conversation.prompt(command, system=system)
    print(command.text())
