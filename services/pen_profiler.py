"""
Pen Lag Diagnostics & Deep Telemetry Profiler
Provides deep, granular monitoring of pen/stylus drawing in Anki Occlusion.
Analyzes exact root causes of lag:
  1. OS/Driver Event Dispatch Delay (Wintab / Windows Ink / polling rate jitter)
  2. Main Thread / GIL Blockers (active background threads stealing execution time)
  3. Qt paintEvent Render Bottleneck (large dirty rects, full redrawing, CPU raster)
  4. Curve Smoothing Algorithmic Overhead (re-evaluating paths on every move)
  5. Micro-jitter Filter False-Drops (skipping slow handwriting or small accents)
  6. Tablet / Mouse Event Clashes (synthesized mouse event competition)

Data stays strictly in memory during drawing and flushes to logs/pen_lag_report.log
only when transitioning to a new card, keeping RAM 100% clean and free.
"""

import os
import time
import math
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List


class PenTelemetryProfiler:
    _instance = None

    @classmethod
    def instance(cls) -> "PenTelemetryProfiler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.enabled = True
        self.log_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "logs",
            "pen_lag_report.log"
        )
        # Current active card telemetry
        self.current_card_info: Dict[str, Any] = {
            "card_id": "",
            "title": "",
            "card_type": "",
            "start_time": time.perf_counter(),
        }
        self.strokes: List[Dict[str, Any]] = []
        self.current_stroke: Optional[Dict[str, Any]] = None
        
        # Paint telemetry
        self.paint_records: List[Dict[str, Any]] = []
        
        # Stutter & lag diagnostic thresholds
        self.TH_MINOR_LAG_MS = 25.0     # < 40 FPS
        self.TH_MODERATE_LAG_MS = 45.0  # < 22 FPS
        self.TH_SEVERE_LAG_MS = 80.0    # Noticeable hitch / freeze
        self.TH_SKIP_DIST_PX = 35.0     # Large jump indicating missing intermediate points
        self.TH_PAINT_OVERRUN_MS = 16.67 # Frame budget for 60 FPS

    def start_card(self, card_id: str = "", title: str = "", card_type: str = ""):
        """Initialize telemetry buffer for a new card."""
        self.reset_memory()
        self.current_card_info = {
            "card_id": str(card_id),
            "title": str(title),
            "card_type": str(card_type),
            "start_time": time.perf_counter(),
        }

    def reset_memory(self):
        """100% clean dump of in-memory telemetry buffer."""
        self.strokes.clear()
        self.current_stroke = None
        self.paint_records.clear()

    def record_press(
        self,
        x: float,
        y: float,
        pressure: float = 1.0,
        input_kind: str = "tablet",
        canvas_name: str = "canvas",
        device_type: str = "stylus"
    ):
        """Called on TabletPress or MousePress."""
        if not self.enabled:
            return
        now = time.perf_counter()
        stroke_idx = len(self.strokes) + 1
        
        # Sample active background threads to check for thread contention
        active_threads = [t.name for t in threading.enumerate() if t is not threading.main_thread()]

        self.current_stroke = {
            "stroke_idx": stroke_idx,
            "canvas_name": canvas_name,
            "input_kind": input_kind,
            "device_type": device_type,
            "start_time": now,
            "last_time": now,
            "last_x": x,
            "last_y": y,
            "last_pressure": pressure,
            "total_events": 1,
            "accepted_points": 1,
            "filtered_points": 0,
            "stutters": [],
            "intervals_ms": [],
            "distances_px": [],
            "path_calc_durations_ms": [],
            "min_x": x,
            "max_x": x,
            "min_y": y,
            "max_y": y,
            "active_bg_threads": active_threads,
        }

    def record_move(
        self,
        x: float,
        y: float,
        pressure: float = 1.0,
        accepted: bool = True,
        path_calc_ms: float = 0.0
    ):
        """
        Called on TabletMove or MouseMove.
        Tracks time delta, distance, micro-jitter filter drops, and path building time.
        """
        if not self.enabled or self.current_stroke is None:
            return
        
        now = time.perf_counter()
        s = self.current_stroke
        s["total_events"] += 1
        
        dt_ms = (now - s["last_time"]) * 1000.0
        dx = x - s["last_x"]
        dy = y - s["last_y"]
        dist_px = math.sqrt(dx * dx + dy * dy)

        if path_calc_ms > 0:
            s["path_calc_durations_ms"].append(path_calc_ms)

        if not accepted:
            s["filtered_points"] += 1
            s["last_time"] = now
            s["last_x"] = x
            s["last_y"] = y
            s["last_pressure"] = pressure
            return

        s["accepted_points"] += 1
        s["intervals_ms"].append(dt_ms)
        s["distances_px"].append(dist_px)

        # Update bounding box
        if x < s["min_x"]: s["min_x"] = x
        if x > s["max_x"]: s["max_x"] = x
        if y < s["min_y"]: s["min_y"] = y
        if y > s["max_y"]: s["max_y"] = y

        # Detect lag spikes and skipped coordinate jumps
        is_lag = dt_ms >= self.TH_MINOR_LAG_MS
        is_jump = dist_px >= self.TH_SKIP_DIST_PX and dt_ms >= self.TH_MINOR_LAG_MS

        if is_lag or is_jump:
            severity = "MINOR_LAG"
            probable_reason = "Input event queue delay"
            if dt_ms >= self.TH_SEVERE_LAG_MS:
                severity = "SEVERE_FREEZE"
                probable_reason = "Main thread/GIL blockage or heavy paint lock"
            elif dt_ms >= self.TH_MODERATE_LAG_MS:
                severity = "MODERATE_LAG"
                probable_reason = "Dropped display frame (frame rate < 25 FPS)"
            elif is_jump:
                severity = "SKIPPED_POINTS"
                probable_reason = "Fast stroke move with missed OS/driver samples"

            s["stutters"].append({
                "severity": severity,
                "probable_reason": probable_reason,
                "dt_ms": round(dt_ms, 2),
                "dist_px": round(dist_px, 2),
                "speed_px_s": round((dist_px / (dt_ms / 1000.0)), 1) if dt_ms > 0 else 0,
                "from_coord": (round(s["last_x"], 1), round(s["last_y"], 1)),
                "to_coord": (round(x, 1), round(y, 1)),
                "pressure": round(pressure, 2),
                "time_offset_ms": round((now - s["start_time"]) * 1000.0, 1),
                "path_calc_ms": round(path_calc_ms, 2),
            })

        s["last_time"] = now
        s["last_x"] = x
        s["last_y"] = y
        s["last_pressure"] = pressure

    def record_release(self, x: float, y: float):
        """Called on TabletRelease or MouseRelease."""
        if not self.enabled or self.current_stroke is None:
            return
        now = time.perf_counter()
        s = self.current_stroke
        s["end_time"] = now
        s["duration_ms"] = round((now - s["start_time"]) * 1000.0, 2)
        self.strokes.append(s)
        self.current_stroke = None

    def record_paint(self, duration_ms: float, rect_w: int = 0, rect_h: int = 0, stroke_count: int = 0):
        """Record paintEvent execution duration, dirty rect size, and stroke count."""
        if not self.enabled:
            return
        self.paint_records.append({
            "timestamp": time.perf_counter(),
            "duration_ms": duration_ms,
            "rect_w": rect_w,
            "rect_h": rect_h,
            "stroke_count": stroke_count,
        })

    def flush_card_report(self, card_id: str = "", title: str = "", card_type: str = "") -> bool:
        """
        Appends deep diagnostic report to log file IF any drawing occurred.
        Then dumps memory completely.
        """
        if self.current_stroke is not None:
            self.strokes.append(self.current_stroke)
            self.current_stroke = None

        if not self.strokes:
            self.reset_memory()
            return False

        try:
            os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)
            report_text = self._build_deep_report_text(card_id, title, card_type)
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(report_text + "\n")
        except Exception as ex:
            print(f"[PenProfiler] Error writing deep report: {ex}")
        finally:
            self.reset_memory()
        
        return True

    def _build_deep_report_text(self, card_id: str, title: str, card_type: str) -> str:
        cid = card_id or self.current_card_info.get("card_id", "unknown")
        ctitle = title or self.current_card_info.get("title", "Untitled")
        ctype = card_type or self.current_card_info.get("card_type", "unknown")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        total_strokes = len(self.strokes)
        total_events = sum(s.get("total_events", 0) for s in self.strokes)
        total_accepted = sum(s.get("accepted_points", 0) for s in self.strokes)
        total_filtered = sum(s.get("filtered_points", 0) for s in self.strokes)
        
        all_intervals = [dt for s in self.strokes for dt in s.get("intervals_ms", [])]
        avg_dt = (sum(all_intervals) / len(all_intervals)) if all_intervals else 0.0
        max_dt = max(all_intervals) if all_intervals else 0.0
        min_dt = min(all_intervals) if all_intervals else 0.0
        est_polling_hz = round(1000.0 / avg_dt, 1) if avg_dt > 0 else 0.0

        all_stutters = [st for s in self.strokes for st in s.get("stutters", [])]
        minor_lags = [st for st in all_stutters if st["severity"] == "MINOR_LAG"]
        mod_lags = [st for st in all_stutters if st["severity"] == "MODERATE_LAG"]
        severe_lags = [st for st in all_stutters if st["severity"] == "SEVERE_FREEZE"]
        skipped_pts = [st for st in all_stutters if st["severity"] == "SKIPPED_POINTS"]

        # Paint statistics
        paint_durations = [p["duration_ms"] for p in self.paint_records]
        avg_paint = (sum(paint_durations) / len(paint_durations)) if paint_durations else 0.0
        max_paint = max(paint_durations) if paint_durations else 0.0
        overrun_paints = [d for d in paint_durations if d >= self.TH_PAINT_OVERRUN_MS]

        # Path calc statistics
        all_path_calcs = [c for s in self.strokes for c in s.get("path_calc_durations_ms", [])]
        avg_path_calc = (sum(all_path_calcs) / len(all_path_calcs)) if all_path_calcs else 0.0
        max_path_calc = max(all_path_calcs) if all_path_calcs else 0.0

        # Background threads observed
        bg_threads_seen = set(t for s in self.strokes for t in s.get("active_bg_threads", []))

        # Root Cause Analysis
        reasons = []
        if max_paint >= self.TH_PAINT_OVERRUN_MS:
            reasons.append(
                f"🛑 [PAINT EVENT BOTTLENECK] Max paint duration was {max_paint:.2f}ms "
                f"(budget: 16.67ms). {len(overrun_paints)} paint calls exceeded 60 FPS frame limit. "
                "The screen/GPU could not rasterize the dirty rect fast enough."
            )
        
        if severe_lags or len(mod_lags) >= 3:
            if avg_paint < 10.0 and max_paint < 16.67:
                reasons.append(
                    f"🛑 [OS / EVENT LOOP INPUT STALL] Qt paintEvent was fast (avg {avg_paint:.1f}ms), "
                    f"but event intervals stalled up to {max_dt:.1f}ms! "
                    "This indicates Windows Ink / Wintab driver delivery delay or Python GIL contention."
                )

        if max_path_calc >= 2.5:
            reasons.append(
                f"⚠️ [SMOOTHING OVERHEAD] Path curve generation took up to {max_path_calc:.2f}ms per event. "
                "Recalculating curves over long strokes contributes to input stutter."
            )

        if total_filtered > 0 and (total_filtered / total_events) >= 0.40:
            reasons.append(
                f"ℹ️ [HIGH JITTER FILTERING] {total_filtered}/{total_events} points ({total_filtered/total_events*100:.1f}%) "
                "were dropped by distance threshold (<1.5px or <2.0px). Can cause perceived lag during fine writing."
            )

        if not reasons:
            reasons.append("✅ [SMOOTH DRAWING] Input delivery and rendering both stayed within 60+ FPS limits.")

        lines = [
            "================================================================================",
            f"🖊️ DEEP PEN LAG & DRAWING DIAGNOSTIC REPORT — {now_str}",
            f"📌 Card: [{cid}] \"{ctitle}\" | Type: {ctype}",
            "--------------------------------------------------------------------------------",
            "📊 1. INPUT STREAM METRICS (Stylus & OS Polling):",
            f"   • Total Strokes Drawn        : {total_strokes}",
            f"   • Total Raw Input Events     : {total_events}",
            f"   • Points Accepted (Rendered) : {total_accepted} ({(total_accepted/total_events*100):.1f}%)",
            f"   • Points Filtered (Jitter)   : {total_filtered} ({(total_filtered/total_events*100):.1f}%)",
            f"   • Stylus Sampling Frequency  : ~{est_polling_hz} Hz (Target: 60Hz-133Hz)",
            f"   • Event Interval (Δt)        : Avg = {avg_dt:.2f}ms | Min = {min_dt:.2f}ms | Max = {max_dt:.2f}ms",
            "--------------------------------------------------------------------------------",
            "🎨 2. RENDER & PAINT METRICS (Qt paintEvent):",
            f"   • Total paintEvent Calls     : {len(self.paint_records)}",
            f"   • Avg Paint Duration         : {avg_paint:.2f}ms",
            f"   • Max Paint Duration         : {max_paint:.2f}ms",
            f"   • Frame Drops (>16.67ms)     : {len(overrun_paints)} calls ({len(overrun_paints)/(len(self.paint_records) or 1)*100:.1f}%)",
            f"   • Path Smoothing Duration    : Avg = {avg_path_calc:.2f}ms | Max = {max_path_calc:.2f}ms",
            "--------------------------------------------------------------------------------",
            f"🧵 3. SYSTEM & BACKGROUND THREAD STATE:",
            f"   • Background Threads Alive   : {', '.join(bg_threads_seen) if bg_threads_seen else 'None (Clean main thread)'}",
            "--------------------------------------------------------------------------------",
            "🔍 4. ROOT CAUSE DIAGNOSIS (Kyu Lag Hua?):",
        ]
        for r in reasons:
            lines.append(f"   {r}")

        if all_stutters:
            lines.append("--------------------------------------------------------------------------------")
            lines.append(f"⚠️ 5. DETAILED LAG & SKIPPED COORDINATE BREAKDOWN (Top {min(25, len(all_stutters))} of {len(all_stutters)}):")
            for idx, st in enumerate(all_stutters[:25], 1):
                lines.append(
                    f"   [{idx:02d}] {st['severity']} | Δt={st['dt_ms']}ms | Δd={st['dist_px']}px ({st['speed_px_s']} px/s) | "
                    f"From {st['from_coord']} -> To {st['to_coord']} | P={st['pressure']} | T+{st['time_offset_ms']}ms\n"
                    f"        ↳ Reason: {st['probable_reason']} (PathCalc: {st['path_calc_ms']}ms)"
                )

        lines.append("================================================================================\n")
        return "\n".join(lines)


# Global helper instance
pen_profiler = PenTelemetryProfiler.instance()
