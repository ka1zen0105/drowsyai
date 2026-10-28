"""Camera capture and MediaPipe Face Mesh pipeline.

Runs in the Vision thread.  Captures frames, detects face landmarks, computes
EAR / MAR / head-pitch via ``features.py``, and pushes ``FeatureRecord``
objects onto a bounded queue for the Fusion thread.
"""

from __future__ import annotations

import sys
import time
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple, Union

import cv2
import numpy as np

from features import compute_ear_avg, compute_mar, estimate_head_pose

# ---------------------------------------------------------------------------
# MediaPipe model download URL
# ---------------------------------------------------------------------------
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)


# ---------------------------------------------------------------------------
# FeatureRecord — output of the vision pipeline, consumed by fusion
# ---------------------------------------------------------------------------

@dataclass
class FeatureRecord:
    """A single frame's worth of computed features."""
    timestamp: float
    frame_id: int
    face_found: bool
    ear_left: float = 0.0
    ear_right: float = 0.0
    ear_avg: float = 0.0
    mar: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    roll_deg: float = 0.0


# ---------------------------------------------------------------------------
# Face Mesh detector (wraps MediaPipe Tasks API)
# ---------------------------------------------------------------------------

class FaceMeshDetector:
    """MediaPipe Face Landmarker wrapper.

    Uses the **Tasks API** (mediapipe ≥ 1.0) with the ``face_landmarker.task``
    model.  Falls back to the legacy ``mp.solutions.face_mesh`` if available.
    """

    def __init__(self, model_path: str = "models/face_landmarker.task",
                 lbf_model_path: str = "models/lbfmodel.yaml"):
        self._model_path = model_path
        self._lbf_model_path = lbf_model_path
        self._backend: str = "none"
        self._detector = None
        self._mp = None
        self._face_cascade = None
        self._facemark = None
        self._tracked_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_landmarks_px: Optional[np.ndarray] = None
        self._frames_since_seen: int = 0
        self._init()

    def lock_subject(self, bbox: Optional[Tuple[int, int, int, int]] = None) -> None:
        """Lock onto a specific subject's face bounding box."""
        if bbox is not None:
            self._tracked_bbox = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
            self.last_bbox = self._tracked_bbox
        elif self.last_bbox is not None:
            self._tracked_bbox = self.last_bbox

    def reset_subject_lock(self) -> None:
        """Clear the current locked subject to allow re-acquiring."""
        self._tracked_bbox = None
        self.last_bbox = None
        self.last_landmarks_px = None
        self._frames_since_seen = 0

    # ---- initialisation ---------------------------------------------------

    def _ensure_model(self) -> str:
        p = Path(self._model_path)
        if p.exists() and p.stat().st_size > 1000:
            return str(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Vision] Downloading face_landmarker model → {p} …")
        urllib.request.urlretrieve(_MODEL_URL, str(p))
        print(f"[Vision] Download complete ({p.stat().st_size:,} bytes).")
        return str(p)

    def _init(self) -> None:
        # Check platform: on Raspberry Pi 4 (Cortex-A72), PyPI's ARM64 MediaPipe
        # binary was compiled with ARMv8.1 LSE atomics that trigger SIGILL.
        # Check /proc/cpuinfo to avoid the crash directly.
        is_rpi4 = False
        try:
            if sys.platform.startswith("linux"):
                with open("/proc/cpuinfo", "r") as f:
                    cpuinfo = f.read()
                    if "Raspberry Pi 4" in cpuinfo or "BCM2711" in cpuinfo or ("Cortex-A72" in cpuinfo and "aes" not in cpuinfo):
                        is_rpi4 = True
        except Exception:
            pass

        if not is_rpi4:
            # 1. Modern Tasks API (mediapipe ≥ 1.0)
            try:
                import mediapipe as mp
                self._mp = mp
                if hasattr(mp, "tasks"):
                    from mediapipe.tasks import python as mp_python
                    from mediapipe.tasks.python import vision as mp_vision

                    model_file = self._ensure_model()
                    base = mp_python.BaseOptions(model_asset_path=model_file)
                    opts = mp_vision.FaceLandmarkerOptions(
                        base_options=base,
                        running_mode=mp_vision.RunningMode.IMAGE,
                        num_faces=1,
                        min_face_detection_confidence=0.5,
                        min_face_presence_confidence=0.5,
                        min_tracking_confidence=0.5,
                        output_face_blendshapes=False,
                    )
                    self._detector = mp_vision.FaceLandmarker.create_from_options(opts)
                    self._backend = "tasks"
                    print("[Vision] MediaPipe Tasks API initialised.")
                    return
            except Exception as exc:
                print(f"[Vision] Tasks API failed ({exc}); trying Solutions / Facemark.")

            # 2. Legacy Solutions API
            try:
                import mediapipe as mp
                if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):
                    self._detector = mp.solutions.face_mesh.FaceMesh(
                        max_num_faces=1, refine_landmarks=True,
                        min_detection_confidence=0.5, min_tracking_confidence=0.5,
                    )
                    self._backend = "solutions"
                    print("[Vision] MediaPipe Solutions API initialised.")
                    return
            except Exception as exc:
                print(f"[Vision] MediaPipe Solutions API failed ({exc}).")

        # 3. Native OpenCV FacemarkLBF (Cortex-A72 / ARM64 optimized, zero illegal instructions)
        try:
            self._init_opencv_facemark()
            return
        except Exception as exc:
            print(f"[Vision] OpenCV Facemark initialization failed ({exc}).")

        raise RuntimeError("No facial landmark detector available (MediaPipe and OpenCV Facemark failed).")

    def _init_opencv_facemark(self) -> None:
        cascade_candidates = [
            "models/haarcascade_frontalface_default.xml",
            str(Path.home() / "drowsy/models/haarcascade_frontalface_default.xml"),
        ]
        cascade_file = None
        for c in cascade_candidates:
            if c and Path(c).exists():
                cascade_file = c
                break

        if not cascade_file:
            cascade_file = "models/haarcascade_frontalface_default.xml"
            Path(cascade_file).parent.mkdir(parents=True, exist_ok=True)
            url = "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml"
            print(f"[Vision] Downloading haarcascade → {cascade_file} …")
            urllib.request.urlretrieve(url, cascade_file)

        lbf_candidates = [
            "models/lbfmodel.yaml",
            str(Path.home() / "drowsy/models/lbfmodel.yaml"),
        ]
        lbf_file = None
        for l in lbf_candidates:
            if l and Path(l).exists():
                lbf_file = l
                break

        if not lbf_file:
            lbf_file = "models/lbfmodel.yaml"
            Path(lbf_file).parent.mkdir(parents=True, exist_ok=True)
            url = "https://raw.githubusercontent.com/kurnianggoro/GSOC2017/master/data/lbfmodel.yaml"
            print(f"[Vision] Downloading lbfmodel.yaml → {lbf_file} …")
            urllib.request.urlretrieve(url, lbf_file)

        self._face_cascade = cv2.CascadeClassifier(str(cascade_file))
        self._facemark = cv2.face.createFacemarkLBF()
        self._facemark.loadModel(str(lbf_file))
        self._backend = "facemark"
        print("[Vision] Native OpenCV FacemarkLBF initialised (ARM Cortex-A72 optimized).")

    # ---- detection --------------------------------------------------------

    def detect(self, bgr_frame: np.ndarray) -> Optional[np.ndarray]:
        """Return normalised landmarks (N, 3) or None if no face found."""
        if bgr_frame is None or bgr_frame.size == 0:
            return None

        if self._backend == "tasks":
            rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            mp_img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            res = self._detector.detect(mp_img)
            if not res.face_landmarks:
                return None
            lms = res.face_landmarks[0]
            pts = np.empty((len(lms), 3), dtype=np.float32)
            for i, lm in enumerate(lms):
                pts[i] = (lm.x, lm.y, lm.z)
            return pts

        if self._backend == "solutions":
            rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            result = self._detector.process(rgb)
            if not result.multi_face_landmarks:
                return None
            lms = result.multi_face_landmarks[0].landmark
            pts = np.empty((len(lms), 3), dtype=np.float32)
            for i, lm in enumerate(lms):
                pts[i] = (lm.x, lm.y, lm.z)
            return pts

        if self._backend == "facemark":
            gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=4, minSize=(60, 60)
            )
            if len(faces) == 0 and self._tracked_bbox is not None:
                # Tilt recovery pass 1: search around tracked subject with relaxed parameters
                tx, ty, tw, th = self._tracked_bbox
                pad_x, pad_y = int(tw * 0.35), int(th * 0.35)
                h_img, w_img = gray.shape[:2]
                rx1 = max(0, tx - pad_x)
                ry1 = max(0, ty - pad_y)
                rx2 = min(w_img, tx + tw + pad_x)
                ry2 = min(h_img, ty + th + pad_y)
                roi = gray[ry1:ry2, rx1:rx2]

                roi_faces = self._face_cascade.detectMultiScale(
                    roi, scaleFactor=1.08, minNeighbors=1, minSize=(int(tw * 0.6), int(th * 0.6))
                )
                if len(roi_faces) > 0:
                    faces = np.array([[fx + rx1, fy + ry1, fw, fh] for (fx, fy, fw, fh) in roi_faces])
                else:
                    # Tilt recovery pass 2: rotated ROI (±18°) for steep left/right head tilt
                    roi_h, roi_w = roi.shape[:2]
                    roi_center = (roi_w / 2.0, roi_h / 2.0)
                    for angle in (-18.0, 18.0):
                        rot_mat = cv2.getRotationMatrix2D(roi_center, angle, 1.0)
                        rot_roi = cv2.warpAffine(roi, rot_mat, (roi_w, roi_h))
                        rot_faces = self._face_cascade.detectMultiScale(
                            rot_roi, scaleFactor=1.10, minNeighbors=2, minSize=(int(tw * 0.6), int(th * 0.6))
                        )
                        if len(rot_faces) > 0:
                            fx, fy, fw, fh = rot_faces[0]
                            fcx, fcy = fx + fw / 2.0, fy + fh / 2.0
                            inv_mat = cv2.getRotationMatrix2D(roi_center, -angle, 1.0)
                            orig_pt = inv_mat @ np.array([fcx, fcy, 1.0])
                            orig_x = int(orig_pt[0] - fw / 2.0 + rx1)
                            orig_y = int(orig_pt[1] - fh / 2.0 + ry1)
                            faces = np.array([[max(0, orig_x), max(0, orig_y), fw, fh]])
                            break


            if len(faces) == 0:
                self._frames_since_seen += 1
                if self._frames_since_seen > 30:
                    self._tracked_bbox = None
                    self.last_bbox = None
                    self.last_landmarks_px = None
                return None

            self._frames_since_seen = 0

            # Single-subject lock-on logic
            if self._tracked_bbox is not None and len(faces) > 1:
                tx, ty, tw, th = self._tracked_bbox
                tcx, tcy = tx + tw / 2.0, ty + th / 2.0
                def score_face(f):
                    fx, fy, fw, fh = f
                    fcx, fcy = fx + fw / 2.0, fy + fh / 2.0
                    center_dist = np.hypot(fcx - tcx, fcy - tcy)
                    area_diff = abs((fw * fh) - (tw * th)) / max(1.0, float(tw * th))
                    return center_dist + area_diff * 40.0
                chosen = min(faces, key=score_face)
            else:
                # Driver face: prefer prominent central face
                h_img, w_img = bgr_frame.shape[:2]
                def initial_driver_score(f):
                    fx, fy, fw, fh = f
                    fcx = fx + fw / 2.0
                    area = fw * fh
                    center_dist = abs(fcx - w_img / 2.0)
                    return area - center_dist * 40.0
                chosen = max(faces, key=initial_driver_score)

            # Smooth tracked bbox (alpha=0.7)
            bx, by, bw, bh = chosen
            if self._tracked_bbox is None:
                self._tracked_bbox = (int(bx), int(by), int(bw), int(bh))
            else:
                ox, oy, ow, oh = self._tracked_bbox
                self._tracked_bbox = (
                    int(0.70 * bx + 0.30 * ox),
                    int(0.70 * by + 0.30 * oy),
                    int(0.70 * bw + 0.30 * ow),
                    int(0.70 * bh + 0.30 * oh),
                )
            self.last_bbox = self._tracked_bbox

            ok, landmarks = self._facemark.fit(gray, np.array([chosen]))
            if not ok or len(landmarks) == 0:
                return None
            pts = landmarks[0].reshape(-1, 2)
            if len(pts) < 68:
                return None
            self.last_landmarks_px = pts
            h, w = bgr_frame.shape[:2]
            norm = np.zeros((len(pts), 3), dtype=np.float32)
            norm[:, 0] = pts[:, 0] / w
            norm[:, 1] = pts[:, 1] / h
            return norm

        return None

    def close(self) -> None:
        if self._detector and hasattr(self._detector, "close"):
            try:
                self._detector.close()
            except Exception:
                pass

    @staticmethod
    def to_pixels(norm: np.ndarray, w: int, h: int) -> np.ndarray:
        """Convert normalised (N,3) landmarks to integer pixel (N,2) array."""
        px = np.empty((len(norm), 2), dtype=np.int32)
        px[:, 0] = np.clip(norm[:, 0] * w, 0, w - 1).astype(np.int32)
        px[:, 1] = np.clip(norm[:, 1] * h, 0, h - 1).astype(np.int32)
        return px


# ---------------------------------------------------------------------------
# Threaded camera reader
# ---------------------------------------------------------------------------

class CameraReader:
    """Background-threaded frame grabber for USB webcams and video files.

    Decouples camera I/O latency from the rest of the vision pipeline.
    """

    def __init__(self, source: Union[int, str, Any] = 0,
                 width: int = 640, height: int = 480, fps: int = 30):
        if hasattr(source, "source"):
            width = getattr(source, "width", width)
            height = getattr(source, "height", height)
            fps = getattr(source, "fps", fps)
            source = source.source

        self.source = int(source) if isinstance(source, str) and source.isdigit() else source
        self.width = width
        self.height = height
        self.target_fps = fps

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "CameraReader":
        if self._running:
            return self

        # Platform-specific backend: V4L2 on Linux/Pi, DirectShow on Windows
        if isinstance(self.source, int):
            if sys.platform.startswith("linux"):
                backend = cv2.CAP_V4L2
            elif sys.platform == "win32":
                backend = cv2.CAP_DSHOW
            else:
                backend = cv2.CAP_ANY
            candidates = [self.source] + [i for i in [0, 1, 2, 3] if i != self.source]
        else:
            backend = cv2.CAP_ANY
            candidates = [self.source]

        for cand in candidates:
            cap = None
            if isinstance(cand, int):
                try:
                    cap = cv2.VideoCapture(int(cand), backend)
                except Exception:
                    cap = None
                if cap is None or not cap.isOpened():
                    try:
                        cap = cv2.VideoCapture(int(cand))
                    except Exception:
                        cap = None
            else:
                try:
                    cap = cv2.VideoCapture(str(cand))
                except Exception:
                    cap = None

            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                continue

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.target_fps)

            # Warmup retry loop
            frame = None
            for _ in range(10):
                ret, frame = cap.read()
                if ret and frame is not None:
                    break
                time.sleep(0.05)

            if frame is not None:
                self.source = cand
                self._cap = cap
                break
            cap.release()

        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera source '{self.source}' (probed candidates: {candidates}).")

        if frame is None:
            raise RuntimeError("Camera opened but first frame read failed.")

        with self._lock:
            self._frame = frame
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="CameraReader")
        self._thread.start()
        return self

    def _loop(self) -> None:
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                break
            ret, frame = self._cap.read()
            if ret and frame is not None:
                with self._lock:
                    self._frame = frame
            else:
                # Video file looping for test replay
                if isinstance(self.source, str):
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                time.sleep(0.01)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def is_running(self) -> bool:
        return self._running and self._cap is not None and self._cap.isOpened()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._cap:
            self._cap.release()
            self._cap = None


# ---------------------------------------------------------------------------
# Facial landmark drawing helper
# ---------------------------------------------------------------------------

def draw_face_landmarks(frame: np.ndarray, landmarks_px: Optional[np.ndarray]) -> None:
    """Draw clear facial landmark dots and contours onto frame.
    
    Draws full face mesh points plus highlighted eyes, mouth, and nose landmarks.
    """
    if landmarks_px is None or len(landmarks_px) == 0:
        return

    n_pts = len(landmarks_px)

    if n_pts >= 468:
        # Full MediaPipe Face Mesh: base mesh dots in subtle emerald green
        for pt in landmarks_px:
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 1, (0, 190, 100), -1)

        # Left eye in bright cyan
        left_eye_indices = [33, 160, 158, 133, 153, 144, 246, 161, 159, 157, 173, 155, 154, 145, 163, 7]
        for idx in left_eye_indices:
            if idx < n_pts:
                cv2.circle(frame, (int(landmarks_px[idx][0]), int(landmarks_px[idx][1])), 2, (255, 255, 0), -1)

        # Right eye in bright cyan
        right_eye_indices = [362, 385, 387, 263, 373, 380, 466, 388, 386, 384, 398, 374, 381, 382, 390, 249]
        for idx in right_eye_indices:
            if idx < n_pts:
                cv2.circle(frame, (int(landmarks_px[idx][0]), int(landmarks_px[idx][1])), 2, (255, 255, 0), -1)

        # Lips / mouth in bright yellow
        mouth_indices = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78, 13, 81, 82, 312, 311]
        for idx in mouth_indices:
            if idx < n_pts:
                cv2.circle(frame, (int(landmarks_px[idx][0]), int(landmarks_px[idx][1])), 2, (0, 255, 255), -1)

        # Nose tip and bridge in orange
        nose_indices = [1, 2, 98, 327, 168, 6, 197, 195, 5]
        for idx in nose_indices:
            if idx < n_pts:
                cv2.circle(frame, (int(landmarks_px[idx][0]), int(landmarks_px[idx][1])), 2, (0, 165, 255), -1)

    elif n_pts >= 68:
        # Standard 68-point model (FacemarkLBF / dlib)
        for pt in landmarks_px[0:17]:
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 1, (0, 190, 100), -1)
        for pt in landmarks_px[17:27]:
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 2, (0, 255, 120), -1)
        for pt in landmarks_px[27:36]:
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 2, (0, 165, 255), -1)
        for pt in landmarks_px[36:48]:
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 2, (255, 255, 0), -1)
        for pt in landmarks_px[48:68]:
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 2, (0, 255, 255), -1)


# ---------------------------------------------------------------------------
# Vision pipeline — to be called in vision thread loop
# ---------------------------------------------------------------------------

def process_frame(
    detector: FaceMeshDetector,
    bgr_frame: np.ndarray,
    frame_id: int,
) -> FeatureRecord:
    """Run full pipeline on one frame: face detection → feature extraction.

    Returns a ``FeatureRecord`` with ``face_found=False`` when no face is
    detected, so the fusion / watchdog threads can react accordingly.
    """
    ts = time.time()
    norm = detector.detect(bgr_frame)
    if norm is None or len(norm) < 68:
        detector.last_landmarks_px = None
        detector.last_bbox = None
        return FeatureRecord(timestamp=ts, frame_id=frame_id, face_found=False)

    h, w = bgr_frame.shape[:2]
    px = FaceMeshDetector.to_pixels(norm, w, h)
    detector.last_landmarks_px = px

    # Update bounding box if not already set by tracker
    if detector.last_bbox is None or detector._backend != "facemark":
        min_x = int(np.min(px[:, 0]))
        max_x = int(np.max(px[:, 0]))
        min_y = int(np.min(px[:, 1]))
        max_y = int(np.max(px[:, 1]))
        pad_w = int((max_x - min_x) * 0.12)
        pad_h = int((max_y - min_y) * 0.12)
        bx = max(0, min_x - pad_w)
        by = max(0, min_y - pad_h)
        bw = min(w - bx, (max_x - min_x) + 2 * pad_w)
        bh = min(h - by, (max_y - min_y) + 2 * pad_h)
        detector.last_bbox = (bx, by, bw, bh)

    ear_l, ear_r, ear_avg = compute_ear_avg(px)
    mar = compute_mar(px)
    pitch, yaw, roll, _, _ = estimate_head_pose(px, (h, w))

    return FeatureRecord(
        timestamp=ts,
        frame_id=frame_id,
        face_found=True,
        ear_left=ear_l,
        ear_right=ear_r,
        ear_avg=ear_avg,
        mar=mar,
        pitch_deg=pitch,
        yaw_deg=yaw,
        roll_deg=roll,
    )
