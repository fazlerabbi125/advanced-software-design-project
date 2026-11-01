from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import cv2
import numpy as np

from app.core.config import Settings, get_settings
from app.shared.constants import (
    ALLOWED_BIOMETRIC_IMAGE_TYPES,
    BIOMETRIC_IMAGE_SUFFIXES,
    FACE_DETECTION_MIN_NEIGHBORS,
    FACE_DETECTION_MIN_SIZE,
    FACE_DETECTION_SCALE_FACTOR,
    MAX_BIOMETRIC_IMAGE_PIXELS,
)
from app.shared.handle_file import verify_file_type

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


class PhotoValidationError(ValueError):
    pass


@dataclass(slots=True)
class PhotoValidationContext:
    path: Path
    content_type: str
    image: np.ndarray[Any, Any] | None = None
    verified_suffix: str | None = None


class PhotoValidationHandler(ABC):
    def __init__(self) -> None:
        self._next: PhotoValidationHandler | None = None

    def set_next(self, handler: PhotoValidationHandler) -> PhotoValidationHandler:
        self._next = handler
        return handler

    def validate(self, context: PhotoValidationContext) -> None:
        self._validate(context)
        if self._next is not None:
            self._next.validate(context)

    @abstractmethod
    def _validate(self, context: PhotoValidationContext) -> None: ...


class ImageTypeHandler(PhotoValidationHandler):
    def _validate(self, context: PhotoValidationContext) -> None:
        try:
            verified_mime = verify_file_type(
                context.content_type,
                list(ALLOWED_BIOMETRIC_IMAGE_TYPES),
            )
        except ValueError as error:
            raise PhotoValidationError("unsupported biometric image type") from error

        with context.path.open("rb") as image_file:
            signature = image_file.read(len(PNG_SIGNATURE))
        if verified_mime == "image/png" and not signature.startswith(PNG_SIGNATURE):
            raise PhotoValidationError("image content does not match image/png")
        if verified_mime in {"image/jpeg", "image/jpg"} and not signature.startswith(
            JPEG_SIGNATURE
        ):
            raise PhotoValidationError("image content does not match JPEG")
        context.verified_suffix = BIOMETRIC_IMAGE_SUFFIXES[verified_mime]


class ReadabilityHandler(PhotoValidationHandler):
    def __init__(self, minimum_width: int, minimum_height: int) -> None:
        super().__init__()
        self.minimum_width = minimum_width
        self.minimum_height = minimum_height

    @staticmethod
    def _png_dimensions(image_file: BinaryIO) -> tuple[int, int]:
        header = image_file.read(24)
        if len(header) != 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
            raise PhotoValidationError("image cannot be read")
        return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")

    @staticmethod
    def _jpeg_dimensions(image_file: BinaryIO) -> tuple[int, int]:
        if image_file.read(2) != b"\xff\xd8":
            raise PhotoValidationError("image cannot be read")
        while marker_start := image_file.read(1):
            if marker_start != b"\xff":
                continue
            marker = image_file.read(1)
            while marker == b"\xff":
                marker = image_file.read(1)
            if not marker or marker in {b"\x00", b"\xd8", b"\xd9"}:
                continue
            if marker[0] in {*range(0xD0, 0xD8), 0x01}:
                continue
            length_bytes = image_file.read(2)
            if len(length_bytes) != 2:
                break
            length = int.from_bytes(length_bytes, "big")
            if length < 2:
                break
            if marker[0] in JPEG_SOF_MARKERS:
                dimensions = image_file.read(5)
                if len(dimensions) != 5:
                    break
                return int.from_bytes(dimensions[3:5], "big"), int.from_bytes(
                    dimensions[1:3], "big"
                )
            image_file.seek(length - 2, 1)
        raise PhotoValidationError("image cannot be read")

    def _dimensions(self, context: PhotoValidationContext) -> tuple[int, int]:
        with context.path.open("rb") as image_file:
            if context.verified_suffix == ".png":
                return self._png_dimensions(image_file)
            return self._jpeg_dimensions(image_file)

    def _validate(self, context: PhotoValidationContext) -> None:
        width, height = self._dimensions(context)
        if width <= 0 or height <= 0 or width * height > MAX_BIOMETRIC_IMAGE_PIXELS:
            raise PhotoValidationError("image dimensions are too large")
        image = cv2.imread(str(context.path), cv2.IMREAD_COLOR)
        if image is None:
            raise PhotoValidationError("image cannot be read")
        height, width = image.shape[:2]
        if width < self.minimum_width or height < self.minimum_height:
            raise PhotoValidationError(
                f"image must be at least {self.minimum_width}x{self.minimum_height} pixels"
            )
        context.image = image


class ImageQualityHandler(PhotoValidationHandler):
    def __init__(
        self, minimum_brightness: float, maximum_brightness: float, minimum_blur: float
    ) -> None:
        super().__init__()
        self.minimum_brightness = minimum_brightness
        self.maximum_brightness = maximum_brightness
        self.minimum_blur = minimum_blur

    def _validate(self, context: PhotoValidationContext) -> None:
        if context.image is None:
            raise RuntimeError("image must be decoded before quality validation")
        grayscale = cv2.cvtColor(context.image, cv2.COLOR_BGR2GRAY)
        brightness = float(grayscale.mean())
        if not self.minimum_brightness <= brightness <= self.maximum_brightness:
            raise PhotoValidationError("image brightness is unsuitable for biometric enrolment")
        blur_variance = float(cv2.Laplacian(grayscale, cv2.CV_64F).var())
        if blur_variance < self.minimum_blur:
            raise PhotoValidationError("image is too blurry for biometric enrolment")


class HaarFaceDetector:
    def __init__(self) -> None:
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        self.cascade = cv2.CascadeClassifier(str(cascade_path))
        if self.cascade.empty():
            raise RuntimeError("OpenCV frontal-face cascade is unavailable")

    def count_faces(self, image: np.ndarray[Any, Any]) -> int:
        grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = self.cascade.detectMultiScale(
            grayscale,
            scaleFactor=FACE_DETECTION_SCALE_FACTOR,
            minNeighbors=FACE_DETECTION_MIN_NEIGHBORS,
            minSize=FACE_DETECTION_MIN_SIZE,
        )
        return len(faces)


class SingleFaceHandler(PhotoValidationHandler):
    def __init__(self, face_count: Callable[[np.ndarray[Any, Any]], int]) -> None:
        super().__init__()
        self.face_count = face_count

    def _validate(self, context: PhotoValidationContext) -> None:
        if context.image is None:
            raise RuntimeError("image must be decoded before face validation")
        if self.face_count(context.image) != 1:
            raise PhotoValidationError("image must contain exactly one visible face")


class PhotoValidator:
    def __init__(self, settings: Settings, face_detector: HaarFaceDetector | None = None) -> None:
        detector = face_detector or HaarFaceDetector()
        image_type = ImageTypeHandler()
        readable = image_type.set_next(
            ReadabilityHandler(
                settings.biometric_image_min_width,
                settings.biometric_image_min_height,
            )
        )
        quality = readable.set_next(
            ImageQualityHandler(
                settings.biometric_image_min_brightness,
                settings.biometric_image_max_brightness,
                settings.biometric_image_min_blur_variance,
            )
        )
        quality.set_next(SingleFaceHandler(detector.count_faces))
        self._first = image_type

    def validate(self, path: Path, content_type: str) -> str:
        context = PhotoValidationContext(path=path, content_type=content_type)
        self._first.validate(context)
        if context.verified_suffix is None:
            raise RuntimeError("image type must be verified before validation completes")
        return context.verified_suffix


def get_photo_validator() -> PhotoValidator:
    return PhotoValidator(get_settings())
