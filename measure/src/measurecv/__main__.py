"""Entry point for ``python -m measurecv``.

The ``measurecv`` console script is installed into Python's ``Scripts``
directory, which is frequently not on ``PATH`` -- a per-user pip install on
Windows is the common case. ``python -m measurecv`` needs no PATH entry at all
because it resolves through the interpreter that installed the package, so it
works identically in a venv, a container, and a bare user install.
"""

from measurecv.cli import app

if __name__ == "__main__":
    app()
