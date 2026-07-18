"""M-setup smoke tests: package imports and CLI entry point."""

from typer.testing import CliRunner

import driverdna
from driverdna.cli import app


def test_package_has_version():
    assert driverdna.__version__


def test_cli_version_command():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert driverdna.__version__ in result.output
