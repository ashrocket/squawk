"""build_pool() encodes Ashley's 2026-06 listening test: default first,
Kokoro next, then all Premiums; Enhanced and basic tiers are out entirely."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import speak

FAKE_INSTALLED = [
    "Ava (Premium)", "Isha (Premium)", "Serena (Premium)",
    "Allison (Enhanced)", "Ava (Enhanced)", "Isha (Enhanced)",
    "Kate (Enhanced)", "Daniel (Enhanced)", "Serena (Enhanced)",
    "Karen", "Samantha", "Eddy (English (US))",
]


class BuildPoolTest(unittest.TestCase):
    def setUp(self):
        self._installed = speak.installed_english_voices
        self._model, self._bin = speak.KOKORO_MODEL, speak.KOKORO_VOICES_BIN
        speak.installed_english_voices = lambda: list(FAKE_INSTALLED)
        existing = pathlib.Path(speak.__file__)  # any path that exists
        speak.KOKORO_MODEL = speak.KOKORO_VOICES_BIN = existing
        self.pool = speak.build_pool()

    def tearDown(self):
        speak.installed_english_voices = self._installed
        speak.KOKORO_MODEL, speak.KOKORO_VOICES_BIN = self._model, self._bin

    def test_default_stays_first(self):
        self.assertEqual(self.pool[0], speak.DEFAULT_VOICE)

    def test_all_premiums_kept(self):
        for v in ["Ava (Premium)", "Isha (Premium)", "Serena (Premium)"]:
            self.assertIn(v, self.pool)

    def test_no_enhanced_voices(self):
        for v in FAKE_INSTALLED:
            if "(Enhanced)" in v:
                self.assertNotIn(v, self.pool)

    def test_no_basic_voices(self):
        for v in ["Karen", "Samantha", "Eddy (English (US))"]:
            self.assertNotIn(v, self.pool)

    def test_kokoro_outranks_premium(self):
        self.assertLess(self.pool.index("kokoro:af_heart"),
                        self.pool.index("Isha (Premium)"))


class PoolFileOverrideTest(unittest.TestCase):
    """A pool.json written by the settings app overrides the computed pool."""

    def setUp(self):
        self._installed = speak.installed_english_voices
        self._model, self._bin = speak.KOKORO_MODEL, speak.KOKORO_VOICES_BIN
        self._pool_file = speak.POOL_FILE
        speak.installed_english_voices = lambda: list(FAKE_INSTALLED)
        existing = pathlib.Path(speak.__file__)
        speak.KOKORO_MODEL = speak.KOKORO_VOICES_BIN = existing
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        speak.POOL_FILE = pathlib.Path(self.tmp.name)

    def tearDown(self):
        speak.installed_english_voices = self._installed
        speak.KOKORO_MODEL, speak.KOKORO_VOICES_BIN = self._model, self._bin
        pathlib.Path(self.tmp.name).unlink(missing_ok=True)
        speak.POOL_FILE = self._pool_file

    def _write(self, voices):
        import json
        pathlib.Path(self.tmp.name).write_text(json.dumps(voices))

    def test_pool_file_order_is_honored(self):
        self._write(["Isha (Premium)", "default", "kokoro:bf_emma"])
        self.assertEqual(speak.build_pool(),
                         ["Isha (Premium)", "default", "kokoro:bf_emma"])

    def test_unavailable_voices_are_dropped(self):
        self._write(["default", "Gone (Premium)", "Karen", "kokoro:af_heart"])
        # "Gone" isn't installed; "Karen" basic is installed so it stays
        self.assertEqual(speak.build_pool(),
                         ["default", "Karen", "kokoro:af_heart"])

    def test_kokoro_dropped_when_models_missing(self):
        speak.KOKORO_MODEL = pathlib.Path("/nonexistent")
        self._write(["default", "kokoro:af_heart", "Isha (Premium)"])
        self.assertEqual(speak.build_pool(), ["default", "Isha (Premium)"])


if __name__ == "__main__":
    unittest.main()
