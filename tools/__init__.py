"""Tools package – all custom LangChain tools live here."""
from tools.shell import run_powershell, list_available_modules
from tools.web_tool import fetch_url, post_platform_api, get_platform_token, get_platform_api_spec
from tools.git_tool import (
    git_clone,
    git_create_branch,
    git_commit_and_push,
    git_status,
    read_file_in_repo,
    list_repo_files,
    write_file_in_repo,
)
from tools.test_runner import run_tests
from tools.code_search import search_local_code

LOCAL_TOOLS = [
    # Shell
    run_powershell,
    list_available_modules,
    # Web / platform
    get_platform_token,
    fetch_url,
    post_platform_api,
    get_platform_api_spec,
    # Git / repo
    git_clone,
    git_create_branch,
    read_file_in_repo,
    list_repo_files,
    write_file_in_repo,
    git_status,
    git_commit_and_push,
    # Tests
    run_tests,
    # Search
    search_local_code,
]

__all__ = ["LOCAL_TOOLS"]

