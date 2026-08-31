import os
os.environ["ANKI_TESTING"] = "1"
import tempfile
import storage_paths
import data_manager


# Create a temporary directory for all test data to isolate test runs
_TEST_TEMP_DIR = tempfile.TemporaryDirectory()

# Override get_mission_archive_root to always return "" during tests
storage_paths.get_mission_archive_root = lambda: ""

# Override _home_file in storage_paths to point to our temp directory
storage_paths._home_file = lambda name: os.path.join(_TEST_TEMP_DIR.name, name)

# Override DATA_FILE in data_manager
data_manager.DATA_FILE = os.path.join(_TEST_TEMP_DIR.name, "anki_occlusion_data_test.db")
