"""Double-click launcher (runs the GUI without a console window)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openuninstaller.gui.app import main  # noqa: E402

main()
