from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core.config import Settings, get_settings
from app.shared.constants import ALLOWED_BIOMETRIC_IMAGE_TYPES, BIOMETRIC_IMAGE_SUFFIXES
from app.shared.handle_file import verify_file_type

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


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

    def _validate(self, context: PhotoValidationContext) -> None:
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
            grayscale, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
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
