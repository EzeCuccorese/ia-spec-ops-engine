import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_GW_DIR = Path(__file__).resolve().parents[3] / "devscripts" / "services" / "generate_workspace"
sys.path.insert(0, str(_GW_DIR))
from devscripts.services.generate_workspace.generate_workspace import set_env_value

GENERATE_WORKSPACE_DIR = str(_GW_DIR)



class TestSetEnvValue(unittest.TestCase):
    """set_env_value mirrors scripts/init-env.sh's bash set_env_value: in-place
    update by line match, else append; never reorders/drops other lines."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.env', delete=False)
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp_path.unlink(missing_ok=True)

    def _write(self, content: str) -> None:
        self.tmp_path.write_text(content)

    def _read(self) -> str:
        return self.tmp_path.read_text()

    def test_updates_existing_key_in_place(self):
        self._write('FOO=bar\nAI_STATUSLINE=false\nBAZ=qux\n')
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertIn('AI_STATUSLINE=true\n', result)
        self.assertNotIn('AI_STATUSLINE=false', result)

    def test_updating_existing_key_leaves_other_lines_byte_identical(self):
        original = '# a comment\nFOO=bar\nAI_STATUSLINE=false\nBAZ=qux\n'
        self._write(original)
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertIn('# a comment\n', result)
        self.assertIn('FOO=bar\n', result)
        self.assertIn('BAZ=qux\n', result)

    def test_appends_missing_key(self):
        self._write('FOO=bar\n')
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertIn('FOO=bar\n', result)
        self.assertIn('AI_STATUSLINE=true\n', result)

    def test_appends_missing_key_with_single_trailing_newline(self):
        self._write('FOO=bar\n')
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertTrue(result.endswith('AI_STATUSLINE=true\n'))
        self.assertFalse(result.endswith('\n\n'))

    def test_appends_when_file_missing_trailing_newline(self):
        self._write('FOO=bar')  # no trailing newline
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertIn('FOO=bar\n', result)
        self.assertIn('AI_STATUSLINE=true\n', result)

    def test_idempotent_write_no_duplicate_lines(self):
        self._write('FOO=bar\n')
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertEqual(result.count('AI_STATUSLINE='), 1)

    def test_preserves_comments_and_blank_lines(self):
        original = (
            '# header comment\n'
            '\n'
            'FOO=bar\n'
            '\n'
            '# another comment\n'
            'AI_STATUSLINE=false\n'
        )
        self._write(original)
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertIn('# header comment\n', result)
        self.assertIn('# another comment\n', result)
        # blank lines preserved (structure intact, only the value line changes)
        lines = result.splitlines()
        self.assertIn('', lines)

    def test_does_not_clobber_other_keys(self):
        self._write('AAA=1\nAI_STATUSLINE=false\nZZZ=2\n')
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        self.assertIn('AAA=1\n', result)
        self.assertIn('ZZZ=2\n', result)

    def test_does_not_create_file_when_missing(self):
        """Docstring contract: set_env_value does not touch the file at all if
        it doesn't exist — callers are expected to guard existence."""
        self.tmp_path.unlink()  # remove the file setUp created
        self.assertFalse(self.tmp_path.exists())
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        self.assertFalse(self.tmp_path.exists())

    def test_updates_all_duplicate_key_lines(self):
        """Mirrors sed -i's global per-file substitution (init-env.sh's bash
        set_env_value): if the key appears more than once, EVERY matching line
        must be updated, else load_env (last-occurrence-wins) returns a stale
        value even though set_env_value reported success."""
        self._write('AI_STATUSLINE=false\nFOO=bar\nAI_STATUSLINE=false\n')
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        lines = [l for l in result.splitlines() if l.startswith('AI_STATUSLINE=')]
        self.assertEqual(lines, ['AI_STATUSLINE=true', 'AI_STATUSLINE=true'])

    def test_duplicate_key_load_env_returns_new_value(self):
        from generate_workspace import load_env
        self._write('AI_STATUSLINE=false\nFOO=bar\nAI_STATUSLINE=false\n')
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        env = load_env(self.tmp_path)
        self.assertEqual(env['AI_STATUSLINE'], 'true')

    def test_update_preserves_line_order(self):
        original = 'AAA=1\nBBB=2\nAI_STATUSLINE=false\nCCC=3\n'
        self._write(original)
        set_env_value('AI_STATUSLINE', 'true', self.tmp_path)
        result = self._read()
        order = [l.split('=')[0] for l in result.splitlines() if '=' in l]
        self.assertEqual(order, ['AAA', 'BBB', 'AI_STATUSLINE', 'CCC'])

    def test_round_trips_non_ascii_value(self):
        """A value containing an accented character must round-trip correctly
        through set_env_value + load_env, independent of platform encoding."""
        from generate_workspace import load_env
        self._write('FOO=bar\n')
        set_env_value('GREETING', 'café', self.tmp_path)
        result = self._read()
        self.assertIn('GREETING=café\n', result)
        env = load_env(self.tmp_path)
        self.assertEqual(env['GREETING'], 'café')


class TestNonUtf8LocaleEncoding(unittest.TestCase):
    """set_env_value/load_env must use an explicit UTF-8 encoding, not the
    platform's locale-preferred encoding (Path.read_text()/write_text()'s
    default). Under a non-UTF-8 locale (e.g. a minimal container, or a
    US-ASCII/POSIX locale — a real-world case, not contrived), the platform
    default would raise UnicodeDecodeError/UnicodeEncodeError on non-ASCII
    content (accents, emoji) in config/.env. Reproduced by running the actual
    round-trip in a SEPARATE subprocess under LC_ALL=en_US.US-ASCII: Python
    resolves Path.read_text()'s default encoding once at interpreter startup
    from the process locale, so this cannot be forced by mutating locale
    state in-process — it requires a fresh interpreter with that locale set
    before Python starts.
    """

    NON_UTF8_LOCALE = 'en_US.US-ASCII'

    def setUp(self):
        import locale
        try:
            locale.setlocale(locale.LC_ALL, self.NON_UTF8_LOCALE)
            locale.setlocale(locale.LC_ALL, '')  # restore, just probing availability
        except locale.Error:
            self.skipTest(f'{self.NON_UTF8_LOCALE} locale not installed on this system')

    def _run_round_trip_under_locale(self) -> subprocess.CompletedProcess:
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from generate_workspace import set_env_value, load_env\n"
            "p = Path(sys.argv[1])\n"
            "p.write_text('FOO=bar\\n')\n"
            "set_env_value('GREETING', 'café', p)\n"
            "env = load_env(p)\n"
            "assert env['GREETING'] == 'café', env\n"
            "print('ROUND_TRIP_OK')\n"
        ) % GENERATE_WORKSPACE_DIR
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            tmp_path = f.name
        try:
            env = dict(os.environ)
            env['LC_ALL'] = self.NON_UTF8_LOCALE
            env.pop('PYTHONUTF8', None)
            env.pop('PYTHONIOENCODING', None)
            return subprocess.run(
                [sys.executable, '-c', script, tmp_path],
                env=env, capture_output=True, text=True,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_round_trip_survives_non_utf8_locale(self):
        result = self._run_round_trip_under_locale()
        self.assertEqual(
            result.returncode, 0,
            f'round-trip failed under LC_ALL={self.NON_UTF8_LOCALE}:\n'
            f'stdout={result.stdout!r}\nstderr={result.stderr!r}',
        )
        self.assertIn('ROUND_TRIP_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
