import threading
import unittest
from queue import Queue
from unittest.mock import patch

import numpy as np

from antimacro import (
    _ocr_worker,
    is_antimacro_monitor_ready,
    is_antimacro_text_present,
    is_metalgreymon_text_present,
)


class AntimacroTextDetectionTests(unittest.TestCase):
    def test_detects_standard_spanish_header(self) -> None:
        self.assertTrue(is_antimacro_text_present("Antimacro activado"))

    def test_detects_header_when_ocr_splits_or_hyphenates_antimacro(self) -> None:
        self.assertTrue(is_antimacro_text_present("Anti-macro activado"))
        self.assertTrue(is_antimacro_text_present("Anti macro activado"))

    def test_ignores_unrelated_game_text(self) -> None:
        self.assertFalse(is_antimacro_text_present("Seleccionar objetivo"))
        self.assertFalse(is_antimacro_text_present("antimacro"))

    def test_detects_metalgreymon_with_or_without_leader_label(self) -> None:
        self.assertTrue(is_metalgreymon_text_present("MetalGreymon"))
        self.assertTrue(is_metalgreymon_text_present("(Líder) MetalGrey mon"))

    def test_rejects_other_target_names(self) -> None:
        self.assertFalse(is_metalgreymon_text_present("Greymon"))
        self.assertFalse(is_metalgreymon_text_present("MetalGarurumon"))


class AntimacroOcrWorkerTests(unittest.TestCase):
    def test_monitor_requires_ocr_when_no_template_is_loaded(self) -> None:
        ready = threading.Event()
        unavailable = threading.Event()

        self.assertFalse(is_antimacro_monitor_ready(False, ready, unavailable))
        ready.set()
        self.assertTrue(is_antimacro_monitor_ready(False, ready, unavailable))
        unavailable.set()
        self.assertFalse(is_antimacro_monitor_ready(False, ready, unavailable))

    def test_template_keeps_monitor_available_without_ocr(self) -> None:
        self.assertTrue(
            is_antimacro_monitor_ready(
                True,
                threading.Event(),
                threading.Event(),
            )
        )

    def test_reports_ocr_unavailable_without_a_compatible_language(self) -> None:
        ready = threading.Event()
        unavailable = threading.Event()

        with patch(
            "antimacro.OcrEngine.try_create_from_user_profile_languages",
            return_value=None,
        ):
            _ocr_worker(
                Queue(maxsize=1),
                threading.Event(),
                threading.Event(),
                ready,
                unavailable,
            )

        self.assertFalse(ready.is_set())
        self.assertTrue(unavailable.is_set())

    def test_reports_ocr_ready_when_worker_starts(self) -> None:
        ready = threading.Event()
        unavailable = threading.Event()
        shutdown = threading.Event()
        shutdown.set()
        fake_ocr = type(
            "FakeOcr",
            (),
            {"recognizer_language": type("Language", (), {"language_tag": "es-MX"})()},
        )()

        with patch(
            "antimacro.OcrEngine.try_create_from_user_profile_languages",
            return_value=fake_ocr,
        ):
            _ocr_worker(
                Queue(maxsize=1),
                threading.Event(),
                shutdown,
                ready,
                unavailable,
            )

        self.assertTrue(ready.is_set())
        self.assertFalse(unavailable.is_set())

    def test_disables_monitor_after_repeated_ocr_errors(self) -> None:
        ready = threading.Event()
        unavailable = threading.Event()
        frames: Queue[np.ndarray] = Queue()
        for _ in range(3):
            frames.put(np.zeros((1, 1, 3), dtype=np.uint8))
        fake_ocr = type(
            "FakeOcr",
            (),
            {"recognizer_language": type("Language", (), {"language_tag": "es-MX"})()},
        )()

        with (
            patch(
                "antimacro.OcrEngine.try_create_from_user_profile_languages",
                return_value=fake_ocr,
            ),
            patch(
                "antimacro.recognize_antimacro_header",
                side_effect=RuntimeError("simulated OCR failure"),
            ),
            patch("antimacro.ANTIMACRO_OCR_INTERVAL", 0),
        ):
            _ocr_worker(
                frames,
                threading.Event(),
                threading.Event(),
                ready,
                unavailable,
            )

        self.assertFalse(ready.is_set())
        self.assertTrue(unavailable.is_set())


if __name__ == "__main__":
    unittest.main()
