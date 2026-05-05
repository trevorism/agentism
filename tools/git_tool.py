"""Git tools – clone repos, write files, commit, and push using GitPython."""
from pathlib import Path
from langchain_core.tools import tool
from config import WORKSPACE_DIR, DEV_DIR
import config

# Primary dev directory – pre-existing checkouts are found here before cloning.
PRIMARY_DEV_DIR = DEV_DIR

# Branches the agent is never allowed to push to directly.
PROTECTED_BRANCHES = {"master"}


def _find_repo(name: str) -> Path | None:
    """
    Search DEV_DIR for a directory named `name`.

    Checks two levels deep so repos nested under subdirectories
    are found alongside top-level ones.
    Returns the first match, or None if not found.
    """
    if not DEV_DIR or not DEV_DIR.exists():
        return None

    # Level 1 – DEV_DIR/<name>
    candidate = DEV_DIR / name
    if candidate.exists():
        return candidate

    # Level 2 – DEV_DIR/<subdir>/<name>
    try:
        for subdir in DEV_DIR.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("."):
                candidate = subdir / name
                if candidate.exists():
                    return candidate
    except PermissionError:
        pass

    return None


def _repo_path(repo_name: str) -> Path:
    """
    Resolve the local path for a repo.

    Resolution order:
      1. Absolute paths are used as-is.
      2. DEV_DIR/<repo_name>          – direct child of primary dev directory.
      3. DEV_DIR/<subdir>/<repo_name>  – one level nested.
      4. WORKSPACE_DIR/<repo_name>     – agent-managed clones.

    Raises ValueError if repo_name is '.' or empty — the agent must supply
    the actual repository folder name, not a relative path placeholder.
    """
    if not repo_name or repo_name.strip() in (".", ".."):
        raise ValueError(
            "repo_name must be the repository folder name (e.g. 'my-repo'), "
            "not '.' or empty. Use list_repo_files with the actual repo name."
        )
    p = Path(repo_name)
    if p.is_absolute():
        return p
    found = _find_repo(repo_name)
    if found:
        return found
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

    found = _find_repo(name)
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
def read_file_in_repo(repo_name: str, relative_path: str) -> str:
    """
    Read the full contents of a file inside a local repository.

    Always use this to inspect existing source files before modifying them.
    Never assume file contents – read first, then write.

    Args:
        repo_name:     Repo folder name (located in DEV_DIR automatically), or absolute path.
        relative_path: Path inside the repo (e.g. src/main/groovy/MyService.groovy).

    Returns:
        Full file contents as text, or an error message.
    """
    target = _repo_path(repo_name) / relative_path
    if not target.exists():
        return f"File not found: {target}"
    if not target.is_file():
        return f"Path is not a file: {target}"
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def list_repo_files(repo_name: str, subdir: str = "", pattern: str = "*") -> str:
    """
    List files in a local repository directory, optionally filtered by glob pattern.

    .git internals are always excluded to keep output focused on source files.

    Use this to understand repo structure before reading or writing files.
    Never assume what files exist – list them first.

    Args:
        repo_name: Short name of the repo folder (checked in DEV_DIR first), or absolute path.
        subdir:    Subdirectory inside the repo to list (default: repo root).
        pattern:   Glob pattern to filter results (default: "*" for all files).
                   Use "**/*.groovy" for recursive Groovy files, "*.json" for JSON, etc.

    Returns:
        Newline-separated relative file paths, or an error message.
    """
    root = _repo_path(repo_name)
    search_dir = root / subdir if subdir else root
    if not search_dir.exists():
        return f"Directory not found: {search_dir}"
    try:
        files = sorted(search_dir.glob(pattern))
        visible_files = [
            f for f in files
            if f.is_file() and ".git" not in f.relative_to(root).parts
        ]
        if not visible_files:
            return f"No files matching '{pattern}' in {search_dir}"
        return "\n".join(str(f.relative_to(root)) for f in visible_files)
    except Exception as e:
        return f"Error listing files: {e}"


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
    if config.DRY_RUN:
        preview = content[:200] + ("…" if len(content) > 200 else "")
        return f"[DRY-RUN] Would write {len(content)} chars to: {target}\nPreview:\n{preview}"
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
