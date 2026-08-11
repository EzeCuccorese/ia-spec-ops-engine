import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_TOOLKIT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_TOOLKIT_DIR / "devscripts" / "services" / "generate_workspace"))

from devscripts.services.generate_workspace import generate_workspace
from devscripts.services.generate_workspace.generate_workspace import create_workspace

TOOLKIT_DIR = _TOOLKIT_DIR



def _call_create_workspace(**kwargs):
    """Call create_workspace with os.execv and os.chdir patched out."""
    with patch('os.execv'), patch('os.chdir'):
        create_workspace(**kwargs)


class TestCreateWorkspace(unittest.TestCase):
    def setUp(self):
        self.workspaces_root = Path(tempfile.mkdtemp())
        self.workspace_name = 'test-ws'
        self.workspace_dir = self.workspaces_root / self.workspace_name

    def tearDown(self):
        shutil.rmtree(str(self.workspaces_root), ignore_errors=True)

    def test_no_symlinks_in_scripts(self):
        _call_create_workspace(
            workspace_name=self.workspace_name,
            toolkit_dir=TOOLKIT_DIR,
            workspaces_root=self.workspaces_root,
            repo_configs=[],
            repo_paths={},
        )
        scripts_dir = self.workspace_dir / 'scripts'
        if scripts_dir.exists():
            self.assertFalse(scripts_dir.is_symlink(), 'scripts/ must not be a symlink')

    def test_no_symlinks_in_docker(self):
        _call_create_workspace(
            workspace_name=self.workspace_name,
            toolkit_dir=TOOLKIT_DIR,
            workspaces_root=self.workspaces_root,
            repo_configs=[],
            repo_paths={},
        )
        docker_dir = self.workspace_dir / 'docker'
        self.assertTrue(docker_dir.exists())
        self.assertFalse(docker_dir.is_symlink(), 'docker/ must not be a symlink')

    def test_skills_and_specify_are_copies_not_symlinks(self):
        _call_create_workspace(
            workspace_name=self.workspace_name,
            toolkit_dir=TOOLKIT_DIR,
            workspaces_root=self.workspaces_root,
            repo_configs=[],
            repo_paths={},
        )
        for dir_name in ('skills', '.specify'):
            p = self.workspace_dir / dir_name
            if p.exists():
                self.assertFalse(p.is_symlink(), f'{dir_name} must not be a symlink')

    def test_sync_toolkit_copied(self):
        _call_create_workspace(
            workspace_name=self.workspace_name,
            toolkit_dir=TOOLKIT_DIR,
            workspaces_root=self.workspaces_root,
            repo_configs=[],
            repo_paths={},
        )
        self.assertTrue((self.workspace_dir / 'skills').exists())


    def test_config_is_still_symlink(self):
        _call_create_workspace(
            workspace_name=self.workspace_name,
            toolkit_dir=TOOLKIT_DIR,
            workspaces_root=self.workspaces_root,
            repo_configs=[],
            repo_paths={},
        )
        config = self.workspace_dir / 'config'
        self.assertTrue(config.is_symlink(), 'config/ must remain a symlink')

    def test_edit_workspace_copied(self):
        _call_create_workspace(
            workspace_name=self.workspace_name,
            toolkit_dir=TOOLKIT_DIR,
            workspaces_root=self.workspaces_root,
            repo_configs=[],
            repo_paths={},
        )
        self.assertTrue(
            (self.workspace_dir / '.specify').exists() or (self.workspace_dir / 'skills').exists(),
            'workspace structure must be created in the workspace',
        )

    def test_toolkit_menu_tests_dir_excluded_from_workspace_copy(self):
        """bin/toolkit-menu/tests/ (incl. test-ensure-textual.bats) must NOT be
        copied into the workspace — copytree's ignore_patterns('__pycache__',
        'tests') already covers this; this asserts the invariant holds for the
        new Slice-1 test file specifically (T1.22 verify, no production change)."""
        _call_create_workspace(
            workspace_name=self.workspace_name,
            toolkit_dir=TOOLKIT_DIR,
            workspaces_root=self.workspaces_root,
            repo_configs=[],
            repo_paths={},
        )
        menu_tests_dir = self.workspace_dir / 'bin' / 'toolkit-menu' / 'tests'
        self.assertFalse(
            menu_tests_dir.exists(),
            'bin/toolkit-menu/tests/ must be excluded from the workspace copy',
        )


class TestWorktreeCleanupOnFailure(unittest.TestCase):
    """When worktree creation fails partway through, the worktrees already
    created in the source repos must be unregistered so they don't leave
    orphaned entries that block future `git worktree add`."""

    def setUp(self):
        self.workspaces_root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(str(self.workspaces_root), ignore_errors=True)

    def test_partial_failure_removes_successful_worktrees(self):
        names = ['repo-a', 'repo-b', 'repo-c']
        repo_configs = [
            SimpleNamespace(name=n, branch='feat', mode='new', parent='main')
            for n in names
        ]
        repo_paths = {n: Path(f'/fake/{n}') for n in names}

        # Fail on the 3rd repo; the first two were created successfully.
        def _setup(src, target, cfg):
            if cfg.name == 'repo-c':
                raise RuntimeError('boom')

        git_mock = patch('devscripts.services.generate_workspace.generate_workspace._git').start()
        self.addCleanup(patch.stopall)

        with patch('devscripts.services.generate_workspace.generate_workspace.setup_repo_worktree', side_effect=_setup), \
             patch('os.execv'), patch('os.chdir'):
            with self.assertRaises(SystemExit):
                create_workspace(
                    workspace_name='cleanup-ws',
                    toolkit_dir=TOOLKIT_DIR,
                    workspaces_root=self.workspaces_root,
                    repo_configs=repo_configs,
                    repo_paths=repo_paths,
                )

        removed = [
            call.args for call in git_mock.call_args_list
            if len(call.args) >= 2 and call.args[1] == 'worktree' and 'remove' in call.args
        ]
        removed_targets = {args[-1] for args in removed}
        self.assertIn(str(self.workspaces_root / 'cleanup-ws' / 'repositories' / 'repo-a'), removed_targets)
        self.assertIn(str(self.workspaces_root / 'cleanup-ws' / 'repositories' / 'repo-b'), removed_targets)
        # repo-c never succeeded, so it must NOT be in the cleanup set.
        self.assertNotIn(str(self.workspaces_root / 'cleanup-ws' / 'repositories' / 'repo-c'), removed_targets)


class TestInstallHostDeps(unittest.TestCase):
    """install_host_deps runs `install-deps.sh --local` for node repos only
    (host worktree node_modules for husky/commit), and is skippable + non-fatal."""

    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        (self.ws / 'scripts').mkdir()
        (self.ws / 'scripts' / 'install-deps.sh').write_text('#!/bin/bash\nexit 0\n')
        self.repos = self.ws / 'repositories'
        # one node repo (has package.json), one gradle repo (no package.json)
        (self.repos / 'web').mkdir(parents=True)
        (self.repos / 'web' / 'package.json').write_text('{}')
        (self.repos / 'svc').mkdir(parents=True)
        (self.repos / 'svc' / 'build.gradle').write_text('')
        self.configs = [SimpleNamespace(name='web'), SimpleNamespace(name='svc')]

    def tearDown(self):
        shutil.rmtree(str(self.ws), ignore_errors=True)

    def _local_calls(self, mock_run):
        return [c for c in mock_run.call_args_list
                if '--local' in c.args[0]]

    def test_installs_node_repo_only(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = SimpleNamespace(returncode=0)
            generate_workspace.install_host_deps(self.ws, self.configs, self.repos)
        calls = self._local_calls(mock_run)
        self.assertEqual(len(calls), 1, 'only the node repo should be installed')
        self.assertIn('web', calls[0].args[0])
        self.assertNotIn('svc', calls[0].args[0])

    def test_multiple_node_repos_single_call(self):
        # A second node repo — both must go into ONE install-deps invocation
        # (install-workspace installs them in parallel), not one call per repo.
        (self.repos / 'admin').mkdir(parents=True)
        (self.repos / 'admin' / 'package.json').write_text('{}')
        configs = [SimpleNamespace(name='web'),
                   SimpleNamespace(name='admin'),
                   SimpleNamespace(name='svc')]
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = SimpleNamespace(returncode=0)
            generate_workspace.install_host_deps(self.ws, configs, self.repos)
        calls = self._local_calls(mock_run)
        self.assertEqual(len(calls), 1, 'all node repos must share a single call')
        cmd = calls[0].args[0]
        self.assertIn('web', cmd)
        self.assertIn('admin', cmd)
        self.assertNotIn('svc', cmd)

    def test_no_node_repos_is_noop(self):
        gradle_only = [SimpleNamespace(name='svc')]
        with patch('subprocess.run') as mock_run:
            generate_workspace.install_host_deps(self.ws, gradle_only, self.repos)
        self.assertEqual(self._local_calls(mock_run), [],
                         'no node repos -> no install-deps call')

    def test_nonzero_exit_is_non_fatal(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = SimpleNamespace(returncode=1)
            # must not raise even though the install "failed"
            generate_workspace.install_host_deps(self.ws, self.configs, self.repos)


if __name__ == '__main__':
    unittest.main()
