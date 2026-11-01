import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import cv2
import numpy as np

from app.modules.members.photo_validation import PhotoValidationError, PhotoValidator
from app.shared.handle_file import (
    build_filename,
    check_file_exists,
    delete_file,
    verify_file_type,
)
from app.storage.biometric_images import BiometricImageStorage


class FakeFaceDetector:
    def __init__(self, count: int) -> None:
        self.count = count

    def count_faces(self, _image: np.ndarray) -> int:
        return self.count


class InMemoryUpload:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.content_type = content_type
        self.position = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        if self.position >= len(self.content):
            return b""
        end = len(self.content) if size < 0 else self.position + size
        chunk = self.content[self.position : end]
        self.position += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        biometric_image_min_width=300,
        biometric_image_min_height=300,
        biometric_image_min_brightness=50,
        biometric_image_max_brightness=205,
        biometric_image_min_blur_variance=100,
    )


def sharp_image(width: int = 400, height: int = 400) -> np.ndarray:
    grid = (np.indices((height, width)).sum(axis=0) // 16 % 2 * 255).astype(np.uint8)
    return cv2.cvtColor(grid, cv2.COLOR_GRAY2BGR)


def encoded_image(extension: str, image: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(extension, image)
    if not success:
        raise AssertionError("test image encoding failed")
    return encoded.tobytes()


class PhotoValidatorTests(unittest.TestCase):
    def validator(self, face_count: int = 1) -> PhotoValidator:
        return PhotoValidator(settings(), FakeFaceDetector(face_count))

    def write(self, directory: Path, name: str, content: bytes) -> Path:
        path = directory / name
        path.write_bytes(content)
        return path

    def test_accepts_png_jpeg_and_jpg_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cases = (
                ("image.png", "image/png", encoded_image(".png", sharp_image())),
                ("image.jpg", "image/jpeg", encoded_image(".jpg", sharp_image())),
                ("image-jpg.jpg", "image/jpg", encoded_image(".jpg", sharp_image())),
            )
            for name, content_type, content in cases:
                with self.subTest(content_type=content_type):
                    image = self.write(directory, name, content)
                    self.validator().validate(image, content_type)
                    self.assertEqual(
                        verify_file_type(content_type, [content_type]),
                        content_type,
                    )

    def test_rejects_unsupported_and_mismatched_content_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            png = self.write(directory, "image.png", encoded_image(".png", sharp_image()))
            with self.assertRaisesRegex(PhotoValidationError, "unsupported"):
                self.validator().validate(png, "image/webp")
            with self.assertRaisesRegex(PhotoValidationError, "does not match JPEG"):
                self.validator().validate(png, "image/jpeg")

    def test_rejects_unreadable_small_dark_bright_and_blurry_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            unreadable = self.write(directory, "unreadable.png", b"\x89PNG\r\n\x1a\nnot-an-image")
            small = self.write(directory, "small.png", encoded_image(".png", sharp_image(299, 299)))
            dark = self.write(
                directory,
                "dark.png",
                encoded_image(".png", np.zeros((400, 400, 3), dtype=np.uint8)),
            )
            bright = self.write(
                directory,
                "bright.png",
                encoded_image(".png", np.full((400, 400, 3), 255, dtype=np.uint8)),
            )
            blurry = self.write(
                directory,
                "blurry.png",
                encoded_image(".png", np.full((400, 400, 3), 127, dtype=np.uint8)),
            )
            cases = (
                (unreadable, "cannot be read"),
                (small, "at least"),
                (dark, "brightness"),
                (bright, "brightness"),
                (blurry, "blurry"),
            )
            for image, message in cases:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(PhotoValidationError, message):
                        self.validator().validate(image, "image/png")

    def test_rejects_oversized_png_before_decoding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            header = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                + (4_001).to_bytes(4, "big")
                + (4_001).to_bytes(4, "big")
            )
            image = self.write(Path(temporary), "oversized.png", header)
            with patch("app.modules.members.photo_validation.cv2.imread") as decode:
                with self.assertRaisesRegex(PhotoValidationError, "dimensions are too large"):
                    self.validator().validate(image, "image/png")
            decode.assert_not_called()

    def test_rejects_zero_or_multiple_faces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = self.write(Path(temporary), "image.png", encoded_image(".png", sharp_image()))
            for count in (0, 2):
                with self.subTest(count=count):
                    with self.assertRaisesRegex(PhotoValidationError, "exactly one"):
                        self.validator(count).validate(image, "image/png")


class BiometricImageStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_upload_closes_stream_and_leaves_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upload_root = Path(temporary)
            storage = BiometricImageStorage(PhotoValidator(settings(), FakeFaceDetector(0)))
            upload = InMemoryUpload(encoded_image(".png", sharp_image()), "image/png")
            runtime_settings = SimpleNamespace(
                upload_root=upload_root,
                biometric_image_max_bytes=5 * 1024 * 1024,
            )
            with patch("app.storage.biometric_images.get_settings", return_value=runtime_settings):
                with self.assertRaisesRegex(PhotoValidationError, "exactly one"):
                    await storage.save(uuid4(), upload)

            self.assertTrue(upload.closed)
            self.assertEqual([path for path in upload_root.rglob("*") if path.is_file()], [])

    async def test_valid_upload_promotes_verified_image_with_server_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upload_root = Path(temporary)
            storage = BiometricImageStorage(PhotoValidator(settings(), FakeFaceDetector(1)))
            upload = InMemoryUpload(encoded_image(".jpg", sharp_image()), "image/jpg")
            runtime_settings = SimpleNamespace(
                upload_root=upload_root,
                biometric_image_max_bytes=5 * 1024 * 1024,
            )
            with patch("app.storage.biometric_images.get_settings", return_value=runtime_settings):
                stored = await storage.save(uuid4(), upload)

            self.assertTrue(upload.closed)
            self.assertEqual(stored.content_type, "image/jpg")
            self.assertTrue(stored.key.endswith(".jpg"))
            self.assertTrue((upload_root / stored.key).is_file())
            self.assertEqual(list(upload_root.rglob("*.upload")), [])


class FileHandlingTests(unittest.TestCase):
    def test_verify_file_type_uses_the_callers_allow_list(self) -> None:
        self.assertEqual(
            verify_file_type("application/pdf", ["application/pdf", "text/plain"]),
            "application/pdf",
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            verify_file_type("application/x-python", ["application/pdf"])

    def test_build_filename_and_missing_file_cleanup(self) -> None:
        filename = build_filename(".jpg")
        self.assertTrue(filename.endswith(".jpg"))
        self.assertNotIn("/", filename)
        self.assertTrue(build_filename(".py").endswith(".py"))
        self.assertTrue(build_filename(".tar.gz").endswith(".tar.gz"))
        for suffix in (".jpg/../unsafe", "jpg", "."):
            with self.subTest(suffix=suffix):
                with self.assertRaisesRegex(ValueError, "path separators|extension"):
                    build_filename(suffix)
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.jpg"
            delete_file(missing)
            self.assertFalse(check_file_exists(missing))


if __name__ == "__main__":
    unittest.main()
