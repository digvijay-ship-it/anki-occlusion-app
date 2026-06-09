import builtins
import os


_ORIGINAL_PRINT = builtins.print
_DEBUG_PREFIXES = ("[DEBUG]", "[PROFILE]")
_ENABLE_ENV = "ANKI_ALLOW_DEBUG_LOGS"


def _debug_logs_enabled():
    raw = os.environ.get(_ENABLE_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _is_debug_message(args):
    if not args:
        return False
    first = str(args[0])
    return first.startswith(_DEBUG_PREFIXES)


def install_debug_output_filter():
    if _debug_logs_enabled():
        return
    if getattr(builtins.print, "_anki_debug_filter", False):
        return

    def filtered_print(*args, **kwargs):
        if _debug_logs_enabled():
            return _ORIGINAL_PRINT(*args, **kwargs)
        if _is_debug_message(args):
            return
        return _ORIGINAL_PRINT(*args, **kwargs)

    filtered_print._anki_debug_filter = True
    builtins.print = filtered_print
