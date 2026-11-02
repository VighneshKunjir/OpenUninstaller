import sys

GUI_FLAGS = ("--forced", "--trace", "--no-elevate")

if len(sys.argv) > 1 and sys.argv[1] not in GUI_FLAGS:
    from .cli import main
else:
    from .gui.app import main

main()
