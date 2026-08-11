import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_toolkit_dir = Path(__file__).resolve().parents[2]
_gw_dir = _toolkit_dir / 'devscripts' / 'services' / 'generate_workspace'
_ew_dir = _toolkit_dir / 'devscripts' / 'services' / 'edit_workspace'
sys.path.insert(0, str(_toolkit_dir))
sys.path.insert(0, str(_gw_dir))
sys.path.insert(0, str(_ew_dir))

from devscripts.services.generate_workspace.select_repos import load_repos
from devscripts.services.edit_workspace import add_repos



class TestLoadReposWorktrees(unittest.TestCase):
    def test_detects_git_file_as_repo(self):
        # Create a dir with a .git FILE (worktree pattern)
        with tempfile.TemporaryDirectory() as base:
            wt = Path(base) / 'my-worktree'
            wt.mkdir()
            (wt / '.git').write_text('gitdir: /some/main/repo/.git/worktrees/my-worktree\n')
            result = load_repos(Path(base))
            self.assertIn('my-worktree', result)

    def test_git_file_and_git_dir_both_detected(self):
        with tempfile.TemporaryDirectory() as base:
            repo_a = Path(base) / 'repo-a'
            repo_b = Path(base) / 'repo-b'
            repo_a.mkdir(); (repo_a / '.git').mkdir()        # normal repo
            repo_b.mkdir(); (repo_b / '.git').write_text('gitdir: ...')  # worktree
            result = load_repos(Path(base))
            self.assertIn('repo-a', result)
            self.assertIn('repo-b', result)


class TestSelectReposLockedParam(unittest.TestCase):
    def test_locked_param_accepted(self):
        import inspect
        from select_repos import select_repos
        sig = inspect.signature(select_repos)
        self.assertIn('locked', sig.parameters)

    def test_locked_param_defaults_to_none(self):
        import inspect
        from select_repos import select_repos
        sig = inspect.signature(select_repos)
        self.assertIsNone(sig.parameters['locked'].default)


class TestAddReposManifestPatch(unittest.TestCase):
    def setUp(self):
        self.ws_dir = Path(tempfile.mkdtemp())
        self.toolkit_dir = _toolkit_dir
        ai_dir = self.ws_dir / '.ai-toolkit'
        ai_dir.mkdir()
        self.manifest_path = ai_dir / 'workspace.json'
        self.manifest_path.write_text(json.dumps({
            'schema_version': 1,
            'workspace': 'test-ws',
            'created_at': '2025-01-01T00:00:00-03:00',
            'toolkit_version': {'tag': 'v1.0.0', 'sha': 'abc123'},
            'repositories': [
                {'name': 'existing-repo', 'branch': 'test-ws', 'parent_branch': 'main'},
            ],
        }, indent=2))

    def tearDown(self):
        shutil.rmtree(str(self.ws_dir), ignore_errors=True)

    def _run_main(self, selected_repos, setup_side_effect=None):
        """Helper: run add_repos.main() with all TUI/git mocked."""
        from configure_workspace_repos import RepoConfig
        configs = [RepoConfig(name=r, mode='new', branch='test-ws', parent='main') for r in selected_repos]

        patches = [
            patch('generate_workspace.load_env', return_value={'AI_REPOSITORIES_DIR': '/fake/repos'}),
            patch('generate_workspace.resolve_repos_root', return_value=Path('/fake/repos')),
            patch('select_repos.select_repos', return_value=selected_repos),
            patch('configure_workspace_repos.configure_repos', return_value=configs),
            patch('configure_workspace_repos.pre_validate', return_value=[]),
            patch('generate_workspace.setup_repo_worktree', side_effect=setup_side_effect),
            patch('render_agents_md.render_agents_md', return_value='# CLAUDE.md content'),
            patch('sys.argv', ['add_repos.py', '--workspace-dir', str(self.ws_dir), '--toolkit-dir', str(self.toolkit_dir)]),
        ]
        with __import__('contextlib').ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            add_repos.main()

    def test_manifest_patched_in_place_preserves_created_at(self):
        self._run_main(['new-repo'])
        data = json.loads(self.manifest_path.read_text())
        self.assertEqual(data['created_at'], '2025-01-01T00:00:00-03:00')
        self.assertEqual(data['toolkit_version']['tag'], 'v1.0.0')
        names = [r['name'] for r in data['repositories']]
        self.assertIn('existing-repo', names)
        self.assertIn('new-repo', names)

    def test_new_repo_entry_has_correct_fields(self):
        self._run_main(['new-repo'])
        data = json.loads(self.manifest_path.read_text())
        new = next(r for r in data['repositories'] if r['name'] == 'new-repo')
        self.assertEqual(new['branch'], 'test-ws')
        self.assertEqual(new['parent_branch'], 'main')

    def test_existing_repo_not_duplicated(self):
        self._run_main(['new-repo'])
        data = json.loads(self.manifest_path.read_text())
        names = [r['name'] for r in data['repositories']]
        self.assertEqual(names.count('existing-repo'), 1)


class TestAddReposErrorHandling(unittest.TestCase):
    def setUp(self):
        self.ws_dir = Path(tempfile.mkdtemp())
        self.toolkit_dir = _toolkit_dir
        ai_dir = self.ws_dir / '.ai-toolkit'
        ai_dir.mkdir()
        self.manifest_path = ai_dir / 'workspace.json'
        self.manifest_path.write_text(json.dumps({
            'schema_version': 1,
            'workspace': 'test-ws',
            'created_at': '2025-01-01T00:00:00-03:00',
            'toolkit_version': {'tag': 'v1.0.0', 'sha': 'abc123'},
            'repositories': [
                {'name': 'existing-repo', 'branch': 'test-ws', 'parent_branch': 'main'},
            ],
        }, indent=2))

    def tearDown(self):
        shutil.rmtree(str(self.ws_dir), ignore_errors=True)

    def test_missing_manifest_exits_1(self):
        ws = Path(tempfile.mkdtemp())
        try:
            with patch('sys.argv', ['add_repos.py', '--workspace-dir', str(ws), '--toolkit-dir', str(_toolkit_dir)]):
                with self.assertRaises(SystemExit) as cm:
                    add_repos.main()
            self.assertEqual(cm.exception.code, 1)
        finally:
            shutil.rmtree(str(ws), ignore_errors=True)

    def test_missing_ai_repositories_dir_exits_1(self):
        with patch('generate_workspace.load_env', return_value={}), \
             patch.dict('os.environ', {}, clear=True), \
             patch('sys.argv', ['add_repos.py', '--workspace-dir', str(self.ws_dir), '--toolkit-dir', str(self.toolkit_dir)]):
            with self.assertRaises(SystemExit) as cm:
                add_repos.main()
        self.assertEqual(cm.exception.code, 1)

    def test_all_worktrees_fail_exits_1(self):
        from configure_workspace_repos import RepoConfig
        cfg = RepoConfig(name='new-repo', mode='new', branch='test-ws', parent='main')
        with patch('generate_workspace.load_env', return_value={'AI_REPOSITORIES_DIR': '/fake/repos'}), \
             patch('generate_workspace.resolve_repos_root', return_value=Path('/fake/repos')), \
             patch('select_repos.select_repos', return_value=['new-repo']), \
             patch('configure_workspace_repos.configure_repos', return_value=[cfg]), \
             patch('configure_workspace_repos.pre_validate', return_value=[]), \
             patch('generate_workspace.setup_repo_worktree', side_effect=RuntimeError('git error')), \
             patch('sys.argv', ['add_repos.py', '--workspace-dir', str(self.ws_dir), '--toolkit-dir', str(self.toolkit_dir)]):
            with self.assertRaises(SystemExit) as cm:
                add_repos.main()
        self.assertEqual(cm.exception.code, 1)

    def test_partial_worktree_failure_updates_manifest_with_succeeded(self):
        """If one repo fails but another succeeds, manifest gets only the succeeded one."""
        from configure_workspace_repos import RepoConfig
        configs = [
            RepoConfig(name='good-repo', mode='new', branch='test-ws', parent='main'),
            RepoConfig(name='bad-repo', mode='new', branch='test-ws', parent='main'),
        ]
        call_count = [0]
        def worktree_side_effect(repo_path, target, config):
            call_count[0] += 1
            if config.name == 'bad-repo':
                raise RuntimeError('git failed')
        with patch('generate_workspace.load_env', return_value={'AI_REPOSITORIES_DIR': '/fake/repos'}), \
             patch('generate_workspace.resolve_repos_root', return_value=Path('/fake/repos')), \
             patch('select_repos.select_repos', return_value=['good-repo', 'bad-repo']), \
             patch('configure_workspace_repos.configure_repos', return_value=configs), \
             patch('configure_workspace_repos.pre_validate', return_value=[]), \
             patch('generate_workspace.setup_repo_worktree', side_effect=worktree_side_effect), \
             patch('render_agents_md.render_agents_md', return_value=''), \
             patch('sys.argv', ['add_repos.py', '--workspace-dir', str(self.ws_dir), '--toolkit-dir', str(self.toolkit_dir)]):
            add_repos.main()
        data = json.loads(self.manifest_path.read_text())
        names = [r['name'] for r in data['repositories']]
        self.assertIn('good-repo', names)
        self.assertNotIn('bad-repo', names)

    def test_claude_md_regen_failure_does_not_crash(self):
        """render_agents_md failure should warn but not exit non-zero."""
        from configure_workspace_repos import RepoConfig
        cfg = RepoConfig(name='new-repo', mode='new', branch='test-ws', parent='main')
        with patch('generate_workspace.load_env', return_value={'AI_REPOSITORIES_DIR': '/fake/repos'}), \
             patch('generate_workspace.resolve_repos_root', return_value=Path('/fake/repos')), \
             patch('select_repos.select_repos', return_value=['new-repo']), \
             patch('configure_workspace_repos.configure_repos', return_value=[cfg]), \
             patch('configure_workspace_repos.pre_validate', return_value=[]), \
             patch('generate_workspace.setup_repo_worktree'), \
             patch('render_agents_md.render_agents_md', side_effect=KeyError('workspace_name')), \
             patch('sys.argv', ['add_repos.py', '--workspace-dir', str(self.ws_dir), '--toolkit-dir', str(self.toolkit_dir)]):
            # Should NOT raise — CLAUDE.md failure is caught and warned
            add_repos.main()
        # Manifest should still be updated
        data = json.loads(self.manifest_path.read_text())
        names = [r['name'] for r in data['repositories']]
        self.assertIn('new-repo', names)


if __name__ == '__main__':
    unittest.main()
