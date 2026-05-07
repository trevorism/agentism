"""Git-only tools – clone repos, inspect status, branch, commit, and push."""
from __future__ import annotations

from langchain_core.tools import tool
from agentism.config import WORKSPACE_DIR, DEV_DIR
from agentism import config
from tools.repo_paths import find_repo, repo_path

# Primary dev directory – pre-existing checkouts are found here before cloning.
PRIMARY_DEV_DIR = DEV_DIR

# Branches the agent is never allowed to push to directly.
PROTECTED_BRANCHES = {"master"}


def _find_repo(name: str):
    """Backward-compatible wrapper for existing tests/imports."""
    return find_repo(name)


def _repo_path(repo_name: str):
    """Backward-compatible wrapper for existing tests/imports."""
    return repo_path(repo_name)


@tool
def git_clone(repo_url: str, local_name: str = "") -> str:
    """
    Ensure a Git repository is available locally.

    Checks DEV_DIR first (pre-existing checkouts). If the repo is
    already present there (or in the agent workspace), returns its path and
    skips cloning. Only clones when the repo cannot be found locally.

    Args:
        repo_url:   HTTPS or SSH URL of the repo.
        local_name: Optional folder name to look for / clone into.
                    Defaults to the repo name inferred from the URL.

    Returns:
        Absolute path to the repo, or an error message.
    """
    import git

    name = local_name or repo_url.rstrip("/").split("/")[-1].removesuffix(".git")

    found = find_repo(name)
    if found:
        return f"Found existing checkout at {found} – using that."

    # Not found anywhere locally – clone into workspace
    workspace = WORKSPACE_DIR / name
    if workspace.exists():
        return f"Found existing checkout at {workspace} – using that."

    # Neither location has it: clone into workspace
    try:
        git.Repo.clone_from(repo_url, str(workspace))
        return f"Cloned to {workspace}"
    except git.GitCommandError as e:
        return f"Clone failed: {e}"


@tool
def git_status(repo_name: str) -> str:
    """
    Return the git status of a local repository (staged, unstaged, untracked files).

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
    """
    import git

    try:
        repo = git.Repo(str(_repo_path(repo_name)))
        changed = [item.a_path for item in repo.index.diff(None)]
        staged = [item.a_path for item in repo.index.diff("HEAD")] if repo.head.is_valid() else []
        untracked = repo.untracked_files
        return (
            f"Branch: {repo.active_branch.name}\n"
            f"Staged:    {staged}\n"
            f"Unstaged:  {changed}\n"
            f"Untracked: {untracked}"
        )
    except Exception as e:
        return f"Error: {e}"


@tool
def git_create_branch(repo_name: str, branch_name: str, from_branch: str = "master") -> str:
    """
    Create and checkout a new feature branch in a local repository.

    Always call this before making changes so that work is isolated from the
    default branch. The new branch is based on the latest commit of from_branch.

    Args:
        repo_name:   Short name of the repo folder in the workspace, or absolute path.
        branch_name: Name for the new branch (e.g. "feature/issue-42-add-reports").
        from_branch: Branch to base the new branch from (default: "master").

    Returns:
        Confirmation message, or an error.
    """
    import git

    if branch_name in PROTECTED_BRANCHES:
        return f"Error: '{branch_name}' is a protected branch name. Choose a feature branch name."

    if config.DRY_RUN:
        return f"[DRY-RUN] Would create branch '{branch_name}' from '{from_branch}' in '{repo_name}'."

    try:
        repo = git.Repo(str(_repo_path(repo_name)))
        # First fetch to ensure we have the latest remote refs
        repo.remotes.origin.fetch()
        # Checkout (or reset) to the remote tracking branch to get latest state
        remote_branch = f"origin/{from_branch}"
        if remote_branch in [ref.name for ref in repo.remote_refs]:
            repo.git.checkout(remote_branch)
        else:
            # Fall back to local branch if remote tracking doesn't exist
            repo.git.checkout(from_branch)
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()
        return f"Created and checked out branch '{branch_name}' from '{from_branch}'."
    except Exception as e:
        return f"Error: {e}"


@tool
def git_commit_and_push(repo_name: str, message: str) -> str:
    """
    Stage all changes in a local repo, commit them, and push to origin.

    Always create a feature branch with git_create_branch before calling this.
    After pushing, create a pull request via the GitHub MCP tools.

    Args:
        repo_name: Short name of the repo folder in the workspace, or absolute path.
        message:   Commit message.

    Returns:
        Commit SHA and push confirmation, or an error message.
    """
    import git

    try:
        repo = git.Repo(str(_repo_path(repo_name)))
        current_branch = repo.active_branch.name
        if current_branch in PROTECTED_BRANCHES:
            return (
                f"Error: currently on protected branch '{current_branch}'. "
                f"Use git_create_branch to create a feature branch first, then commit."
            )
        if config.DRY_RUN:
            repo.git.add(A=True)
            staged = [item.a_path for item in repo.index.diff("HEAD")] if repo.head.is_valid() else []
            untracked = repo.untracked_files
            changed = [item.a_path for item in repo.index.diff(None)]
            all_changes = sorted(set(staged + untracked + changed))
            repo.git.reset()   # undo the staging – don't leave a messy state
            return (
                f"[DRY-RUN] Would commit: {message!r}\n"
                f"  Branch : {current_branch}\n"
                f"  Changes: {all_changes}\n"
                f"  Would push to origin/{current_branch}"
            )
        repo.git.add(A=True)
        if not repo.index.diff("HEAD") and not repo.untracked_files:
            return "Nothing to commit – working tree is clean."
        commit = repo.index.commit(message)
        origin = repo.remote("origin")
        origin.push(refspec=f"HEAD:{current_branch}", set_upstream=True)
        return (
            f"Committed {commit.hexsha[:8]}: {message}\n"
            f"Pushed to origin/{current_branch}\n"
            f"Next step: open a pull request for '{current_branch}' via GitHub MCP tools."
        )
    except Exception as e:
        return f"Error: {e}"


@tool
def git_sync_master(repo_name: str) -> str:
    """
    Sync a local repository after a PR merge by updating the master branch.

    This checks out `master` and pulls the latest commits from `origin` so the
    local checkout matches the remote default branch state after merge.
    """
    import git

    if config.DRY_RUN:
        return f"[DRY-RUN] Would checkout 'master' and pull latest from origin in '{repo_name}'."

    try:
        repo = git.Repo(str(_repo_path(repo_name)))
        repo.git.checkout("master")
        repo.remotes.origin.pull()
        return "Checked out 'master' and pulled latest changes from origin."
    except Exception as e:
        return f"Error: {e}"