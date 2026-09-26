"""Pre-launch hardening: the shell must not route around the discuss lock or the push gate.

Each case below was allowed before this change (baseline red): a cooperating
agent could edit files through Bash while the user asked for discussion only,
lift the lock itself with a sopctl call, or disable/skip the pre-push gate with
an ordinary git or shell command.  The read-only and unlocked cases pin that
the hardening does not block normal work.
"""
from __future__ import annotations

import pytest

from sopcontrol.harness import check_tool_call, is_git_push, is_read_only_command


def bash(command: str, *, intent: str | None = None, gate: str | None = None):
    return check_tool_call(
        {"tool_name": "Bash", "tool_input": {"command": command}},
        gate,
        intent,
    )


# --- B1: the discuss-only lock covers the shell, not just Write/Edit ---------

@pytest.mark.parametrize("command", [
    "echo hi > src/app.py",
    "echo hi >> src/app.py",
    "sed -i '' s/a/b/ src/app.py",
    "cat notes.txt | tee src/app.py",
    "python3 -c 'open(\"src/app.py\", \"w\").write(\"x\")'",
    "rm src/app.py",
    "mv src/app.py src/old.py",
    "git commit -am wip",
    "git checkout -- src/app.py",
    "bash -c 'echo hi > src/app.py'",
    "FOO=1 make build",
    "ls; rm src/app.py",
    "ls && touch src/new.py",
    "ls\nrm src/app.py",
    "ls `rm src/app.py`",
    "ls $(rm src/app.py)",
    "find . -name '*.pyc' -delete",
    "find . -exec rm {} ;",
    "sort data.txt -o data.txt",
    "git branch feature-x",
    "sopctl task open . --objective x --allow y",
])
def test_discuss_only_denies_shell_writes(command):
    decision = bash(command, intent="discuss_only")
    assert decision.permissionDecision == "deny", command
    assert "discuss_only" in decision.reason


@pytest.mark.parametrize("command", [
    "ls",
    "ls -la src",
    "cat README.md",
    "head -20 src/app.py",
    "grep -rn TODO .",
    "rg preview_gate sopcontrol",
    "git status",
    "git diff HEAD~1 -- src/app.py",
    "git log --oneline -5",
    "git -C sub status",
    "git branch --show-current",
    "git config --get core.hooksPath",
    "find . -name '*.py'",
    "ls missing 2>/dev/null",
    "git status 2>&1",
    "cat src/app.py | head -5",
    "wc -l < src/app.py",
    "cd src && ls",
    "sopctl task list",
    "sopctl intent show",
])
def test_discuss_only_still_allows_read_only_shell(command):
    decision = bash(command, intent="discuss_only")
    assert decision.permissionDecision == "allow", (command, decision.reason)


def test_shell_writes_are_untouched_when_not_locked():
    assert bash("echo hi > src/app.py").permissionDecision == "allow"
    assert bash("sed -i '' s/a/b/ src/app.py").permissionDecision == "allow"


# --- B2: the agent cannot lift (or forge) the user's intent -----------------

@pytest.mark.parametrize("command", [
    "sopctl intent clear .",
    "sopctl intent clear",
    "/usr/local/bin/sopctl intent clear .",
    "python -m sopcontrol.cli intent clear .",
    "sopctl intake . --conversation chat.txt",
    "sopctl intake --conversation=chat.txt .",
])
@pytest.mark.parametrize("intent", [None, "discuss_only"])
def test_agent_cannot_set_or_clear_session_intent(command, intent):
    decision = bash(command, intent=intent)
    assert decision.permissionDecision == "deny", command
    assert "人" in decision.reason


def test_reading_the_intent_is_still_allowed():
    assert bash("sopctl intent show", intent="discuss_only").permissionDecision == "allow"
    assert bash("sopctl intake . --with-docs").permissionDecision == "allow"


# --- B3: the pre-push gate cannot be removed or skipped from the shell ------

@pytest.mark.parametrize("command", [
    "rm .git/hooks/pre-push",
    "rm -f ./.git/hooks/pre-push",
    "chmod -x .git/hooks/pre-push",
    "mv .git/hooks/pre-push /tmp/pre-push.bak",
    "echo 'exit 0' > .git/hooks/pre-push",
    "rm -rf .git/hooks",
    "find .git/hooks -delete",
    "git config core.hooksPath /dev/null",
    "git config --local core.hooksPath .githooks-empty",
    "git -c core.hooksPath=/dev/null push origin main",
    "GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/dev/null'\" git push",
])
def test_shell_cannot_disable_the_push_gate(command):
    decision = bash(command, gate="clean")
    assert decision.permissionDecision == "deny", command


def test_write_tools_cannot_replace_git_hooks():
    for tool in ("Write", "Edit"):
        decision = check_tool_call({
            "tool_name": tool,
            "tool_input": {"file_path": "/repo/.git/hooks/pre-push", "content": "exit 0"},
        })
        assert decision.permissionDecision == "deny", tool


def test_reading_the_hook_is_allowed():
    assert bash("cat .git/hooks/pre-push").permissionDecision == "allow"
    assert bash("ls -la .git/hooks").permissionDecision == "allow"


@pytest.mark.parametrize("command", [
    "git push origin main",
    "git -C . push origin main",
    "git --no-pager push",
    "cd sub && git push",
    "/usr/bin/git push",
    "command git push",
    "sh -c 'git push origin main'",
    "bash -lc \"git push\"",
])
def test_every_spelling_of_push_reaches_the_gate(command):
    assert is_git_push(command), command
    # No gate context means the push was not evaluated: fail closed.
    assert bash(command).permissionDecision == "deny", command
    assert bash(command, gate="block").permissionDecision == "deny", command
    assert bash(command, gate="clean").permissionDecision == "allow", command


@pytest.mark.parametrize("command", [
    "git log --grep push",
    "git commit -m 'push fix'",
    "echo git push",
    "grep -rn 'git push' docs",
])
def test_push_mentions_are_not_pushes(command):
    assert not is_git_push(command), command


def test_read_only_classifier_rejects_unparseable_commands():
    assert not is_read_only_command("cat 'unterminated")
    assert not is_read_only_command("")
