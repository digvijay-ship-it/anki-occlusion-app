import os
import time

def init_review_profile(self, cards):
    raw = os.environ.get("ANKI_REVIEW_PROFILE", "").strip().lower()
    pdf_filter = os.environ.get("ANKI_REVIEW_PROFILE_PDF", "").strip().lower()
    enabled = raw in {"1", "true", "yes", "on"}
    if enabled and pdf_filter:
        enabled = any(
            pdf_filter
            in " ".join(
                (
                    str((card or {}).get("title", "")),
                    os.path.basename(str((card or {}).get("pdf_path", ""))),
                    str((card or {}).get("pdf_path", "")),
                )
            ).lower()
            for card in cards or []
        )
    self._review_profile_enabled = enabled
    self._review_profile_filter = pdf_filter
    self._review_profile_t0 = time.perf_counter()
    self._review_profile_last = self._review_profile_t0
    self._review_profile_counts = {}
    if enabled:
        self._review_profile_log(
            "session_start",
            cards=len(cards or []),
            filter=pdf_filter or "all",
        )

def review_profile_active(self):
    return bool(self.__dict__.get("_review_profile_enabled", False))

def review_profile_rss_mb(self):
    try:
        if os.name == "nt":
            import ctypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            if ok:
                return counters.WorkingSetSize / (1024 * 1024)
        else:
            import resource

            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return rss / 1024 if rss > 1024 * 1024 else rss / (1024 * 1024)
    except Exception:
        return None
    return None

def review_profile_log(self, event, **fields):
    if not self._review_profile_active():
        return
    now = time.perf_counter()
    last = float(self.__dict__.get("_review_profile_last", now) or now)
    start = float(self.__dict__.get("_review_profile_t0", now) or now)
    self._review_profile_last = now
    parts = [
        f"+{(now - last) * 1000:.1f}ms",
        f"total={(now - start) * 1000:.1f}ms",
    ]
    rss_mb = self._review_profile_rss_mb()
    if rss_mb is not None:
        peak = max(float(self.__dict__.get("_review_profile_peak_rss_mb", 0.0)), rss_mb)
        self._review_profile_peak_rss_mb = peak
        parts.append(f"rss={rss_mb:.1f}MB")
        parts.append(f"peak_rss={peak:.1f}MB")
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    print(f"[PROFILE][review] {event} " + " ".join(parts))

def review_profile_count(self, name, amount=1):
    counts = self.__dict__.setdefault("_review_profile_counts", {})
    counts[name] = int(counts.get(name, 0)) + int(amount)
    return counts[name]

def log_review_scroll_profile(
    self,
    *,
    value,
    page_zero,
    page_changed,
    page_calc_ms,
    page_ui_ms,
    overlay_ms,
    total_ms,
):
    if not self._review_scroll_profile_enabled():
        return
    now = time.perf_counter()
    prev_ts = self.__dict__.get("_review_scroll_profile_last_event_ts")
    dt_ms = 0.0 if prev_ts is None else (now - float(prev_ts)) * 1000.0
    self._review_scroll_profile_last_event_ts = now
    last_log = float(self.__dict__.get("_review_scroll_profile_last_log_ts", 0.0) or 0.0)
    should_log = page_changed or total_ms >= 8.0 or (now - last_log) >= 1.0
    if not should_log:
        return
    self._review_scroll_profile_last_log_ts = now
    rate = 1000.0 / dt_ms if dt_ms > 0 else 0.0
    print(
        "[PROFILE][review_scroll] "
        f"value={int(value)} "
        f"page=p.{int(page_zero) + 1} "
        f"changed={'yes' if page_changed else 'no'} "
        f"dt={dt_ms:.1f}ms "
        f"rate={rate:.1f}/s "
        f"total={total_ms:.1f}ms "
        f"page_calc={page_calc_ms:.1f}ms "
        f"page_ui={page_ui_ms:.1f}ms "
        f"overlay={overlay_ms:.1f}ms"
    )
