import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from api.models import BangladeshLocation


class Command(BaseCommand):
    help = "Imports Bangladesh administrative hierarchy (division/district/upazila/union) from backend/geodata CSVs."

    GEO = "geodata"
    FILES = [
        ("divisions", "divisions.csv"),
        ("districts", "districts.csv"),
        ("upazilas", "upazilas.csv"),
        ("unions", "unions.csv"),
    ]

    def read_rows(self, filename):
        path = os.path.join(settings.BASE_DIR, self.GEO, filename)
        with open(path, encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if not row:
                    continue
                yield [c.strip().strip('"') for c in row]

    def upsert(self, geo_id, level, **defaults):
        obj, created = BangladeshLocation.objects.get_or_create(
            geo_id=geo_id, level=level, defaults=defaults)
        if not created:
            for k, v in defaults.items():
                if v and not getattr(obj, k):
                    setattr(obj, k, v)
            obj.save()
        return obj

    def handle(self, *args, **options):
        counts = {}

        # 1. Divisions
        self.stdout.write("Importing divisions...")
        division_map = {}
        for row in self.read_rows("divisions/divisions.csv"):
            geo_id, name_en, name_bn, url = row
            obj = self.upsert(int(geo_id), 'division',
                              name_en=name_en, name_bn=name_bn,
                              url=url or '', parent=None)
            division_map[int(geo_id)] = obj
        counts['division'] = len(division_map)

        # 2. Districts (parent = division; carries official lat/lon)
        self.stdout.write("Importing districts...")
        district_map = {}
        for row in self.read_rows("districts/districts.csv"):
            geo_id, division_id, name_en, name_bn, lat, lon, url = row
            obj = self.upsert(
                int(geo_id), 'district',
                name_en=name_en, name_bn=name_bn,
                parent=division_map.get(int(division_id)),
                latitude=float(lat) if lat else None,
                longitude=float(lon) if lon else None,
                url=url or '')
            district_map[int(geo_id)] = obj
        counts['district'] = len(district_map)

        # 3. Upazilas (parent = district)
        self.stdout.write("Importing upazilas...")
        upazila_map = {}
        for row in self.read_rows("upazilas/upazilas.csv"):
            geo_id, district_id, name_en, name_bn, url = row
            obj = self.upsert(
                int(geo_id), 'upazila',
                name_en=name_en, name_bn=name_bn,
                parent=district_map.get(int(district_id)),
                url=url or '')
            upazila_map[int(geo_id)] = obj
        counts['upazila'] = len(upazila_map)

        # 4. Unions (parent = upazilla -- note the double-L column in the dump)
        self.stdout.write("Importing unions...")
        union_count = 0
        for row in self.read_rows("unions/unions.csv"):
            geo_id, upazilla_id, name_en, name_bn, url = row
            self.upsert(
                int(geo_id), 'union',
                name_en=name_en, name_bn=name_bn,
                parent=upazila_map.get(int(upazilla_id)),
                url=url or '')
            union_count += 1
        counts['union'] = union_count

        self.stdout.write(self.style.SUCCESS(
            f"Geo import complete: {counts}"))