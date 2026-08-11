import sys
import tempfile
import unittest
from pathlib import Path

_GW_DIR = Path(__file__).resolve().parents[3] / "devscripts" / "services" / "generate_workspace"
sys.path.insert(0, str(_GW_DIR))
from devscripts.services.generate_workspace.render_agents_md import render_agents_md



class TestRenderAgentsMd(unittest.TestCase):
    def setUp(self):
        self.template = tempfile.NamedTemporaryFile(mode='w', suffix='.template', delete=False)
        self.template.write(
            '# Workspace: {workspace_name}\n'
            'Repos dir: {repos_dir}\n'
            '{repo_list}\n'
        )
        self.template.close()

    def tearDown(self):
        Path(self.template.name).unlink(missing_ok=True)

    def test_substitutes_workspace_name(self):
        result = render_agents_md(self.template.name, 'my-ws', 'repositories', [])
        self.assertIn('# Workspace: my-ws', result)

    def test_substitutes_repos_dir(self):
        result = render_agents_md(self.template.name, 'ws', 'repositories', [])
        self.assertIn('Repos dir: repositories', result)

    def test_substitutes_repo_list(self):
        result = render_agents_md(self.template.name, 'ws', 'repositories', ['repo-a', 'repo-b'])
        self.assertIn('- repo-a', result)
        self.assertIn('- repo-b', result)

    def test_empty_repo_list(self):
        result = render_agents_md(self.template.name, 'ws', 'repositories', [])
        self.assertNotIn('{repo_list}', result)


if __name__ == '__main__':
    unittest.main()
