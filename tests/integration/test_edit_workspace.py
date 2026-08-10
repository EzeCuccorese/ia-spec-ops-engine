"""
Integration tests for workspace env resolution and project root discovery.
"""

from pathlib import Path
from devscripts.core.finder import find_project_root, parse_dotenv, resolve_local_env

def test_resolve_local_env_in_repo(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=8080\nDB_HOST=localhost\n")

    root = find_project_root(tmp_path)
    assert root == tmp_path

    resolved = resolve_local_env(tmp_path, "my-repo")
    assert resolved == env_file

    parsed = parse_dotenv(resolved)
    assert parsed.get("PORT") == "8080"
    assert parsed.get("DB_HOST") == "localhost"
