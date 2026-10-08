"""Double-click launcher (Python 3.11+). State lives beside this file."""
from pathlib import Path
from hitl_se.gui import launch

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    launch(root / '.hitl', root / '.hitl-demo')
