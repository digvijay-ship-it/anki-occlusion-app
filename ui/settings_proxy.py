TRACKED_KEYS = [
    "_font_size", "_theme", "_keep_fullscreen", 
    "_volume", "_onboarding_done", "_invert_pdf", 
    "_home_animations", "_auto_reveal", "_scroll_speed"
]

class SettingsProxyDict(dict):
    """
    A dictionary wrapper that transparently routes global preference keys
    to PyQt QSettings. This avoids triggering heavy database saves and
    cloud uploads when changing minor UI preferences.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from PyQt5.QtCore import QSettings
        from storage_paths import is_running_tests
        
        # Determine organization and app names
        org = "AnkiOcclusionTest" if is_running_tests() else "AnkiOcclusion"
        app = "AppTest" if is_running_tests() else "App"
        settings = QSettings(org, app)
        
        for k in TRACKED_KEYS:
            val = settings.value(f"settings/{k}")
            if val is not None:
                # Normalize types because QSettings might save them as strings/variants
                if k in ["_keep_fullscreen", "_onboarding_done", "_invert_pdf", "_home_animations", "_auto_reveal"]:
                    if isinstance(val, str):
                        val = (val.lower() == "true")
                    else:
                        val = bool(val)
                elif k in ["_font_size", "_volume", "_scroll_speed"]:
                    try:
                        val = int(val)
                    except (ValueError, TypeError):
                        pass
                super().__setitem__(k, val)
            elif k in self:
                # Sync from DB to QSettings if not already set (e.g. initial migration)
                settings.setValue(f"settings/{k}", self[k])

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if key in TRACKED_KEYS:
            from PyQt5.QtCore import QSettings
            from storage_paths import is_running_tests
            org = "AnkiOcclusionTest" if is_running_tests() else "AnkiOcclusion"
            app = "AppTest" if is_running_tests() else "App"
            settings = QSettings(org, app)
            settings.setValue(f"settings/{key}", value)

    def __delitem__(self, key):
        super().__delitem__(key)
        if key in TRACKED_KEYS:
            from PyQt5.QtCore import QSettings
            from storage_paths import is_running_tests
            org = "AnkiOcclusionTest" if is_running_tests() else "AnkiOcclusion"
            app = "AppTest" if is_running_tests() else "App"
            settings = QSettings(org, app)
            settings.remove(f"settings/{key}")

    def pop(self, key, *args):
        val = super().pop(key, *args)
        if key in TRACKED_KEYS:
            from PyQt5.QtCore import QSettings
            from storage_paths import is_running_tests
            org = "AnkiOcclusionTest" if is_running_tests() else "AnkiOcclusion"
            app = "AppTest" if is_running_tests() else "App"
            settings = QSettings(org, app)
            settings.remove(f"settings/{key}")
        return val

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        from PyQt5.QtCore import QSettings
        from storage_paths import is_running_tests
        org = "AnkiOcclusionTest" if is_running_tests() else "AnkiOcclusion"
        app = "AppTest" if is_running_tests() else "App"
        settings = QSettings(org, app)
        for k in TRACKED_KEYS:
            if k in self:
                settings.setValue(f"settings/{k}", self[k])
