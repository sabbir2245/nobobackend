import os
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token
from api.models import (
    Post, PostImage, Order, Review, ReviewImage, ProductType,
    Payment, FarmerBankAccount, OTP, BangladeshLocation, Area,
    Batch, BatchItem, PendingPool,
)
from api.services import process_new_order
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

User = get_user_model()

# ==========================================================
# bKash Sandbox Credentials (Tokenized Checkout v1.2.0-beta)
# ==========================================================
# Merchant API credentials:
#   Username : sandboxTokenizedUser02
#   Password : sandboxTokenizedUser02@12345
#   App Key  : 4f6o0cjiki2rfm34kfdadl1eqq
#   App Secret: 2is7hdktrekvrbljjh44ll3d9l1dtjo4pasmjvs5vl5qr3fug4b
# (These match backend/nobanno/settings.py:145-149.)
#
# Test wallet (customer) numbers — enter one on bKash's hosted payment page:
#   Successful              : 01770618575, 01929918378, 01770618576,
#                             01877722345, 01619777282, 01619777283
#   Failed (insufficient)   : 01823074817
#   Failed (debit block)    : 01823074818
#
# Test wallet PIN / OTP:
#   PIN : 12121
#   OTP : 123456
#
# Environment URLs:
#   Sandbox : https://tokenized.sandbox.bka.sh/v1.2.0-beta
#   Live    : https://tokenized.pay.bka.sh/v1.2.0-beta
#             (do NOT use sandbox credentials on live)
# ==========================================================


def loc(level, name_en):
    return BangladeshLocation.objects.filter(level=level, name_en=name_en).first()


def union_obj(geo_id):
    return BangladeshLocation.objects.filter(level='union', geo_id=geo_id).first()


class Command(BaseCommand):
    help = "Seeds the database with test data for the new delivery (batch) system."

    def handle(self, *args, **options):
        self.stdout.write("Clearing existing database...")
        PendingPool.objects.all().delete()
        BatchItem.objects.all().delete()
        Batch.objects.all().delete()
        Order.objects.all().delete()
        PostImage.objects.all().delete()
        Post.objects.all().delete()
        ReviewImage.objects.all().delete()
        Review.objects.all().delete()
        Area.objects.all().delete()
        FarmerBankAccount.objects.all().delete()
        Payment.objects.all().delete()
        OTP.objects.all().delete()
        Token.objects.all().delete()
        User.objects.all().delete()
        ProductType.objects.all().delete()

        self.stdout.write("Importing Bangladesh geo hierarchy...")
        call_command('import_geo')

        # ==========================================
        # PRODUCT TYPES
        # ==========================================
        product_types_data = [
            ("Garlic", "রসুন"),
            ("Raw Banana", "কলা (কাঁচা)"),
            ("Carrot", "গাজর"),
            ("Cherry", "চেরি"),
            ("Cucumber", "শসা"),
            ("Eggplant", "বেগুন"),
            ("Tomato", "টমেটো"),
            ("Potato", "আলু"),
            ("Onion", "পেঁয়াজ"),
            ("Green Chili", "কাঁচামরিচ"),
            ("Melon", "তরমুজ"),
            ("Peach", "পীচ"),
            ("Rice", "চাল"),
            ("Zucchini", "ঝুকিনি"),
        ]
        product_type_map = {}
        for name_en, name_bn in product_types_data:
            pt, _ = ProductType.objects.get_or_create(name_en=name_en, defaults={"name_bn": name_bn})
            product_type_map[name_en] = pt

        # ==========================================
        # AREAS (admin-set delivery thresholds)
        # ==========================================
        savar = loc('upazila', 'Savar')
        nangalkot = loc('upazila', 'Nangalkot')
        sherpur = loc('upazila', 'Sherpur')
        paba = loc('upazila', 'Paba')
        sharsha = loc('upazila', 'Sharsha')

        area_savar, _ = Area.objects.get_or_create(
            name="Dhaka Savar Cluster",
            defaults={'threshold_kg': Decimal('500.00'), 'is_active': True})
        area_savar.upazilas.add(savar)

        area_comilla, _ = Area.objects.get_or_create(
            name="Comilla Nangalkot Cluster",
            defaults={'threshold_kg': Decimal('300.00'), 'is_active': True})
        area_comilla.upazilas.add(nangalkot)

        area_bogura, _ = Area.objects.get_or_create(
            name="Bogura Sherpur Cluster",
            defaults={'threshold_kg': Decimal('500.00'), 'is_active': True})
        area_bogura.upazilas.add(sherpur)

        area_rajshahi, _ = Area.objects.get_or_create(
            name="Rajshahi Cluster",
            defaults={'threshold_kg': Decimal('500.00'), 'is_active': True})
        area_rajshahi.upazilas.add(paba)

        area_jashore, _ = Area.objects.get_or_create(
            name="Jashore Cluster",
            defaults={'threshold_kg': Decimal('400.00'), 'is_active': True})
        area_jashore.upazilas.add(sharsha)

        # ==========================================
        # USERS (location = a real Union)
        # ==========================================
        self.stdout.write("Creating users (1 Admin, 5 Farmers, 2 Customers, 2 Deliverymen)...")

        admin_user = User.objects.create_superuser(
            username="robi",
            email="nobanno.contact@gmail.com",
            password="lifeisso4green@",
            role="admin",
            name="Super Admin",
            phone_number="01000000000",
            address="Aminbazar, Savar, Dhaka",
            location=union_obj(3282),
            is_verified=True,
        )
        Token.objects.create(user=admin_user)

        # Farmers (union geo_ids chosen from real geo data)
        f1 = User.objects.create_user(
            username="fjamal", email="jamal@farms.com", password="F1",
            role="farmer", name="Jamal Uddin", phone_number="01712345678",
            address="Aminbazar Wholesale Market, Savar, Dhaka",
            location=union_obj(3282), is_verified=True, bkash_number="01712345678",
        )
        f2 = User.objects.create_user(
            username="frahim", email="rahim@bogura.com", password="F2",
            role="farmer", name="Rahim Mia", phone_number="01812345678",
            address="Garidaha, Sherpur, Bogura",
            location=union_obj(1194), is_verified=True, bkash_number="01812345678",
        )
        f3 = User.objects.create_user(
            username="fkarim", email="karim@rajshahi.com", password="F3",
            role="farmer", name="Karim Ahmed", phone_number="01612345678",
            address="Damkura, Paba, Rajshahi",
            location=union_obj(1216), is_verified=True, bkash_number="01612345678",
        )
        f4 = User.objects.create_user(
            username="fselim", email="selim@jashore.com", password="F4",
            role="farmer", name="Selim Hossain", phone_number="01512345678",
            address="Benapole, Sharsha, Jashore",
            location=union_obj(1596), is_verified=True, bkash_number="01512345678",
        )
        f5 = User.objects.create_user(
            username="farif", email="arif@comilla.com", password="F5",
            role="farmer", name="Arif Chowdhury", phone_number="01998765432",
            address="Mokara, Nangalkot, Comilla",
            location=union_obj(120), is_verified=True, bkash_number="01998765432",
        )
        for f in [f1, f2, f3, f4, f5]:
            Token.objects.create(user=f)

        c1 = User.objects.create_user(
            username="rahimk", email="rahimk@restaurant.com", password="C",
            role="customer", name="ratul", phone_number="01912345678",
            address="Aminbazar, Savar, Dhaka",
            location=union_obj(3282), is_verified=True,
        )
        c2 = User.objects.create_user(
            username="chasan", email="hasan@retail.com", password="C23",
            role="customer", name="Hasan Groceries", phone_number="01512345678",
            address="Savar, Dhaka",
            location=union_obj(3271), is_verified=True,
        )
        c3 = User.objects.create_user(
            username="cmukta", email="mukta@bazar.com", password="C3",
            role="customer", name="Mukta Rahman", phone_number="01655567891",
            address="Nabinagar, Savar, Dhaka",
            location=union_obj(3282), is_verified=True,
        )
        c4 = User.objects.create_user(
            username="ctanvir", email="tanvir@kitchen.com", password="C4",
            role="customer", name="Tanvir Ahmed", phone_number="01777788990",
            address="Hemayetpur, Savar, Dhaka",
            location=union_obj(3271), is_verified=True,
        )
        for c in [c1, c2, c3, c4]:
            Token.objects.create(user=c)

        d1 = User.objects.create_user(
            username="dkarim", email="karim@delivery.com", password="D1",
            role="deliveryman", name="Karim Delivery", phone_number="01600000001",
            address="Savar, Dhaka",
            location=union_obj(3282),
            service_areas=[area_savar.id, area_comilla.id],
            is_verified=True,
        )
        d2 = User.objects.create_user(
            username="drahim", email="rahim@delivery.com", password="D2",
            role="deliveryman", name="Rahim Delivery", phone_number="01600000002",
            address="Nangalkot, Comilla",
            location=union_obj(120),
            service_areas=[area_comilla.id],
            is_verified=True,
        )
        for d in [d1, d2]:
            Token.objects.create(user=d)

        # ==========================================
        # IMAGE UTILITY
        # ==========================================
        timage_dir = settings.MEDIA_ROOT
        fallback_bytes = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00'
            b'\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
            b'\x01\x00\x01\x00\x00\x02\x02\x4c\x01\x00\x3b'
        )

        def get_image_file(filename):
            full_path = os.path.join(timage_dir, filename)
            if os.path.exists(timage_dir):
                for actual_file in os.listdir(timage_dir):
                    if actual_file.lower() == filename.lower():
                        full_path = os.path.join(timage_dir, actual_file)
                        break
            if os.path.exists(full_path) and os.path.isfile(full_path):
                stored_name = filename
                # Extensionless source files would be served as octet-stream and
                # may not render; give them a .jpg so they serve as image/jpeg.
                if not os.path.splitext(stored_name)[1]:
                    stored_name = stored_name + '.jpg'
                with open(full_path, 'rb') as f:
                    return SimpleUploadedFile(name=stored_name, content=f.read(), content_type='image/jpeg')
            return SimpleUploadedFile(name=f"fallback_{filename}.gif", content=fallback_bytes, content_type='image/gif')

        # ==========================================
        # POSTS
        # ==========================================
        self.stdout.write("Creating post listings (all timage assets)...")

        def create_post(farmer, pt_key, title, price, stock, desc, union_id, cp, main_img, gallery=()):
            post = Post.objects.create(
                farmer=farmer,
                product_type=product_type_map.get(pt_key),
                title=title,
                price_per_kg=price,
                total_weight_kg=stock,
                description=desc,
                location=union_obj(union_id),
                collection_point_address=cp,
                image=get_image_file(main_img),
            )
            for img_name in gallery:
                PostImage.objects.create(post=post, image=get_image_file(img_name))
            return post

        savar_cp = "Aminbazar Wholesale Market, Savar, Dhaka"
        bogura_cp = "Garidaha Bazar, Sherpur, Bogura"
        rajshahi_cp = "Damkura Haat, Paba, Rajshahi"
        jashore_cp = "Benapole Bazar, Sharsha, Jashore"
        comilla_cp = "Mokara Bazar, Nangalkot, Comilla"

        # ---- Savar (f1 Jamal) ----
        p_garlic = create_post(
            f1, "Garlic", "Deshi Sun-dried Organic Garlic", 120.00, 800,
            "Premium sun-dried deshi garlic, mild yet pungent, ideal for bulk buyers. Harvested this season.",
            3282, savar_cp, "garlic.jpeg",
            gallery=("garlic3.jpeg", "garlic35.jpeg"))
        p_banana = create_post(
            f1, "Raw Banana", "Sagar Banana (Medium, Uniform Size)", 40.00, 600,
            "Sweet sagar bananas, medium uniform size, good for cooking and ripening stock.",
            3282, savar_cp, "banana_avg.jpg",
            gallery=("banana_large.jpg", "banana_large.jpeg", "banana_short.jpg"))
        p_carrot = create_post(
            f1, "Carrot", "Fresh Spring Carrots (Grade A)", 60.00, 700,
            "Crisp, sweet, deep-orange carrots. Washed and graded, ready for retail and kitchen.",
            3282, savar_cp, "carrot1.jpg",
            gallery=("carrot2.jpg",))
        p_eggplant = create_post(
            f1, "Eggplant", "Bogra-Style Brinjal (Long Variety)", 50.00, 500,
            "Long slim purple brinjal, tender flesh, very low seed count. Great for bhaji and bhorta.",
            3282, savar_cp, "eggplant_1.jpg",
            gallery=("eggplant_long.jpg",))
        p_tomato = create_post(
            f1, "Tomato", "Ripe Red Hybrid Tomato", 55.00, 600,
            "Juicy, uniformly red hybrid tomatoes. Picked at peak ripeness, packed for distance.",
            3282, savar_cp, "tomato.jpg")
        p_tomato_organic = create_post(
            f1, "Tomato", "Organic Cherry Tomatoes (Premium)", 90.00, 400,
            "Premium cherry tomatoes, naturally ripened, high brix sweetness. Hand-sorted and boxed for retail.",
            3282, savar_cp, "-tomato-- (15)",
            gallery=("-tomato-- (16)", "-tomato-- (9)"))
        p_tomato_deshi = create_post(
            f1, "Tomato", "Deshi Red Tomato (Number 65 Grade)", 48.00, 900,
            "Farm-fresh deshi red tomatoes, thick skin, ideal for curry and paste. Bulk wholesale supply.",
            3282, savar_cp, "-tomato--number- (65)",
            gallery=("-tomato--number- (69)", "-tomato--number- (9)"))
        p_tomato_web = create_post(
            f1, "Tomato", "Premium Fresh Tomato (Web Featured)", 68.00, 500,
            "Premium fresh red tomatoes, thick skin and sweet flesh. Hand-picked, graded and boxed for delivery.",
            3282, savar_cp, "tomato_1.jpeg",
            gallery=("tomato_2.jpeg", "tomato_3.jpeg"))

        # ---- Bogura (f2 Rahim) ----
        p_cucumber = create_post(
            f2, "Cucumber", "Green Salad Cucumber (Bulk)", 42.00, 1200,
            "Fresh crunchy salad cucumbers, multiple grades (kacha, thick, long). Greenhouse grown.",
            1194, bogura_cp, "cucumber.jpg",
            gallery=("cucumber_deshi.jpg", "cucumber_dotted.jpg", "cucucumber_kacha.jpg",
                     "cucucumber_thick.jpg", "cucumbers_extra_long.jpg", "cucumbers_jes.jpg"))
        p_rice = create_post(
            f2, "Rice", "Boro Hybrid Paddy (Fresh Mill)", 52.00, 2000,
            "New-season boro hybrid rice, freshly milled, long grain, low broken %. Bulk sacks.",
            1194, bogura_cp, "rice.jpg",
            gallery=("rice_basmati.jpg",))

        # ---- Rajshahi (f3 Karim) ----
        p_potato = create_post(
            f3, "Potato", "Rajshahi Diamond Potato", 30.00, 3000,
            "High-yield Diamond variety, firm texture, ideal for curry and chips. Bulk haat supply.",
            1216, rajshahi_cp, "potato.jpg")
        p_chili = create_post(
            f3, "Green Chili", "Fresh Green Chili (Rajshahi)", 95.00, 400,
            "Freshly harvested hot green chilies, tight skin and high pungency.",
            1216, rajshahi_cp, "greenchilli.jpeg",
            gallery=("chilli2.jpeg",))

        # ---- Jashore (f4 Selim) ----
        p_onion = create_post(
            f4, "Onion", "Jashore Red Onion", 45.00, 2000,
            "Premium red onions from Jashore, firm and dry-stored. The famous Jashore onion.",
            1596, jashore_cp, "onion1.jpeg",
            gallery=("onion_indian.jpeg",))

        # ---- Comilla (f5 Arif) ----
        p_melon = create_post(
            f5, "Melon", "Sweet Red Watermelon", 35.00, 1500,
            "Juicy sweet red watermelons, 4-7 kg each. Chilled-shipped from Nangalkot.",
            120, comilla_cp, "melons1.jpg",
            gallery=("melons2.jpg",))
        p_cherry = create_post(
            f5, "Cherry", "Premium Imported Cherries", 850.00, 150,
            "Premium cherries, hand-sorted, chilled. Limited seasonal stock.",
            120, comilla_cp, "cherries1.jpg",
            gallery=("cherries2.jpg",))
        p_peach = create_post(
            f5, "Peach", "Golden Peach (Fresh Fruit)", 480.00, 120,
            "Sweet golden peaches, graded boxed fruit. Limited stock.",
            120, comilla_cp, "peaches.jpg")
        p_zucchini = create_post(
            f5, "Zucchini", "Fresh Green Zucchini", 90.00, 300,
            "Tender young zucchini, uniform shape, mild flavour. Good for export-grade packing.",
            120, comilla_cp, "zuccini.jpg")

        # ==========================================
        # FARMER BANK ACCOUNTS (for settlement / BEFTN)
        # ==========================================
        self.stdout.write("Creating farmer bank accounts...")
        bank_data = [
            (f1, 'BRAC Bank', 'Savar', '020271634', '1571100001234567', 'savings', '01712345678'),
            (f2, 'Dutch-Bangla Bank', 'Sherpur', '090970641', '1781100002345678', 'current', '01812345678'),
            (f3, 'Islami Bank', 'Paba', '040111111', '2051100003456789', 'savings', '01612345678'),
            (f4, 'Sonali Bank', 'Sharsha', '260221021', '1631100004567890', 'savings', '01512345678'),
            (f5, 'Agrani Bank', 'Nangalkot', '190224431', '1161100005678901', 'current', '01998765432'),
        ]
        for farmer, bank, branch, rt, acct, atype, mob in bank_data:
            FarmerBankAccount.objects.create(
                farmer=farmer, bank_name=bank, branch_name=branch,
                routing_number=rt, account_number=acct, account_type=atype, mobile_number=mob)

        # ==========================================
        # ORDERS — feed pools → build batches across every lifecycle state
        # ==========================================
        self.stdout.write("Creating orders (feeds pool / builds batches)...")

        def make_order(customer, post, qty):
            """Create a pending order and feed its post's area→union+product pool."""
            from api.models import OrderItem
            with transaction.atomic():
                qty_dec = Decimal(str(qty))
                total = round(qty_dec * Decimal(str(post.price_per_kg)), 2)
                fee = round(total * Decimal('0.10'), 2)
                payout = total - fee
                post.total_weight_kg = Decimal(str(post.total_weight_kg)) - qty_dec
                post.save(update_fields=['total_weight_kg'])
                advance = round(total / 2, 2)
                final = total - advance
                order = Order.objects.create(
                    customer=customer, status='pending',
                    total_paid=total, platform_fee=fee, farmer_payout=payout,
                    delivery_address=customer.address or 'Dhaka',
                    advance_amount=advance, final_amount=final,
                )
                OrderItem.objects.create(
                    order=order, post=post, farmer=post.farmer,
                    quantity_kg=qty_dec, quantity_type=post.quantity_type,
                    est_weight_kg=post.est_weight_kg,
                    price_per_kg=post.price_per_kg, subtotal=total,
                )
                process_new_order(order)
                return order

        def assign_and_deliver(batch, deliveryman):
            """Run the deliveryman accept + deliver lifecycle for a batch."""
            batch.status = 'assigned'
            batch.deliveryman = deliveryman
            batch.assigned_at = timezone.now()
            batch.save(update_fields=['status', 'deliveryman', 'assigned_at'])
            batch.status = 'delivered'
            batch.delivered_at = timezone.now()
            batch.save(update_fields=['status', 'delivered_at'])
            now = timezone.now()
            for item in batch.items.select_related('order'):
                o = item.order
                o.status = 'completed'
                o.delivered_at = now
                o.save(update_fields=['status', 'delivered_at'])

        def add_payment(order, suffix):
            """Record a successful, order-linked bKash payment (settlement ledger)."""
            Payment.objects.create(
                user=order.customer, order=order, amount=order.total_paid,
                transaction_id=f"NOB-SEED-{order.id}-{suffix}",
                status='success', gateway='bkash',
                paid_at=timezone.now(), settlement_appended=False,
            )

        # 1) PENDING batch available to deliverymen
        #    Savar Garlic threshold 500kg. Orders total exactly 500 -> batch created, pool reset.
        make_order(c1, p_garlic, 200)
        make_order(c2, p_garlic, 100)
        make_order(c1, p_garlic, 120)
        make_order(c2, p_garlic, 80)   # total 500 >= 500 -> pending Batch at union 3282

        # 2) ASSIGNED batch (deliveryman accepted, pickup in progress)
        #    Savar Carrot threshold 500kg -> batch, then accepted by d1 (left assigned).
        make_order(c1, p_carrot, 150)
        make_order(c2, p_carrot, 150)
        make_order(c1, p_carrot, 200)  # total 500 -> batch
        assigned_batch = Batch.objects.filter(
            area=area_savar, union=union_obj(3282),
            product_type=product_type_map.get("Carrot"), status='pending').first()
        assigned_batch.status = 'assigned'
        assigned_batch.deliveryman = d1
        assigned_batch.assigned_at = timezone.now()
        assigned_batch.save(update_fields=['status', 'deliveryman', 'assigned_at'])

        # 3) DELIVERED batch (completed orders -> eligible for reviews + settlement)
        #    Savar Raw Banana threshold 500kg -> batch, then delivered by d1 (orders completed).
        make_order(c1, p_banana, 180)
        make_order(c2, p_banana, 180)
        make_order(c1, p_banana, 140)  # total 500 -> batch
        delivered_batch = Batch.objects.filter(
            area=area_savar, union=union_obj(3282),
            product_type=product_type_map.get("Raw Banana"), status='pending').first()
        assign_and_deliver(delivered_batch, d1)

        # 4) PENDING batch in a second area (Comilla Nangalkot, Melon threshold 300kg)
        make_order(c2, p_melon, 100)
        make_order(c1, p_melon, 100)
        make_order(c2, p_melon, 100)  # total 300 -> pending Batch for Comilla deliverymen

        # 5) *** NEAR-THRESHOLD UNION (buy here to trigger a batch) ***
        #    Savar Tomato (union 3282, threshold 500kg). Pool sits at 480kg -> below threshold,
        #    so no batch yet. As rahimk (union 3282) you can buy just 20kg+ of this tomato to
        #    push the pool past 500kg and immediately spawn a pending Batch.
        make_order(c1, p_tomato, 250)
        make_order(c2, p_tomato, 230)  # total 480 < 500 -> pool only, NO batch yet

        # 6) Below-threshold pools (fill unions with open stock, no batch)
        #    Savar Eggplant
        make_order(c1, p_eggplant, 100)
        make_order(c2, p_eggplant, 100)      # 200 < 500 -> pool only
        #    Bogura Cucumber / Rice
        make_order(c2, p_cucumber, 180)      # 180 < 500 -> pool only
        make_order(c1, p_rice, 200)          # 200 < 500 -> pool only
        #    Rajshahi Green Chili
        make_order(c2, p_chili, 150)         # 150 < 500 -> pool only
        #    Jashore Onion
        make_order(c1, p_onion, 200)         # 200 < 400 -> pool only
        #    Comilla Cherry / Peach / Zucchini
        make_order(c2, p_cherry, 120)        # 120 < 300 -> pool only
        make_order(c1, p_peach, 60)          # 60 < 300 -> pool only
        make_order(c2, p_zucchini, 150)      # 150 < 300 -> pool only

        # 7) Completed order with successful payment for settlement/BEFTN testing
        o_potato = make_order(c1, p_potato, 200)
        o_potato.status = 'completed'
        o_potato.delivered_at = timezone.now()
        o_potato.save(update_fields=['status', 'delivered_at'])
        add_payment(o_potato, 'POT')
        add_payment(delivered_batch.items.first().order, 'BAN')

        # 8) MULTI-PRODUCT order from chasan: 3 products from 3 different farmers
        #    Pending — ready for bKash payment input
        self.stdout.write("Creating multi-product order for chasan (3 farmers)...")
        from api.models import OrderItem
        with transaction.atomic():
            mp_items = [
                (p_garlic, f1, Decimal('50')),     # Garlic from Jamal (Savar)
                (p_cucumber, f2, Decimal('80')),    # Cucumber from Rahim (Bogura)
                (p_chili, f3, Decimal('10')),       # Chili from Karim (Rajshahi)
            ]
            mp_total = Decimal('0')
            for mp_post, mp_farmer, mp_qty in mp_items:
                mp_total += round(mp_qty * mp_post.price_per_kg, 2)
                mp_post.total_weight_kg -= mp_qty
                mp_post.save(update_fields=['total_weight_kg'])
            mp_fee = round(mp_total * Decimal('0.10'), 2)
            mp_payout = mp_total - mp_fee
            mp_order = Order.objects.create(
                customer=c2, status='pending',
                total_paid=mp_total, platform_fee=mp_fee, farmer_payout=mp_payout,
                delivery_address=c2.address or 'Savar, Dhaka',
                advance_amount=round(mp_total / 2, 2),
                final_amount=mp_total - round(mp_total / 2, 2),
            )
            for mp_post, mp_farmer, mp_qty in mp_items:
                subtotal = round(mp_qty * mp_post.price_per_kg, 2)
                OrderItem.objects.create(
                    order=mp_order, post=mp_post, farmer=mp_farmer,
                    quantity_kg=mp_qty, quantity_type=mp_post.quantity_type,
                    est_weight_kg=mp_post.est_weight_kg,
                    price_per_kg=mp_post.price_per_kg, subtotal=subtotal,
                )
            process_new_order(mp_order)
        self.stdout.write(f"  Multi-product order #{mp_order.id}: Garlic + Cucumber + Chili = {mp_total} BDT (pending)")

        self.stdout.write("Creating reviews for completed orders...")
        Review.objects.create(customer=c1, post=p_potato, rating=5,
                              comment="Excellent Rajshahi potatoes — great value and quality.")
        Review.objects.create(customer=c1, post=p_banana, rating=4,
                              comment="Sweet bananas, delivery on time.")

        # ==========================================
        # JAMAL TOMATO POSTS — completed orders + reviews with images (4 customers)
        # ==========================================
        self.stdout.write("Creating Jamal tomato orders + reviews (4 customers)...")

        def add_completed_tomato_order(customer, post, qty):
            from api.models import OrderItem
            with transaction.atomic():
                qty_dec = Decimal(str(qty))
                total = round(qty_dec * Decimal(str(post.price_per_kg)), 2)
                fee = round(total * Decimal('0.10'), 2)
                payout = total - fee
                advance = round(total / 2, 2)
                final = total - advance
                order = Order.objects.create(
                    customer=customer, status='completed',
                    total_paid=total, platform_fee=fee, farmer_payout=payout,
                    delivery_address=customer.address or 'Dhaka',
                    delivered_at=timezone.now(),
                    advance_amount=advance, final_amount=final,
                    advance_paid=True, final_paid=True,
                    paid_amount=total, paid_at=timezone.now(),
                )
                OrderItem.objects.create(
                    order=order, post=post, farmer=post.farmer,
                    quantity_kg=qty_dec, quantity_type=post.quantity_type,
                    est_weight_kg=post.est_weight_kg,
                    price_per_kg=post.price_per_kg, subtotal=total,
                )
                return order

        def add_tomato_review(customer, post, rating, comment, images):
            review = Review.objects.create(
                customer=customer, post=post, farmer=f1, post_title=post.title,
                rating=rating, comment=comment,
            )
            for img_name in images:
                ReviewImage.objects.create(review=review, image=get_image_file(img_name))
            return review

        # Completed orders so the reviews below are backed by real purchases.
        add_completed_tomato_order(c1, p_tomato_organic, 15)
        add_completed_tomato_order(c2, p_tomato_organic, 20)
        add_completed_tomato_order(c3, p_tomato_deshi, 50)
        add_completed_tomato_order(c4, p_tomato_deshi, 40)

        # 4 customers leave reviews with photos on Jamal's tomato posts.
        add_tomato_review(c1, p_tomato_organic, 5,
                          "Amazing cherry tomatoes — so sweet and fresh. Perfect for our restaurant salads.",
                          ("-tomato-- (15)", "-tomato-- (16)"))
        add_tomato_review(c2, p_tomato_organic, 4,
                          "Very good quality, arrived crisp and well packed. A bit pricey but worth it.",
                          ("-tomato-- (9)",))
        add_tomato_review(c3, p_tomato_deshi, 5,
                          "Best deshi tomatoes I have bought in bulk. Thick flesh, no spoilage.",
                          ("-tomato--number- (65)", "-tomato--number- (69)"))
        add_tomato_review(c4, p_tomato_deshi, 3,
                          "Good tomatoes overall, but a few were overripe this time.",
                          ("-tomato--number- (9)",))

        # Featured web tomato post — 3 customers review with 1, 2 and 3 images.
        add_completed_tomato_order(c1, p_tomato_web, 25)
        add_completed_tomato_order(c2, p_tomato_web, 30)
        add_completed_tomato_order(c3, p_tomato_web, 20)
        add_tomato_review(c1, p_tomato_web, 5,
                          "Perfect tomatoes — sweet, thick, and arrived fresh. Highly recommend.",
                          ("tomato_1.jpeg",))
        add_tomato_review(c2, p_tomato_web, 4,
                          "Great quality and well packed. Loved the ripeness.",
                          ("tomato_1.jpeg", "tomato_2.jpeg"))
        add_tomato_review(c3, p_tomato_web, 5,
                          "Excellent farm-fresh tomatoes. Will order again for our shop.",
                          ("tomato_1.jpeg", "tomato_2.jpeg", "tomato_3.jpeg"))

        # ==========================================
        # SUMMARY
        # ==========================================
        self.stdout.write(self.style.SUCCESS("Comprehensive seed completed successfully!"))
        self.stdout.write(f"  Admin:           admin / mik")
        self.stdout.write(f"  Farmers:         fjamal(F1), frahim(F2), fkarim(F3), fselim(F4), farif(F5)")
        self.stdout.write(f"  Customers:       rahimk(C) [ratul], chasan(C23), cmukta(C3), ctanvir(C4)")
        self.stdout.write(f"  Deliverymen:     dkarim (D1) [Savar Dhaka], drahim (D2) [Comilla]")
        self.stdout.write(f"  Areas:           {Area.objects.count()} created")
        self.stdout.write(f"  Orders:          {Order.objects.count()} total, "
                          f"{Order.objects.filter(status='completed').count()} completed")
        self.stdout.write(f"  Batches:         pending={Batch.objects.filter(status='pending').count()}, "
                          f"assigned={Batch.objects.filter(status='assigned').count()}, "
                          f"delivered={Batch.objects.filter(status='delivered').count()}")
        self.stdout.write(f"  Open pools:      {PendingPool.objects.count()}")
        self.stdout.write(f"  Payments:        {Payment.objects.filter(status='success').count()} successful")
        self.stdout.write(f"  Geo locations:   {BangladeshLocation.objects.count()} nodes")
        near_pool = PendingPool.objects.filter(
            area=area_savar, union=union_obj(3282),
            product_type=product_type_map.get("Tomato")).first()
        if near_pool:
            self.stdout.write(self.style.WARNING(
                f"  >>> NEAR-THRESHOLD: Savar Tomato pool at {near_pool.pending_quantity_kg}kg "
                f"(union 3282, threshold {area_savar.threshold_kg}kg). "
                f"Log in as rahimk and buy ~20kg to exceed & trigger a batch."))