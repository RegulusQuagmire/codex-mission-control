"""Double-click launcher when .pyw is associated with the project Python."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from mission_control.desktop.app import main
raise SystemExit(main())
