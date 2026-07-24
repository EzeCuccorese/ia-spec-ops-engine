import io
import tempfile
from pathlib import Path
from devscripts.core.colors import Color, log_info, log_success, log_warning, log_error
from devscripts.core.file_lock import FileLock
import utils

def test_colors_and_logging():
    out_buf = io.StringIO()
    err_buf = io.StringIO()

    log_info("Info message", file=out_buf)
    assert "Info message" in out_buf.getvalue()

    out_buf = io.StringIO()
    log_success("Success message", file=out_buf)
    assert "Success message" in out_buf.getvalue()

    out_buf = io.StringIO()
    log_warning("Warning message", file=out_buf)
    assert "Warning message" in out_buf.getvalue()

    log_error("Error message", file=err_buf)
    assert "Error message" in err_buf.getvalue()


def test_file_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_path = Path(tmpdir) / "sub" / "test.lock"
        with FileLock(lock_path):
            assert lock_path.exists()


def test_utils_backward_compatibility():
    assert utils.Color.RED == Color.RED
    out_buf = io.StringIO()
    utils.log_info("Utils info", file=out_buf)
    assert "Utils info" in out_buf.getvalue()

    res = utils.run_command("echo 'hello'", check=True, capture_output=True, show_command=False)
    assert res == "hello"
