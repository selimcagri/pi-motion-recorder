from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass

@dataclass
class MotionResult:
    motion: bool
    score: float  # rough motion metric (sum of contour areas)

class MotionDetector:
    def __init__(self, method: str = "mog2", history: int = 300, var_threshold: int = 24,
                 min_area: int = 1200, blur_ksize: int = 7, dilate_iter: int = 2, erode_iter: int = 1):
        self.method = method.lower()
        self.min_area = min_area
        self.blur_ksize = blur_ksize
        self.dilate_iter = dilate_iter
        self.erode_iter = erode_iter

        self.bg = None
        self.prev_gray = None
        if self.method == "mog2":
            self.bg = cv2.createBackgroundSubtractorMOG2(
                history=history, varThreshold=var_threshold, detectShadows=False
            )

    def _prep(self, rgb: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        if self.blur_ksize and self.blur_ksize > 1:
            k = self.blur_ksize if self.blur_ksize % 2 == 1 else self.blur_ksize + 1
            gray = cv2.GaussianBlur(gray, (k, k), 0)
        return gray

    def update(self, rgb: np.ndarray) -> MotionResult:
        gray = self._prep(rgb)

        if self.method == "diff":
            if self.prev_gray is None:
                self.prev_gray = gray
                return MotionResult(False, 0.0)
            frame_delta = cv2.absdiff(self.prev_gray, gray)
            self.prev_gray = gray
            _, th = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)
        else:
            fg = self.bg.apply(gray)  # type: ignore
            _, th = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)

        if self.erode_iter > 0:
            th = cv2.erode(th, None, iterations=self.erode_iter)
        if self.dilate_iter > 0:
            th = cv2.dilate(th, None, iterations=self.dilate_iter)

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        area_sum = 0.0
        for c in contours:
            area_sum += float(cv2.contourArea(c))

        motion = any(cv2.contourArea(c) >= self.min_area for c in contours)
        return MotionResult(motion=motion, score=float(area_sum))
