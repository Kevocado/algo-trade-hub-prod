import base64
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from shared.kalshi_ws import build_ws_auth_headers


class TestKalshiWsAuthHeaders(unittest.TestCase):
    def test_build_ws_auth_headers_signing_string_and_signature_verifies(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        api_key_id = "test-key-id"
        ts = "1700000000000"

        headers = build_ws_auth_headers(api_key_id=api_key_id, private_key=private_key, timestamp_ms=ts)

        self.assertEqual(headers["KALSHI-ACCESS-KEY"], api_key_id)
        self.assertEqual(headers["KALSHI-ACCESS-TIMESTAMP"], ts)

        sig_bytes = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        self.assertTrue(len(sig_bytes) > 0)

        # Must match the docs exactly: timestamp + "GET" + "/trade-api/ws/v2"
        message = f"{ts}GET/trade-api/ws/v2".encode("utf-8")

        public_key = private_key.public_key()
        public_key.verify(
            sig_bytes,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )


if __name__ == "__main__":
    unittest.main()

