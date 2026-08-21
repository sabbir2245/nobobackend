import hashlib
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from api.models import BangladeshLocation


class Command(BaseCommand):
    help = (
        "Imports Dhaka City Corporation areas (DNCC/DSCC wards & areas) from "
        "geodata/city_corp.json as 'ward' level BangladeshLocation rows under "
        "the Dhaka district. Used so customers selecting Dhaka can pick a "
        "city corporation area at signup."
    )

    GEO = "geodata"
    FILENAME = "city_corp.json"
    # geo_id of the Dhaka district (from geodata/districts/districts.csv).
    DHAKA_DISTRICT_GEO_ID = 47

    @staticmethod
    def _geo_id(ext_id):
        """Derive a stable integer id from the JSON's string id (md5 → int).

        Uses 7 hex chars so the value stays within the signed 32-bit int4
        range (max 0xFFFFFFF = 268,435,455) that the geo_id column allows.
        """
        ext_id = (ext_id or '').strip()
        if not ext_id:
            return None
        return int(hashlib.md5(ext_id.encode()).hexdigest()[:7], 16)

    def handle(self, *args, **options):
        path = os.path.join(settings.BASE_DIR, self.GEO, self.FILENAME)
        with open(path, encoding='utf-8') as f:
            rows = json.load(f)

        district = BangladeshLocation.objects.filter(
            level='district',
            geo_id=self.DHAKA_DISTRICT_GEO_ID,
        ).first()
        if district is None:
            self.stdout.write(self.style.ERROR(
                "Dhaka district not found. Run `import_geo` first."))
            return

        created = 0
        updated = 0
        skipped = 0
        for item in rows:
            name_en = (item.get('area_name') or {}).get('en', '').strip()
            name_bn = (item.get('area_name') or {}).get('bn', '').strip()
            tag = (item.get('city_corp_tag') or '').strip()
            ward = (item.get('ward') or '').strip()
            ext_id = (item.get('id') or '').strip()

            if not name_en or not tag:
                skipped += 1
                continue

            obj, created_flag = BangladeshLocation.objects.get_or_create(
                level='ward',
                geo_id=self._geo_id(ext_id),
                defaults={
                    'name_en': name_en,
                    'name_bn': name_bn,
                    'parent': district,
                    'city_corp': tag,
                    'ward_no': ward,
                },
            )
            if created_flag:
                created += 1
            else:
                dirty = False
                if obj.name_en != name_en:
                    obj.name_en = name_en
                    dirty = True
                if obj.name_bn != name_bn:
                    obj.name_bn = name_bn
                    dirty = True
                if obj.parent_id != district.id:
                    obj.parent = district
                    dirty = True
                if obj.city_corp != tag:
                    obj.city_corp = tag
                    dirty = True
                if obj.ward_no != ward:
                    obj.ward_no = ward
                    dirty = True
                if dirty:
                    obj.save()
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"City corporation import complete: created={created}, updated={updated}, skipped={skipped}"))
        self.stdout.write(self.style.SUCCESS(
            f"Dhaka ward/city-corp areas now total: "
            f"{BangladeshLocation.objects.filter(level='ward', parent=district).count()}"))