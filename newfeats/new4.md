# Backend Progress & Outstanding Items

Current state of the Nobanno backend against the client requirements.

## Models (api/models.py — 18)

ProductType, User (roles), Post, PostImage, Order, Review, ReviewImage, Bid, OTP,
Payment, FarmerBankAccount, BangladeshLocation, Area, PendingPool, Batch, BatchItem,
Notification.

Key fields:
- Post: time_availability (hours), is_visible (soft-delete), expires_at / is_expired(),
  quantity_type (kg/piece), est_weight_kg, effective_weight_kg
- Order: escrow advance_amount / final_amount / advance_paid / final_paid, bKash fields,
  quantity_type + est_weight_kg snapshots, effective_weight_kg
- Review: post (SET_NULL), farmer (SET_NULL), post_title snapshot → reviews survive post deletion
- Bid: full negotiation (pending / counter_offered / accepted / rejected)
- Payment: gateways sslcommerz | bkash | uddoktapay, payment_type advance/final,
  uddokta_invoice_id / sender_number, settlement_appended, settlement_paid (+settlement_paid_at)
- Delivery: Area, PendingPool, Batch, BatchItem (weight-based pooling + batching)
- Notification: delivery/handover events (batch_assigned/picked_up/in_transit/
  payment_verified/delivered) for polling / future FCM push

## Views (api/views.py — 21 classes)

Auth (Register/Login/Logout/Profile), UserManagement, ProductType, Post (soft-delete +
visibility filter), Order (bulk_create, complete, cancel), Review, Bid (counter/accept/reject),
FarmerProfile, FarmerWallet, AdminAnalytics, BangladeshLocation, AssignServiceArea, Area,
Batch (available/mine/accept/pick_up/in_transit/verify_payment/deliver), DemoPay,
Notification (list/unread_count/read/read_all), SettlementDue (list/mark-paid).

## Payments

- api/payments.py: bKash Tokenized (initiate/callback/status/refund) + escrow manual TrxID
  (BKashEscrowTrxView) + settlement xlsx (_append_settlement_xlsx, _rebuild_settlement_xlsx,
  CORPnet BEFTN export)
- api/uddoktapay.py (new): create-charge, verify, _finalize_uddoktapay_payment (reuses xlsx)
- api/uddoktapay_views.py (new): Checkout, Webhook (auto-verifies TrxID), Verify, Redirect

## Migration

0016 applied on server: Post/Order quantity_type + est_weight_kg, Payment.settlement_paid,
Notification model.

## Tests (server, all green)

39 tests OK: existing suite (27) + api/test_new_features.py (12) covering per-piece units,
settlement due/paid, notifications, Bangla duplicate-registration wording.

## Live on server

Migrated (0016), gunicorn restarted, routes verified (/api/notifications/ and
/api/payments/settlement/dues/ → 401 without auth, as expected).
Sandbox key added to .env (live checkout-v2 currently blocked by UddoktaPay's own 502 outage).

---

## Against the client requirements

### Implemented & working
- Time availability field on posts
- Full bidding flow (customer bid → farmer counter → customer confirm/reject)
- Advance 50% + final 50% escrow
- UddoktaPay auto-verification (resolves the old TrxID / SMS cross-check gap)
- Farmer-dues settlement xlsx + CORPnet BEFTN export
- Batch proximity sorting (distance_km)
- Full delivery lifecycle (pickup → in-transit → payment-verified → delivered)
- Reviews on farmer profile (survive post deletion)
- Post soft-delete + expire_posts command
- Per-KG vs per-piece product unit (Post/Order quantity_type, est_weight_kg,
  effective_weight_kg — pooling stays weight-based)
- Settlement CHECKBOX backend (Payment.settlement_paid + GET/POST /payments/settlement/dues/)
- Delivery notifications backend (Notification model + /notifications/ endpoints fired on
  every batch handover event)
- Duplicate-registration message now Bangla (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন)

### Not started / divergent
1. ~~Per-KG vs per-piece product unit~~ — **DONE** (backend).
2. Admin farmer-due settlement CHECKBOX **website UI** — backend API done
   (list dues + mark paid); the actual tick-box web page is a **website/frontend** task.
3. Real-time delivery notification **push (FCM / websocket)** — backend stores + polling
   endpoint done; pushing to devices is a separate frontend/infra effort.
4. ~~Duplicate-registration message wording~~ — **DONE** (Bangla).
5. Post expiry behavior — **SOFT-DELETE CONFIRMED**: posts are hidden (`is_visible=false`)
   rather than hard-deleted, keeping orders/reviews intact.

---

## Recommended order
1. Per-piece units (backend: Post/Order quantity_type, est_weight_kg) — **DONE**
2. Admin checkbox settlement **UI** (website/frontend) — backend ready, build the page
3. Duplicate-registration Bangla message wording — **DONE**
4. Real-time delivery push — backend polling ready; wire FCM/websocket on the frontend
