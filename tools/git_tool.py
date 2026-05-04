"""Git tools – clone repos, write files, commit, and push using GitPython."""
from pathlib import Path
from langchain_core.tools import tool
from config import WORKSPACE_DIR, DEV_DIR

# Primary dev directory – pre-existing checkouts are found here before cloning.
PRIMARY_DEV_DIR = DEV_DIR

# Branches the agent is never allowed to push to directly.
PROTECTED_BRANCHES = {"main", "master"}


def _repo_path(repo_name: str) -> Path:
    """
    Resolve the local path for a repo.

    Resolution order:
      1. Absolute paths are used as-is.
      2. DEV_DIR/<repo_name>  – pre-existing checkout in the primary dev directory.
      3. WORKSPACE_DIR/<repo_name>  – agent-managed clones.
    """
    p = Path(repo_name)
    if p.is_absolute():
        return p
    primary = PRIMARY_DEV_DIR / repo_name
    if primary.exists():
        return primary
    return WORKSPACE_DIR / repo_name


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

    # Check primary dev dir first
    primary = PRIMARY_DEV_DIR / name
    if primary.exists():
        return f"Found existing checkout at {primary} – using that."

    # Check agent workspace
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
def write_file_in_repo(repo_name: str, relative_path: str, content: str) -> str:
    """
    Write (create or overwrite) a file inside a local repo.

    Args:
        repo_name:     Short name of the repo folder in the workspace, or absolute path.
        relative_path: Path inside the repo (e.g. src/MyService.groovy).
        content:       Full text content to write.

    Returns:
        Confirmation message with the file path written.
    """
    target = _repo_path(repo_name) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written: {target}"


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
def git_create_branch(repo_name: str, branch_name: str, from_branch: str = "main") -> str:
    """
    Create and checkout a new feature branch in a local repository.

    Always call this before making changes so that work is isolated from the
    default branch. The new branch is based on the latest commit of from_branch.

    Args:
        repo_name:   Short name of the repo folder in the workspace, or absolute path.
        branch_name: Name for the new branch (e.g. "feature/issue-42-add-reports").
        from_branch: Branch to base the new branch from (default: "main").

    Returns:
        Confirmation message, or an error.
    """
    import git

    if branch_name in PROTECTED_BRANCHES:
        return f"Error: '{branch_name}' is a protected branch name. Choose a feature branch name."
    try:
        repo = git.Repo(str(_repo_path(repo_name)))
        # Make sure we're up to date on the source branch
        repo.git.checkout(from_branch)
        repo.remotes.origin.pull()
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()
        return f"Created and checked out branch '{branch_name}' from '{from_branch}'."
    except Exception as e:
        return f"Error: {e}"


@tool
def git_commit_and_push(repo_name: str, message: str) -> str:
    """
    Stage all changes in a local repo, commit them, and push to origin.

    IMPORTANT: Will refuse to push to protected branches (main, master, develop).
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

