import unittest

from app_info import APP_NAME, VERSION, DEVELOPER


class AppInfoTests(unittest.TestCase):
    def test_public_release_metadata(self):
        self.assertEqual(APP_NAME, "OpenGDS - IDE")
        self.assertEqual(VERSION, "1.0.2")
        self.assertEqual(DEVELOPER, "0xbytecode")


if __name__ == "__main__":
    unittest.main()
