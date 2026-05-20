#!/usr/bin/env python3
"""
Auto-Repair Agent
- Scans test failures and runtime errors
- Dumps repo snapshot
- Calls local AI CLIs (opencode, codex, copilot) in that order to get fixes
- Applies suggested patches on a new branch, runs tests, and optionally pushes+creates+merges PR

USAGE:
  AUTO_REPAIR_ALLOW_PUSH=1 PYTHONPATH=. python3 auto_repair_agent.py

Security: By default this runs in dry-run mode and WILL NOT push/merge unless
AUTO_REPAIR_ALLOW_PUSH=1 is set.

"""

import subprocess
import sys
import os
import shlex
from pathlib import Path
import tempfile
import datetime
import uuid
import json

REPO_ROOT = Path(__file__).resolve().parent
DUMP_DIR = REPO_ROOT / "dumps"
COAUTHOR = "Copilot <223556219+Copilot@users.noreply.github.com>"
AI_COMMANDS = ["opencode", "codex", "copilot"]


def run(cmd, cwd=REPO_ROOT, capture_output=True, check=False, env=None, timeout=120):
    env2 = os.environ.copy()
    if env:
        env2.update(env)
    print(f"> {cmd}")
    proc = subprocess.run(shlex.split(cmd), capture_output=capture_output, text=True, cwd=str(cwd), env=env2, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{proc.stderr}")
    return proc


def run_tests():
    print("Running pytest...")
    proc = run(f"python3 -m pytest -q --tb=short", capture_output=True, check=False, timeout=300)
    return proc.returncode, proc.stdout + (proc.stderr or "")


def collect_failures(output: str):
    # crude: look for 'FAILED' and stack traces
    failures = []
    lines = output.splitlines()
    if "failed" in output.lower():
        failures.append("Test failures detected. Full pytest output attached.")
    return failures


def dump_repo_snapshot(tag: str) -> Path:
    DUMP_DIR.mkdir(exist_ok=True)
    ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    name = f"dump-{tag}-{ts}-{uuid.uuid4().hex[:6]}.tar.gz"
    path = DUMP_DIR / name
    # create a git archive if possible
    try:
        run(f"git rev-parse --show-toplevel", check=True)
        run(f"git add -A && git update-index -q --refresh", check=False)
        run(f"git archive --format=tar.gz -o {shlex.quote(str(path))} HEAD", check=True)
        print(f"Repo snapshot written to {path}")
    except Exception as e:
        print(f"git archive failed, falling back to tar of tree: {e}")
        run(f"tar -czf {shlex.quote(str(path))} . --exclude .git", check=True)
    return path


def find_ai_cli():
    candidates = []
    for cmd in AI_COMMANDS:
        p = shutil_which(cmd)
        if p:
            candidates.append(cmd)
    return candidates


def shutil_which(cmd):
    from shutil import which
    return which(cmd)


def call_ai_cli(cmd_name: str, prompt: str, timeout=120) -> str:
    """Attempt to call a local AI CLI that accepts stdin and prints patch or suggestion.
    Behavior varies; this function prefers a unified-diff or JSON with {"patch": "..."}.
    """
    if not shutil_which(cmd_name):
        raise FileNotFoundError(f"AI CLI '{cmd_name}' not found in PATH")
    try:
        proc = subprocess.run([cmd_name], input=prompt, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            print(f"{cmd_name} returned code {proc.returncode}, stderr:\n{proc.stderr}")
        out = proc.stdout or proc.stderr
        return out
    except Exception as e:
        raise


def extract_patch_from_ai(output: str) -> str:
    # Heuristic: if output contains 'diff --git' or starts with '***' or '*** Begin Patch', return as-is
    if 'diff --git' in output or '\n***' in output or output.strip().startswith('---'):
        return output
    # If JSON
    try:
        j = json.loads(output)
        if isinstance(j, dict) and 'patch' in j:
            return j['patch']
    except Exception:
        pass
    # Otherwise return entire output as patch content (best-effort)
    return output


def apply_patch(patch_text: str) -> bool:
    # Try git apply
    with tempfile.NamedTemporaryFile('w+', delete=False) as tf:
        tf.write(patch_text)
        tf.flush()
        patch_file = tf.name
    try:
        res = run(f"git apply --index {shlex.quote(patch_file)}", check=False)
        if res.returncode == 0:
            return True
        else:
            print(f"git apply failed, attempting to write files directly. git apply stderr:\n{res.stderr}")
            # naive fallback: attempt to parse unified diffs and write
            # For security and simplicity, return False
            return False
    finally:
        try:
            os.unlink(patch_file)
        except Exception:
            pass


def create_branch_and_commit(branch_name: str, message: str) -> bool:
    run(f"git checkout -b {shlex.quote(branch_name)}", check=True)
    run("git add -A", check=True)
    run(f"git commit -m {shlex.quote(message)} --author={shlex.quote(COAUTHOR)}", check=False)
    return True


def push_and_create_pr(branch_name: str, remote: str = "origin", target_branch: str = "master") -> bool:
    can_push = os.environ.get('AUTO_REPAIR_ALLOW_PUSH') == '1'
    if not can_push:
        print("AUTO_REPAIR_ALLOW_PUSH not set; skipping push/PR (dry-run). Set AUTO_REPAIR_ALLOW_PUSH=1 to enable)")
        return False
    # push
    run(f"git push {shlex.quote(remote)} {shlex.quote(branch_name)} -v", check=True)
    # create PR using gh if available
    if shutil_which('gh'):
        run(f"gh pr create --fill --base {shlex.quote(target_branch)} --head {shlex.quote(branch_name)}", check=False)
        run(f"gh pr merge --auto --squash", check=False)
        return True
    else:
        print("'gh' CLI not available; pushed branch but cannot auto-create/merge PR")
        return True


def main():
    rc, output = run_tests()
    failures = collect_failures(output)
    if rc == 0:
        print("No failures detected. Nothing to repair.")
        return 0

    tag = 'pytest-failure'
    dump = dump_repo_snapshot(tag)

    prompt = """
You are an automated code fixer. A failing test run and repository snapshot are attached.
Provide a unified-diff patch that fixes the root cause. If multiple fixes are needed, produce a single patch.

PyTest output:
""" + output + "\n\n" + f"Repository dump: {dump}\n"

    # Try AI CLIs in order
    import shutil
    ai_found = [c for c in AI_COMMANDS if shutil.which(c)]
    if not ai_found:
        print("No AI CLI (opencode/codex/copilot) found in PATH. Please install or configure.")
        print("You can set environment variables OPENCODE_CMD/CODEX_CMD/COPILOT_CMD to custom wrappers.")
        return 1

    for ai in ai_found:
        try:
            print(f"Querying AI CLI: {ai}")
            out = call_ai_cli(ai, prompt)
            patch = extract_patch_from_ai(out)
            if not patch.strip():
                print(f"AI {ai} returned no patch. Output:\n{out}")
                continue
            ok = apply_patch(patch)
            if not ok:
                print(f"Applying patch failed for AI {ai}. Output:\n{out}")
                continue
            # commit and test
            branch = f"auto-repair/{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}/{ai}"
            create_branch_and_commit(branch, f"auto-repair: fix tests using {ai}\n\nCo-authored-by: {COAUTHOR}")
            rc2, out2 = run_tests()
            if rc2 == 0:
                print("Tests passed after applying patch. Preparing to push/PR.")
                pushed = push_and_create_pr(branch)
                if pushed:
                    print("Auto-repair completed and pushed")
                else:
                    print("Auto-repair completed locally (dry-run)")
                return 0
            else:
                print("Tests still failing after patch; reverting branch and continuing")
                run("git checkout master", check=True)
                run(f"git branch -D {shlex.quote(branch)}", check=False)
                continue
        except Exception as e:
            print(f"Error while querying AI {ai}: {e}")
            continue

    print("All AI attempts exhausted; manual intervention required.")
    return 2

if __name__ == '__main__':
    sys.exit(main())
