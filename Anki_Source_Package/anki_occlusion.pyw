import os
import sys

# Ensure the script directory is in the path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# Import and launch the main application
import anki_occlusion_v19
