import sys
from pathlib import Path

# app.py lives next to tests/, not in an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
