import os, tempfile, unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from email.message import Message

class WeatherCacheTest(unittest.TestCase):
    def test_hits_and_quota(self):
        with tempfile.TemporaryDirectory() as root:
            os.environ["KFS_WEATHER_CACHE"]=root
            from kfs_weather_cache import cached, QuotaDeferred
            data=[{"hourly":{"time":["2026-11-24T12:00"]}}]
            fetch=Mock(return_value=data)
            self.assertEqual(cached("test",{"run":1},fetch),data)
            self.assertEqual(cached("test",{"run":1},fetch),data)
            fetch.assert_called_once()
            headers=Message();headers["Retry-After"]="60"
            blocked=Mock(side_effect=HTTPError("https://example.com",429,"Quota",headers,None))
            with self.assertRaises(QuotaDeferred):
                cached("test",{"run":2},blocked)
            blocked.assert_called_once()
            with self.assertRaises(QuotaDeferred):
                cached("test",{"run":3},blocked)
            blocked.assert_called_once()
            self.assertEqual(cached("test",{"run":1},fetch),data)

if __name__=="__main__":unittest.main()
