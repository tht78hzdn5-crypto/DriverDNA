"""Enable `python -m driverdna` — identical to the `driverdna` console
script, but PATH-independent. Useful when the install's Scripts/bin directory
isn't on PATH (common on Windows), so the tool is always runnable via the
interpreter that installed it.
"""

from driverdna.cli import app

if __name__ == "__main__":
    app()
