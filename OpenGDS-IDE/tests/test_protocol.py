import sys
import unittest
sys.path.insert(0, __import__('pathlib').Path(__file__).resolve().parents[1].as_posix())
from protocol import FrameBuffer, encode_message

class ProtocolTests(unittest.TestCase):
    def test_partial_and_multiple_frames(self):
        one = encode_message({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
        two = encode_message({"seq": 2, "type": "event", "event": "stopped"})
        parser = FrameBuffer()
        self.assertEqual(parser.feed(one[:9]), [])
        self.assertEqual(parser.feed(one[9:] + two), [
            {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
            {"seq": 2, "type": "event", "event": "stopped"},
        ])

    def test_utf8_content_length_is_byte_length(self):
        payload = {"message": "مرحبا 🌧"}
        framed = encode_message(payload)
        parser = FrameBuffer()
        self.assertEqual(parser.feed(framed), [payload])

if __name__ == "__main__":
    unittest.main()
