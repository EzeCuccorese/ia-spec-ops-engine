"""
Tests para el entry point unificado `ws` y subcomandos de Workspace Engine.
"""

from unittest.mock import patch

from workspace_engine.cli.main import doctor_check, main


def test_doctor_check():
    # Verifica que doctor_check se ejecuta sin excepciones
    doctor_check()


@patch("sys.argv", ["ws", "doctor"])
def test_ws_main_doctor():
    with patch("workspace_engine.cli.main.doctor_check") as mock_doc:
        main()
        mock_doc.assert_called_once()


@patch("sys.argv", ["ws", "clean", "/tmp/nonexistent"])
def test_ws_main_clean():
    with patch("workspace_engine.cli.clean_workspace.main") as mock_clean:
        main()
        mock_clean.assert_called_once()
