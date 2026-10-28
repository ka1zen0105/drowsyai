"""Unified Web Dashboard & Live Monitor for Driver Drowsiness Detection System.

Runs as a standalone side-application without modifying the main codebase.
Provides:
  - Live video stream with face mesh dots, bounding box & HUD via MJPEG
  - Real-time telemetry API (EAR, MAR, Head Pose, PERCLOS, flags, virtual GPIO)
  - Live events log streaming & CSV download
  - Interactive controls (Acknowledge Alert, 15s Calibration trigger)
  - Beautiful dark-mode web application (HTML/CSS/JS) auto-opened in browser
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import threading
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Any

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Import existing modules directly (without modifying them)
from config import AppConfig, CalibrationValues, load_config, save_calibration
from vision import CameraReader, FaceMeshDetector, FeatureRecord, process_frame, draw_face_landmarks
from fusion import FusionEngine, SharedState, SystemState
from alert import AlertController, create_alert_controller
from logger import CSVLogger, TelemetryRow


# ---------------------------------------------------------------------------
# Global Application Context
# ---------------------------------------------------------------------------

class DashboardManager:
    def __init__(self, cfg_path: Optional[str] = None, simulate: bool = True):
        self.cfg: AppConfig = load_config(cfg_path)
        if simulate:
            self.cfg.gpio.simulation_mode = True

        self.state = SharedState()
        self.alert_ctrl = create_alert_controller(self.cfg.gpio)
        self.camera: Optional[CameraReader] = None
        self.detector: Optional[FaceMeshDetector] = None
        self.fusion: Optional[FusionEngine] = None
        self.csv_logger: Optional[CSVLogger] = None

        self._frame_id = 0
        self._latest_display_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._running = False

        # Calibration state tracking
        self.is_calibrating = False
        self.cal_duration = 15.0
        self.cal_elapsed = 0.0
        self.cal_samples: List[float] = []

        # Recent in-memory events ring-buffer
        self.recent_events: List[Dict[str, Any]] = []
        self._events_lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # 1. Self test & initial state
        self.state.system_state = SystemState.STARTUP
        self.alert_ctrl.self_test()
        self.alert_ctrl.register_ack_callback(self._on_ack)

        # 2. Camera & Detector
        self.camera = CameraReader(
            source=self.cfg.camera.source,
            width=self.cfg.camera.width,
            height=self.cfg.camera.height,
            fps=self.cfg.camera.fps,
        ).start()

        self.detector = FaceMeshDetector(model_path=self.cfg.model_path)
        self.csv_logger = CSVLogger(self.cfg.logging)
        self.fusion = FusionEngine(self.cfg.detection, self.cfg.fusion, self.cfg.cal)

        self.state.system_state = SystemState.MONITORING
        self.alert_ctrl.set_normal()

        # 3. Worker threads
        threading.Thread(target=self._vision_loop, name="DashVision", daemon=True).start()
        threading.Thread(target=self._alert_loop, name="DashAlert", daemon=True).start()
        threading.Thread(target=self._watchdog_loop, name="DashWatchdog", daemon=True).start()

        # Load existing events from CSV if present
        self._load_existing_events()
        print("[Dashboard] Engine running. Monitoring driver …")

    def _on_ack(self) -> None:
        now = time.time()
        self.state.ack_event.set()
        if self.fusion:
            self.fusion.acknowledge(now)
        self.state.alarm_event.clear()
        self._record_event("ACK_BUTTON", "Alarm acknowledged by user.")
        print("[Dashboard] Alert acknowledged.")

    def _record_event(self, event_type: str, desc: str, ear=0.0, mar=0.0, pitch=0.0, perclos=0.0) -> None:
        now_ts = time.time()
        iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now_ts))
        ev = {
            "iso_time": iso,
            "timestamp": now_ts,
            "event_type": event_type,
            "ear": ear,
            "mar": mar,
            "pitch": pitch,
            "perclos": perclos,
            "description": desc,
        }
        with self._events_lock:
            self.recent_events.append(ev)
            if len(self.recent_events) > 200:
                self.recent_events.pop(0)

        if self.csv_logger:
            self.csv_logger.log_event(event_type, desc, ear=ear, mar=mar, pitch=pitch, perclos=perclos)

    def _load_existing_events(self) -> None:
        p = Path(self.cfg.logging.directory) / self.cfg.logging.events_file
        if not p.exists():
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                rows = list(reader)
                for r in rows[-30:]:
                    if len(r) >= 8:
                        self.recent_events.append({
                            "iso_time": r[0],
                            "timestamp": float(r[1]) if r[1] else 0.0,
                            "event_type": r[2],
                            "ear": float(r[3]) if r[3] else 0.0,
                            "mar": float(r[4]) if r[4] else 0.0,
                            "pitch": float(r[5]) if r[5] else 0.0,
                            "perclos": float(r[6]) if r[6] else 0.0,
                            "description": r[7],
                        })
        except Exception:
            pass

    def start_calibration(self) -> None:
        if self.is_calibrating:
            return
        threading.Thread(target=self._run_calibration_thread, name="DashCalibrate", daemon=True).start()

    def _run_calibration_thread(self) -> None:
        self.is_calibrating = True
        self.state.system_state = SystemState.CALIBRATING
        self.cal_samples = []
        start_t = time.time()
        mar_samples, pitch_samples, roll_samples, yaw_samples = [], [], [], []

        print("[Dashboard] Starting 15s calibration …")
        while time.time() - start_t < self.cal_duration and self._running:
            self.cal_elapsed = time.time() - start_t
            time.sleep(0.05)

        # Compute baselines
        if len(self.cal_samples) >= 30:
            ear_base = float(np.mean(self.cal_samples))
            mar_base = float(np.mean(mar_samples)) if mar_samples else 0.18
            pitch_base = float(np.mean(pitch_samples)) if pitch_samples else 0.0
            roll_base = float(np.mean(roll_samples)) if roll_samples else 0.0
            yaw_base = float(np.mean(yaw_samples)) if yaw_samples else 0.0

            new_cal = CalibrationValues(
                ear_open_baseline=round(ear_base, 4),
                ear_closed_threshold=round(ear_base * self.cfg.detection.ear_closed_ratio, 4),
                mar_resting_baseline=round(mar_base, 4),
                mar_yawn_threshold=round(mar_base + self.cfg.detection.mar_threshold_offset, 4),
                pitch_baseline=round(pitch_base, 2),
                roll_baseline=round(roll_base, 2),
                yaw_baseline=round(yaw_base, 2),
            )
            self.cfg.cal = new_cal
            self.fusion.cal = new_cal
            save_calibration(new_cal, self.cfg.calibration_cfg.output_file)
            self._record_event("CALIBRATION", f"Baselines updated: EAR={ear_base:.3f}, Pitch={pitch_base:.1f}°")
            print(f"[Dashboard] Calibration finished: EAR={ear_base:.3f}")

        if self.detector:
            self.detector.lock_subject()

        self.is_calibrating = False
        self.state.system_state = SystemState.MONITORING

    def _vision_loop(self) -> None:
        while self._running:
            ok, frame = self.camera.read()
            if not ok or frame is None:
                time.sleep(0.005)
                continue

            self._frame_id += 1
            self.state.update_frame_time()
            rec = process_frame(self.detector, frame, self._frame_id)

            if rec.face_found:
                self.state.update_face_time()
                if self.is_calibrating:
                    self.cal_samples.append(rec.ear_avg)

            # Update fusion & shared state
            if not self.is_calibrating and not self.state.fault_event.is_set():
                alarm = self.fusion.update(rec)
                if alarm and not self.state.alarm_event.is_set():
                    self.state.alarm_event.set()
                    self.state.system_state = SystemState.ALARM
                    reason = "Drowsiness criteria met"
                    if self.fusion.microsleep:
                        reason = f"MICROSLEEP (eyes closed {self.fusion.eye_closure_duration:.1f}s)"
                    self._record_event("ALARM_ON", reason, rec.ear_avg, rec.mar, rec.pitch_deg, self.fusion.perclos)
                elif not alarm and self.state.alarm_event.is_set():
                    self.state.alarm_event.clear()
                    self.state.system_state = SystemState.MONITORING
                    self._record_event("ALARM_OFF", "Alarm cleared.", rec.ear_avg, rec.mar, rec.pitch_deg, self.fusion.perclos)

            with self.state.lock:
                self.state.ear_avg = rec.ear_avg
                self.state.mar = rec.mar
                self.state.pitch = rec.pitch_deg
                self.state.roll = rec.roll_deg
                self.state.yaw = rec.yaw_deg
                self.state.perclos = self.fusion.perclos
                self.state.eye_flag = self.fusion.eye_flag
                self.state.yawn_flag = self.fusion.yawn_flag
                self.state.head_flag = self.fusion.head_flag
                self.state.microsleep = self.fusion.microsleep
                self.state.eye_closure_duration = self.fusion.eye_closure_duration

            # Draw visual landmarks and lock-on box on display frame
            disp_frame = frame.copy()
            if self.detector and getattr(self.detector, "last_landmarks_px", None) is not None:
                draw_face_landmarks(disp_frame, self.detector.last_landmarks_px)

            if self.detector and getattr(self.detector, "last_bbox", None) is not None:
                bx, by, bw, bh = self.detector.last_bbox
                color = (0, 0, 255) if self.state.alarm_event.is_set() else ((0, 255, 255) if self.is_calibrating else (0, 255, 0))
                cv2.rectangle(disp_frame, (bx, by), (bx + bw, by + bh), color, 2)
                tag = "[CALIBRATING]" if self.is_calibrating else ("[ALARM: DRIVER]" if self.state.alarm_event.is_set() else "[LOCKED: DRIVER]")
                cv2.putText(disp_frame, tag, (bx, max(18, by - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2)

            with self._frame_lock:
                self._latest_display_frame = disp_frame

    def _alert_loop(self) -> None:
        while self._running:
            if self.state.alarm_event.is_set():
                self.alert_ctrl.set_alarm()
            elif self.state.fault_event.is_set():
                self.alert_ctrl.set_fault()
            else:
                self.alert_ctrl.set_normal()
            time.sleep(0.08)

    def _watchdog_loop(self) -> None:
        was_fault = False
        while self._running:
            now = time.time()
            frame_stale = (now - self.state.last_frame_time) > self.cfg.watchdog.frame_timeout_sec
            face_stale = (now - self.state.last_face_time) > self.cfg.watchdog.face_timeout_sec

            if (frame_stale or face_stale) and not self.is_calibrating:
                if not self.state.fault_event.is_set():
                    self.state.fault_event.set()
                    self.state.system_state = SystemState.FAULT
                    reason = "no face detected" if face_stale else "camera frame timeout"
                    if not was_fault:
                        self._record_event("FAULT_ON", f"Watchdog: {reason}")
                        was_fault = True
            else:
                if self.state.fault_event.is_set():
                    self.state.fault_event.clear()
                    if not self.state.alarm_event.is_set():
                        self.state.system_state = SystemState.MONITORING
                    if was_fault:
                        self._record_event("FAULT_OFF", "Watchdog: face recovered.")
                        was_fault = False
            time.sleep(0.2)

    def get_latest_frame_bytes(self) -> Optional[bytes]:
        with self._frame_lock:
            if self._latest_display_frame is None:
                return None
            frame = self._latest_display_frame

        ok, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        return jpeg.tobytes() if ok else None

    def get_telemetry_dict(self) -> Dict[str, Any]:
        with self.state.lock:
            ear = self.state.ear_avg
            mar = self.state.mar
            pitch = self.state.pitch
            roll = self.state.roll
            yaw = self.state.yaw
            perclos = self.state.perclos
            eye_f = self.state.eye_flag
            yawn_f = self.state.yawn_flag
            head_f = self.state.head_flag
            ms = self.state.microsleep
            ss = self.state.system_state.value

        face_found = (time.time() - self.state.last_face_time) < 0.5
        avg_cal_ear = float(np.mean(self.cal_samples)) if self.cal_samples else ear

        return {
            "system_state": ss,
            "alarm_active": self.state.alarm_event.is_set(),
            "fault_active": self.state.fault_event.is_set(),
            "face_found": face_found,
            "ear_avg": round(ear, 4),
            "ear_baseline": round(getattr(self.cfg.cal, "ear_open_baseline", 0.28), 4),
            "mar": round(mar, 4),
            "mar_baseline": round(getattr(self.cfg.cal, "mar_resting_baseline", 0.03), 4),
            "mar_yawn_threshold": round(getattr(self.cfg.cal, "mar_yawn_threshold", 0.33), 4),
            "pitch_deg": round(pitch, 1),
            "pitch_baseline": round(getattr(self.cfg.cal, "pitch_baseline", 0.0), 1),
            "roll_deg": round(roll, 1),
            "roll_baseline": round(getattr(self.cfg.cal, "roll_baseline", 0.0), 1),
            "yaw_deg": round(yaw, 1),
            "yaw_baseline": round(getattr(self.cfg.cal, "yaw_baseline", 0.0), 1),
            "perclos": round(perclos, 4),
            "eye_flag": eye_f,
            "yawn_flag": yawn_f,
            "head_flag": head_f,
            "microsleep": ms,
            "green_on": self.alert_ctrl.green_on,
            "red_on": self.alert_ctrl.red_on,
            "buzzer_on": self.alert_ctrl.buzzer_on,
            "calibrating": self.is_calibrating,
            "cal_duration": self.cal_duration,
            "cal_elapsed": round(self.cal_elapsed, 1),
            "cal_samples": len(self.cal_samples),
            "cal_avg_ear": round(avg_cal_ear, 4),
        }


# ---------------------------------------------------------------------------
# FastAPI Web App Setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Driver Drowsiness Detection Dashboard")
mgr: Optional[DashboardManager] = None

# Mount static folder
static_dir = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
def index_page():
    index_file = static_dir / "index.html"
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


def mjpeg_generator():
    while True:
        if mgr is not None:
            jpeg = mgr.get_latest_frame_bytes()
            if jpeg is not None:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        time.sleep(0.033)  # ~30 fps cap


@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/api/telemetry")
def get_telemetry():
    if mgr is None:
        return {}
    return mgr.get_telemetry_dict()


@app.get("/api/events")
def get_events():
    if mgr is None:
        return []
    with mgr._events_lock:
        return list(mgr.recent_events)


@app.get("/api/logs/events.csv")
def download_events_csv():
    if mgr is None:
        return Response(status_code=404)
    p = Path(mgr.cfg.logging.directory) / mgr.cfg.logging.events_file
    if p.exists():
        return FileResponse(path=str(p), filename="events.csv", media_type="text/csv")
    return Response(content="timestamp,epoch,event_type,ear,mar,pitch,perclos,description\n", media_type="text/csv")


@app.post("/api/ack")
def acknowledge_alert():
    if mgr is not None:
        mgr.alert_ctrl.simulate_ack()
        return {"status": "ok", "message": "Alert acknowledged"}
    return {"status": "error"}


@app.post("/api/calibrate")
def trigger_calibration():
    if mgr is not None:
        mgr.start_calibration()
        return {"status": "ok", "message": "Calibration started"}
    return {"status": "error"}


# Mount static root to serve style.css, app.js and assets
app.mount("/", StaticFiles(directory=str(static_dir)), name="web_root")



# ---------------------------------------------------------------------------
# CLI Launcher
# ---------------------------------------------------------------------------

def run():
    global mgr
    parser = argparse.ArgumentParser(description="Driver Drowsiness Live Web Dashboard")
    parser.add_argument("--port", type=int, default=8000, help="Port to run web app (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    mgr = DashboardManager()
    mgr.start()

    url = f"http://{args.host}:{args.port}"
    print("=" * 65)
    print("  DRIVER DROWSINESS DETECTION — WEB DASHBOARD & MONITOR")
    print("=" * 65)
    print(f"  Live Dashboard:  {url}")
    print(f"  Camera Source:   {mgr.cfg.camera.source}")
    print("=" * 65)

    if not args.no_browser:
        def open_browser():
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    run()
