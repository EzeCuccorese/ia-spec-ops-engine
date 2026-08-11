import os
import sys
import unittest
import tempfile
from pathlib import Path

_toolkit_dir = Path(__file__).resolve().parent.parent.parent
_gw_dir = _toolkit_dir / 'devscripts' / 'services' / 'generate_workspace'
sys.path.insert(0, str(_toolkit_dir))
sys.path.insert(0, str(_gw_dir))


from generate_workspace import (
    load_env,
    resolve_repos_root,
    validate_workspace_name,
    check_supported_environment,
    _under_mnt,
)
from configure_workspace_repos import RepoConfig
from select_repos import load_repos, apply_filter


class TestLoadEnv(unittest.TestCase):
    def test_loads_key_value_pairs(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('AI_REPOSITORIES_DIR=../repositories\n')
            f.write('ANOTHER_VAR=some-value\n')
            f.write('# comment line\n')
            f.write('\n')
            name = f.name
        try:
            result = load_env(Path(name))
            self.assertEqual(result['AI_REPOSITORIES_DIR'], '../repositories')
            self.assertEqual(result['ANOTHER_VAR'], 'some-value')
            self.assertNotIn('# comment line', result)
        finally:
            os.unlink(name)

    def test_returns_empty_dict_when_file_missing(self):
        result = load_env(Path('/nonexistent/.env'))
        self.assertEqual(result, {})


class TestSupportedEnvironment(unittest.TestCase):
    def test_under_mnt_true_for_mnt_paths(self):
        self.assertTrue(_under_mnt(Path('/mnt/c/Users/x/repo')))
        self.assertTrue(_under_mnt(Path('/mnt')))

    def test_under_mnt_false_for_linux_paths(self):
        self.assertFalse(_under_mnt(Path('/home/u/dev/repo')))
        self.assertFalse(_under_mnt(Path('/mntfoo/x')))

    def test_under_mnt_resolves_relative_components(self):
        # `..` that escapes /mnt must not be a false positive
        self.assertFalse(_under_mnt(Path('/mnt/c/../../home/u/repo')))

    def test_native_windows_platform_aborts(self):
        with self.assertRaises(SystemExit):
            check_supported_environment(
                'win32', False, Path('/home/u/tk'), Path('/home/u/repos'))

    def test_msys_platform_aborts(self):
        with self.assertRaises(SystemExit):
            check_supported_environment(
                'msys', False, Path('/home/u/tk'), Path('/home/u/repos'))

    def test_wsl_toolkit_on_mnt_aborts(self):
        with self.assertRaises(SystemExit):
            check_supported_environment(
                'linux', True, Path('/mnt/c/dev/tk'), Path('/home/u/repos'))

    def test_wsl_repos_on_mnt_aborts(self):
        with self.assertRaises(SystemExit):
            check_supported_environment(
                'linux', True, Path('/home/u/tk'), Path('/mnt/c/dev/repos'))

    def test_wsl_clean_layout_passes(self):
        # returns None, no raise
        self.assertIsNone(check_supported_environment(
            'linux', True, Path('/home/u/tk'), Path('/home/u/repos')))

    def test_macos_passes(self):
        self.assertIsNone(check_supported_environment(
            'darwin', False, Path('/Users/u/tk'), Path('/Users/u/repos')))

    def test_native_linux_mnt_not_flagged(self):
        # /mnt on a non-WSL Linux host is an ordinary mount, not the bridge
        self.assertIsNone(check_supported_environment(
            'linux', False, Path('/mnt/data/tk'), Path('/mnt/data/repos')))

    def test_repos_dir_none_skips_repo_check(self):
        self.assertIsNone(check_supported_environment(
            'linux', True, Path('/home/u/tk'), None))


class TestValidateWorkspaceName(unittest.TestCase):
    def test_valid_names(self):
        self.assertTrue(validate_workspace_name('my-feature'))
        self.assertTrue(validate_workspace_name('feat_123'))
        self.assertTrue(validate_workspace_name('ABC'))

    def test_invalid_names(self):
        self.assertFalse(validate_workspace_name(''))
        self.assertFalse(validate_workspace_name('has space'))
        self.assertFalse(validate_workspace_name('has/slash'))
        self.assertFalse(validate_workspace_name('has.dot'))


class TestResolveReposRoot(unittest.TestCase):
    def test_absolute_path_used_as_is(self):
        with tempfile.TemporaryDirectory() as d:
            result = resolve_repos_root(Path('/some/toolkit'), Path(d))
            self.assertEqual(result, Path(d))

    def test_relative_path_anchored_to_toolkit(self):
        with tempfile.TemporaryDirectory() as base:
            toolkit = Path(base) / 'toolkit'
            repos = Path(base) / 'repositories'   # must match '../repositories'
            toolkit.mkdir()
            repos.mkdir()
            result = resolve_repos_root(toolkit, Path('../repositories'))
            self.assertEqual(result.resolve(), repos.resolve())

    def test_raises_for_nonexistent_path(self):
        with self.assertRaises(SystemExit):
            resolve_repos_root(Path('/tmp'), Path('/nonexistent/repos'))


class TestRepoConfig(unittest.TestCase):
    def test_new_branch_config(self):
        cfg = RepoConfig(name='my-repo', mode='new', branch='feat/x', parent='main')
        self.assertEqual(cfg.name, 'my-repo')
        self.assertEqual(cfg.mode, 'new')
        self.assertIsNotNone(cfg.parent)

    def test_existing_branch_config(self):
        cfg = RepoConfig(name='my-repo', mode='existing', branch='feat/x', parent=None)
        self.assertIsNone(cfg.parent)


class TestLoadRepos(unittest.TestCase):
    def test_returns_dirs_with_git(self):
        with tempfile.TemporaryDirectory() as base:
            repo_a = Path(base) / 'repo-a'
            repo_b = Path(base) / 'repo-b'
            plain  = Path(base) / 'plain'
            repo_a.mkdir(); (repo_a / '.git').mkdir()
            repo_b.mkdir(); (repo_b / '.git').mkdir()
            plain.mkdir()  # no .git
            result = load_repos(Path(base))
            self.assertIn('repo-a', result)
            self.assertIn('repo-b', result)
            self.assertNotIn('plain', result)

    def test_returns_empty_for_missing_dir(self):
        result = load_repos(Path('/nonexistent'))
        self.assertEqual(result, [])


class TestApplyFilter(unittest.TestCase):
    repos = ['valiant-rural-productor', 'gres-grecosystem-bff', 'valiant-rural-proveedor']

    def test_empty_query_returns_all(self):
        self.assertEqual(apply_filter(self.repos, ''), self.repos)

    def test_case_insensitive_substring_match(self):
        result = apply_filter(self.repos, 'VALIANT')
        self.assertIn('valiant-rural-productor', result)
        self.assertIn('valiant-rural-proveedor', result)
        self.assertNotIn('gres-grecosystem-bff', result)

    def test_no_match_returns_empty(self):
        result = apply_filter(self.repos, 'zzz')
        self.assertEqual(result, [])


from unittest.mock import patch, MagicMock
from configure_workspace_repos import (
    fetch_branches,
    pre_validate,
    RepoConfig,
)


class TestFetchBranches(unittest.TestCase):
    def test_deduplicates_local_and_remote(self):
        mock_output = 'main\ndevelop\nfeat/x\nremotes/origin/main\nremotes/origin/feat/y\n'
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            result = fetch_branches(Path('/fake/repo'))
        self.assertIn('main', result)
        self.assertIn('develop', result)
        self.assertIn('feat/x', result)
        self.assertIn('feat/y', result)
        self.assertEqual(len(result), len(set(result)))  # no duplicates

    def test_strips_origin_prefix(self):
        mock_output = 'remotes/origin/my-branch\n'
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            result = fetch_branches(Path('/fake/repo'))
        self.assertIn('my-branch', result)
        self.assertNotIn('origin/my-branch', result)
        self.assertNotIn('remotes/origin/my-branch', result)

    def test_filters_head(self):
        mock_output = 'remotes/origin/HEAD\nremotes/origin/main\n'
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            result = fetch_branches(Path('/fake/repo'))
        self.assertNotIn('HEAD', result)
        self.assertIn('main', result)


class TestPreValidate(unittest.TestCase):
    def _make_config(self, name, mode, branch, parent=None):
        return RepoConfig(name=name, mode=mode, branch=branch, parent=parent)

    def test_no_errors_for_clean_new_branch(self):
        configs = [self._make_config('repo-a', 'new', 'feat/x', 'main')]
        with tempfile.TemporaryDirectory() as repos_root:
            repo = Path(repos_root) / 'repo-a'
            repo.mkdir()
            repo_paths = {'repo-a': repo}
            with patch('subprocess.run') as mock_run:
                def side_effect(cmd, **kwargs):
                    m = MagicMock()
                    if 'worktree' in cmd:
                        m.stdout = 'worktree /some/main\nHEAD abc\nbranch refs/heads/main\n'
                    elif 'refs/heads/feat/x' in cmd:
                        m.returncode = 1
                    elif 'main' in cmd:
                        m.returncode = 0
                    else:
                        m.returncode = 1
                    return m
                mock_run.side_effect = side_effect
                errors = pre_validate(configs, repo_paths)
        self.assertEqual(errors, [])

    def test_error_when_existing_branch_in_another_worktree(self):
        configs = [self._make_config('repo-a', 'existing', 'feat/active', None)]
        with tempfile.TemporaryDirectory() as repos_root:
            repo = Path(repos_root) / 'repo-a'
            repo.mkdir()
            repo_paths = {'repo-a': repo}
            with patch('subprocess.run') as mock_run:
                def side_effect(cmd, **kwargs):
                    m = MagicMock()
                    if 'worktree' in cmd:
                        m.stdout = (
                            'worktree /workspaces/other/repositories/repo-a\n'
                            'HEAD abc\n'
                            'branch refs/heads/feat/active\n\n'
                        )
                        m.returncode = 0
                    else:
                        m.returncode = 0
                    return m
                mock_run.side_effect = side_effect
                errors = pre_validate(configs, repo_paths)
        self.assertEqual(len(errors), 1)
        self.assertIn('repo-a', errors[0])
        self.assertIn('feat/active', errors[0])

    def test_error_when_parent_branch_missing(self):
        configs = [self._make_config('repo-a', 'new', 'feat/x', 'nonexistent-parent')]
        with tempfile.TemporaryDirectory() as repos_root:
            repo = Path(repos_root) / 'repo-a'
            repo.mkdir()
            repo_paths = {'repo-a': repo}
            with patch('subprocess.run') as mock_run:
                def side_effect(cmd, **kwargs):
                    m = MagicMock()
                    if 'worktree' in cmd:
                        m.stdout = ''
                        m.returncode = 0
                    else:
                        m.returncode = 1  # all rev-parse calls fail
                    return m
                mock_run.side_effect = side_effect
                errors = pre_validate(configs, repo_paths)
        self.assertEqual(len(errors), 1)
        self.assertIn('nonexistent-parent', errors[0])

    def test_error_when_repo_name_not_in_dict(self):
        configs = [self._make_config('repo-missing', 'new', 'feat/x', 'main')]
        errors = pre_validate(configs, {})  # empty dict — name not present
        self.assertEqual(len(errors), 1)
        self.assertIn('repo-missing', errors[0])


from configure_workspace_repos import configure_repos


class TestConfigureReposEmpty(unittest.TestCase):
    def test_empty_repo_names_returns_empty_list(self):
        result = configure_repos(
            workspace_name='my-ws',
            repo_names=[],
            repo_paths={},
        )
        self.assertEqual(result, [])


class TestParseRepoArg(unittest.TestCase):
    def setUp(self):
        # Import here so the test class can be defined before the function exists
        from generate_workspace import _parse_repo_arg
        self._parse = _parse_repo_arg

    def test_bare_name_creates_new_branch_from_main(self):
        cfg, name = self._parse('my-repo', 'my-workspace')
        self.assertEqual(name, 'my-repo')
        self.assertEqual(cfg.mode, 'new')
        self.assertEqual(cfg.branch, 'my-workspace')
        self.assertEqual(cfg.parent, 'main')

    def test_colon_syntax_sets_custom_parent(self):
        cfg, name = self._parse('my-repo:develop', 'my-workspace')
        self.assertEqual(name, 'my-repo')
        self.assertEqual(cfg.mode, 'new')
        self.assertEqual(cfg.branch, 'my-workspace')
        self.assertEqual(cfg.parent, 'develop')

    def test_at_syntax_sets_existing_branch(self):
        cfg, name = self._parse('my-repo@feat/x', 'my-workspace')
        self.assertEqual(name, 'my-repo')
        self.assertEqual(cfg.mode, 'existing')
        self.assertEqual(cfg.branch, 'feat/x')
        self.assertIsNone(cfg.parent)

    def test_toolkit_bare_name(self):
        cfg, name = self._parse('ai-dev-toolkit', 'my-workspace')
        self.assertEqual(name, 'ai-dev-toolkit')
        self.assertEqual(cfg.mode, 'new')
        self.assertEqual(cfg.branch, 'my-workspace')
        self.assertEqual(cfg.parent, 'main')

    def test_toolkit_at_syntax(self):
        cfg, name = self._parse('ai-dev-toolkit@existing-branch', 'my-workspace')
        self.assertEqual(name, 'ai-dev-toolkit')
        self.assertEqual(cfg.mode, 'existing')
        self.assertEqual(cfg.branch, 'existing-branch')
        self.assertIsNone(cfg.parent)


from unittest.mock import patch, call, MagicMock
from generate_workspace import setup_repo_worktree


class TestSetupRepoWorktree(unittest.TestCase):
    def test_new_branch_calls_worktree_add_b(self):
        cfg = RepoConfig(name='r', mode='new', branch='feat/x', parent='main')
        log = []

        def fake_run(cmd, **kwargs):
            log.append(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ''
            return m

        with tempfile.TemporaryDirectory() as tmp:
            repo_path = Path(tmp) / 'repo'
            target = Path(tmp) / 'target'
            repo_path.mkdir()
            with patch('subprocess.run', side_effect=fake_run):
                setup_repo_worktree(repo_path, target, cfg)

        cmd_str = ' '.join(str(c) for c in log[-1])
        self.assertIn('worktree', cmd_str)
        self.assertIn('add', cmd_str)
        self.assertIn('-b', cmd_str)
        self.assertIn('feat/x', cmd_str)

    def test_existing_local_branch_calls_worktree_add_without_b(self):
        cfg = RepoConfig(name='r', mode='existing', branch='develop', parent=None)
        log = []

        def fake_run(cmd, **kwargs):
            log.append(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ''
            return m

        with tempfile.TemporaryDirectory() as tmp:
            repo_path = Path(tmp) / 'repo'
            target = Path(tmp) / 'target'
            repo_path.mkdir()
            with patch('subprocess.run', side_effect=fake_run):
                setup_repo_worktree(repo_path, target, cfg)

        worktree_cmds = [c for c in log if 'worktree' in c and 'add' in c]
        self.assertTrue(worktree_cmds, 'Expected at least one worktree add command')
        final_cmd = worktree_cmds[-1]
        self.assertNotIn('-b', final_cmd)

    def test_existing_remote_only_branch_fetches_then_tracks(self):
        from configure_workspace_repos import RepoConfig as CfgRC
        cfg = CfgRC(name='r', mode='existing', branch='feat/remote', parent=None)
        cfg.mark_remote_only()
        log = []

        def fake_run(cmd, **kwargs):
            log.append(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ''
            return m

        with tempfile.TemporaryDirectory() as tmp:
            repo_path = Path(tmp) / 'repo'
            target = Path(tmp) / 'target'
            repo_path.mkdir()
            with patch('subprocess.run', side_effect=fake_run):
                setup_repo_worktree(repo_path, target, cfg)

        fetch_cmds = [c for c in log if 'fetch' in c]
        self.assertTrue(fetch_cmds, 'Expected a git fetch command for remote-only branch')


if __name__ == '__main__':
    unittest.main()
