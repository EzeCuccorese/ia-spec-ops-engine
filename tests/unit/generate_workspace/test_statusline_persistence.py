import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_GW_DIR = Path(__file__).resolve().parents[3] / "devscripts" / "services" / "generate_workspace"
sys.path.insert(0, str(_GW_DIR))
from devscripts.services.generate_workspace import generate_workspace
from devscripts.services.generate_workspace.generate_workspace import resolve_ai_statusline, parse_ai_statusline_env



class TestParseAiStatuslineEnv(unittest.TestCase):
    """Malformed persisted value must be treated as unset, not silently coerced."""

    def test_true_variants(self):
        for v in ('true', 'True', 'TRUE'):
            self.assertTrue(parse_ai_statusline_env(v))

    def test_false_variants(self):
        for v in ('false', 'False', 'FALSE'):
            self.assertFalse(parse_ai_statusline_env(v))

    def test_missing_is_none(self):
        self.assertIsNone(parse_ai_statusline_env(''))
        self.assertIsNone(parse_ai_statusline_env(None))

    def test_malformed_is_none(self):
        self.assertIsNone(parse_ai_statusline_env('maybe'))
        self.assertIsNone(parse_ai_statusline_env('1'))
        self.assertIsNone(parse_ai_statusline_env('yes'))


class TestResolveAiStatusline(unittest.TestCase):
    """resolve_ai_statusline implements the precedence:
    --no-ai-statusline (one-off, no persist) > persisted AI_STATUSLINE >
    interactive prompt (persists the answer). Direct mode and EOF/interrupt
    never persist.
    """

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.env', delete=False)
        self.env_file = Path(self.tmp.name)
        self.env_file.write_text('FOO=bar\n')

    def tearDown(self):
        self.env_file.unlink(missing_ok=True)

    def test_prompt_skipped_when_persisted_value_set(self):
        self.env_file.write_text('FOO=bar\nAI_STATUSLINE=false\n')
        with patch('devscripts.services.generate_workspace.generate_workspace._prompt_ai_statusline') as mock_prompt:
            result = resolve_ai_statusline(
                env={'AI_STATUSLINE': 'false'},
                cli_flag_disabled=False,
                interactive=True,
                env_file=self.env_file,
            )
        mock_prompt.assert_not_called()
        self.assertFalse(result)

    def test_prompt_shown_and_persisted_when_unset(self):
        with patch('devscripts.services.generate_workspace.generate_workspace._prompt_ai_statusline', return_value=True) as mock_prompt:
            result = resolve_ai_statusline(
                env={},
                cli_flag_disabled=False,
                interactive=True,
                env_file=self.env_file,
            )
        mock_prompt.assert_called_once()
        self.assertTrue(result)
        self.assertIn('AI_STATUSLINE=true', self.env_file.read_text())

    def test_flag_overrides_without_persisting(self):
        self.env_file.write_text('FOO=bar\nAI_STATUSLINE=true\n')
        with patch('devscripts.services.generate_workspace.generate_workspace._prompt_ai_statusline') as mock_prompt:
            result = resolve_ai_statusline(
                env={'AI_STATUSLINE': 'true'},
                cli_flag_disabled=True,
                interactive=True,
                env_file=self.env_file,
            )
        mock_prompt.assert_not_called()
        self.assertFalse(result, 'flag disables this run only')
        # persisted value must remain untouched
        self.assertIn('AI_STATUSLINE=true', self.env_file.read_text())

    def test_malformed_value_treated_as_unset_and_prompts(self):
        with patch('devscripts.services.generate_workspace.generate_workspace._prompt_ai_statusline', return_value=False) as mock_prompt:
            result = resolve_ai_statusline(
                env={'AI_STATUSLINE': 'maybe'},
                cli_flag_disabled=False,
                interactive=True,
                env_file=self.env_file,
            )
        mock_prompt.assert_called_once()
        self.assertFalse(result)
        # answering overwrites the malformed line with a valid value
        content = self.env_file.read_text()
        self.assertIn('AI_STATUSLINE=false', content)
        self.assertNotIn('AI_STATUSLINE=maybe', content)

    def test_direct_mode_does_not_prompt_or_persist(self):
        with patch('devscripts.services.generate_workspace.generate_workspace._prompt_ai_statusline') as mock_prompt:
            result = resolve_ai_statusline(
                env={},
                cli_flag_disabled=False,
                interactive=False,
                env_file=self.env_file,
            )
        mock_prompt.assert_not_called()
        self.assertTrue(result, 'direct mode default stays enabled')
        self.assertNotIn('AI_STATUSLINE', self.env_file.read_text())

    def test_direct_mode_with_flag_disables_without_persisting(self):
        with patch('devscripts.services.generate_workspace.generate_workspace._prompt_ai_statusline') as mock_prompt:
            result = resolve_ai_statusline(
                env={},
                cli_flag_disabled=True,
                interactive=False,
                env_file=self.env_file,
            )
        mock_prompt.assert_not_called()
        self.assertFalse(result)
        self.assertNotIn('AI_STATUSLINE', self.env_file.read_text())

    def test_eof_during_prompt_does_not_persist(self):
        # _prompt_ai_statusline already returns True on EOF/KeyboardInterrupt
        # (existing behavior) — resolve_ai_statusline must not persist that
        # fallback since it wasn't a genuine user choice. We simulate this by
        # having the prompt raise internally to True and asserting no write.
        with patch('devscripts.services.generate_workspace.generate_workspace._prompt_ai_statusline', return_value=True) as mock_prompt, \
             patch('devscripts.services.generate_workspace.generate_workspace._ai_statusline_prompt_was_eof', return_value=True):
            result = resolve_ai_statusline(
                env={},
                cli_flag_disabled=False,
                interactive=True,
                env_file=self.env_file,
            )
        mock_prompt.assert_called_once()
        self.assertTrue(result)
        self.assertNotIn('AI_STATUSLINE', self.env_file.read_text())


if __name__ == '__main__':
    unittest.main()
