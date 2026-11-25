"""Tests du collecteur MTG-LI : NetCDF synthétique, aucun appel externe."""
import io
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import collect as li


class FakeProduct:
    def __init__(self, name, blob):
        self.name, self.blob = name, blob
    def __str__(self):
        return self.name
    def open(self):
        return io.BytesIO(self.blob)


class FakeCollection:
    def __init__(self, products):
        self.products = products
    def search(self, **kwargs):
        return self.products


class FakeStore:
    def __init__(self, products):
        self.products = products
    def get_collection(self, name):
        assert name == li.COLLECTION
        return FakeCollection(self.products)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 7, 18, 12, tzinfo=timezone.utc)
        self.name = "LI-2-LFL_OPE_20261107180000_20261107181000_SAMPLE"
        self.blob = self.sample_zip()

    @staticmethod
    def sample_zip():
        from netCDF4 import Dataset
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "BODY.nc"
            with Dataset(str(path), "w", format="NETCDF4") as ds:
                ds.createDimension("flashes", 3)
                lat = ds.createVariable("latitude", "f4", ("flashes",))
                lon = ds.createVariable("longitude", "f4", ("flashes",))
                times = ds.createVariable("flash_time", "f8", ("flashes",))
                times.units = "seconds since 2026-11-07 18:00:00"
                times.calendar = "standard"
                lat[:] = [49.20, 49.25, 59.00]
                lon[:] = [-0.35, -0.30, 0.10]
                times[:] = [60, 180, 120]
            bio = io.BytesIO()
            with zipfile.ZipFile(bio, "w") as pkg:
                pkg.write(path, arcname="BODY-test.nc")
            return bio.getvalue()

    def test_parse_real_netcdf_and_filter(self):
        points = li.decode_product(self.blob, self.name)
        self.assertEqual(len(points), 2)
        self.assertEqual(len(set(p["id"] for p in points)), 2)
        self.assertTrue(all(40.5 < p["lat"] < 52 for p in points))
        self.assertTrue(all(isinstance(p["ts"], int) for p in points))
        self.assertEqual(points[0]["ts"], int(datetime(
            2026, 11, 7, 18, 1, tzinfo=timezone.utc).timestamp()))

    def test_invalid_zip_is_error_not_zero(self):
        with self.assertRaisesRegex(ValueError, "ZIP"):
            li.decode_product(b"not a zip", self.name)

    def test_run_real_points_and_repeated_run_keeps_previous(self):
        product = FakeProduct(self.name, self.blob)
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "flashes.json"
            one = li.run(output, now=self.now, datastore=FakeStore([product]))
            self.assertEqual(one["state"], "ready")
            self.assertEqual(len(one["flashes"]), 2)
            self.assertEqual(one["latest_product_end_utc"], "2026-11-07T18:10:00Z")
            original = output.read_bytes()
            two = li.run(output, now=self.now + timedelta(minutes=1),
                         datastore=FakeStore([product]))
            self.assertEqual(two["flashes"], one["flashes"])
            self.assertEqual(output.read_bytes(), original)

    def test_empty_source_does_not_overwrite_existing_data(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "flashes.json"
            li.run(output, now=self.now,
                   datastore=FakeStore([FakeProduct(self.name, self.blob)]))
            raw = output.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "Aucun produit"):
                li.run(output, now=self.now + timedelta(minutes=5),
                       datastore=FakeStore([]))
            self.assertEqual(output.read_bytes(), raw)

    def test_retention_and_dedup(self):
        moment = int(self.now.timestamp())
        common = {"id": "same", "lat": 49.1, "lon": 0.2, "ts": moment - 20}
        previous = {"flashes": [
            common, {"id": "too-old", "lat": 49.1, "lon": 0.2,
                     "ts": moment - 7400}], "products_seen": [],
                     "latest_product_end_utc": None}
        updated = li.combine(previous, [common], [], self.now)
        self.assertEqual([x["id"] for x in updated["flashes"]], ["same"])


if __name__ == "__main__":
    unittest.main()
