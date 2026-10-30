"""Hardware-free decoder tests; these are synthetic, NOT bench evidence."""
import unittest

from bench_isp_trace import decode, decode_terminal


def fixture():
    params = bytes([200,100,25,32,0,0x53,3,0xac,0x53,0,0])
    header = bytes([1,6,1,31]) + params + params + bytes([0xc0,1,0,0,3,1,0x38,1])
    events = bytes([3,64,0,0,0,0,7,64,0xff,0xff,0xff,0xff,6,67,0,0,0,0])
    data = header + events
    checksum = 0
    for value in data:
        checksum ^= value
    return data + bytes([checksum])


class TraceTests(unittest.TestCase):
    def test_decode(self):
        result = decode(fixture())
        self.assertTrue(result["parameter_order_matches"])
        self.assertEqual(result["parsed_parameters"]["poll_index"], 3)
        self.assertEqual(result["parsed_parameters"]["poll_value"], 0x53)
        self.assertEqual(result["vtarget_volts"], 3.1)
        self.assertEqual(result["events"][0]["aux0_direction"], "output")
        self.assertEqual(result["events"][1]["rx_hex"], "ff ff ff ff")
        self.assertFalse(result["events"][1]["poll_match"])
        self.assertEqual(result["events"][2]["aux0_level"], 1)
        self.assertEqual(result["events"][2]["aux0_direction"], "input")

    def test_terminal(self):
        raw = b"HiZ>i\r\nISPD1 " + fixture().hex().encode() + b"\r\nHiZ>"
        self.assertEqual(len(decode_terminal(raw)), 1)
        with self.assertRaises(ValueError):
            decode_terminal(b"HiZ>")

    def test_corruption(self):
        data = bytearray(fixture())
        data[5] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            decode(data)
        with self.assertRaises(ValueError):
            decode(fixture()[:-6])
        with self.assertRaises(ValueError):
            decode(b"")


if __name__ == "__main__":
    unittest.main()
