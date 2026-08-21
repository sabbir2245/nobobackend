# New Feature Changes — To-Do List (Items 1–4)

Status: **Backend implemented & tested. Server migrated + restarted.**
Below is exactly what changed and what still needs to be done (mostly frontend/website).

---

## Item 1 — Per-KG vs per-piece product unit (`quantity_type`) ✅ DONE

**Backend (implemented + tested):**
- `Post.quantity_type` (`kg` | `piece`, default `kg`)
- `Post.est_weight_kg` — estimated weight per piece (required when `quantity_type="piece"`)
- `Post.effective_weight_kg` — stock expressed in kg for delivery pooling
- `Order.quantity_type` + `Order.est_weight_kg` — snapshots taken from the post at order time
- `Order.effective_weight_kg` — order qty expressed in kg (pieces × est_weight_kg)
- Delivery pooling/batching (`services.py`) now uses `effective_weight_kg`, so per-piece orders
  still feed the weight-based pool and batches correctly.
- `PostSerializer`: validates that per-piece posts declare a positive `est_weight_kg`.
- Migration `0016` applied on server; gunicorn restarted.

**API changes (see api.md):**
- `POST /posts/` accepts optional `quantity_type` + `est_weight_kg`.
- `POST /orders/` and `orders/bulk_create/` `quantity_kg` is interpreted as **kg** for per-KG
  posts and **pieces** for per-piece posts.
- Post + Order responses include `quantity_type`, `est_weight_kg`, `effective_weight_kg`.

**Frontend (DONE — create-listing screen + api.ts):**
- `services/api.ts`: `Post` interface gains `quantity_type`, `est_weight_kg`,
  `effective_weight_kg`; `createPost` accepts + sends the new fields.
- `app/(farmer)/post.tsx`: added a "Per KG / Per Piece" toggle and an
  "Estimated weight per piece (kg)" input shown only for per-piece; validation added.

**Still to do (frontend, optional polish):**
- Product detail / cart / order screens: show per-piece unit label and price-per-piece instead
  of "per kg" where relevant (e.g. `product/[id].tsx`, `cart.tsx`, order cards).
- `edit-post/[id].tsx` and `updatePost` in `api.ts` should also pass `quantity_type` /
  `est_weight_kg` so farmers can edit the unit.
- Bid amounts: consider labeling per-piece posts as price-per-piece.

---

## Item 2 — Admin farmer-due settlement CHECKBOX UI ✅ backend; UI in Django admin

**Backend (implemented + tested):**
- `Payment.settlement_paid` (Boolean) + `Payment.settlement_paid_at` (DateTime).
- `GET /api/payments/settlement/dues/?unpaid=true` — admin-only list of farmer-due rows,
  one per successful order-linked payment (includes farmer, order, payout_amount,
  settlement_paid status).
- `POST /api/payments/settlement/dues/` — body `{ "payment_id": 123, "paid": true }`
  marks a payout as settled/paid (admin-only).

**Django admin (DONE):**
- `PaymentAdmin` now has `settlement_paid` as a **clickable checkbox** directly in the list
  view (`list_editable`), plus bulk actions "Mark selected as SETTLED" / "Mark selected as NOT
  settled", a new `settlement_paid` filter, and farmer/payout columns.
- A "Download Settlement XLSX (all payments)" button remains on the list page.

**Still to do (only if you build a *custom* web portal outside Django admin):**
- If the client wants their own admin web portal (not Django `/admin/`), point it at the two
  `payments/settlement/dues/` endpoints above and render a checkbox column calling
  `POST .../dues/` with `paid:true|false`.

---

## Item 3 — Real-time delivery notification / handover push ✅ backend; push needs frontend

**Backend (implemented + tested):**
- New `Notification` model (user, notification_type, title, message, batch, order, is_read).
- `services.notify_batch_users(...)` creates notifications for the affected customers, farmers,
  and deliveryman on every batch event.
- Batch actions now fire notifications:
  - `accept` → `batch_assigned`
  - `pick_up` → `batch_picked_up`
  - `in_transit` → `batch_in_transit`
  - `verify_payment` → `payment_verified`
  - `deliver` → `batch_delivered`
- Endpoints (auth required):
  - `GET /api/notifications/`
  - `GET /api/notifications/unread_count/`
  - `POST /api/notifications/<id>/read/`
  - `POST /api/notifications/read_all/`
- `Notification` registered in Django admin.
- Migration `0016` applied; gunicorn restarted.

**Still to do (frontend / infra):**
- App should poll `GET /api/notifications/` (e.g. every 15–30s while a batch is active) and
  show unread count + a notification list/badge on the customer and farmer dashboards.
- For true real-time push, add FCM (firebase-admin on backend + expo-notifications on app) or a
  websocket (e.g. Django Channels + Redis); the backend records are ready to be pushed.
- After reading, call `POST /api/notifications/<id>/read/` or `read_all/`.

---

## Item 4 — Duplicate-registration message wording ✅ DONE (backend only)

- Backend validators now return the requested Bangla wording for duplicate email/phone:
  `Please use a new email/phone number (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন).`
  (Updated in `serializers.py` and `update.py`.)
- **No frontend change required** — the app already renders backend error messages via
  `extractErrorMessage()` in `services/api.ts`.

---

## Migration & deploy notes

- Migration file: `api/migrations/0016_order_est_weight_kg_order_quantity_type_and_more.py`
- Applied on server (`ssh s@200.234.36.38 "cd ~/codes/nobobackend && .venv/bin/python manage.py migrate"`).
- gunicorn restarted, `/api/` returns HTTP 200.
- Tests: 39 passing (existing suite + `api/test_new_features.py` — 12 new tests).

## Summary of remaining work (frontend/website only)

| Item | Backend | Frontend / Website |
|------|---------|--------------------|
| 1. Per-KG vs per-piece | ✅ done | create-listing done; product/cart/edit-post polish pending |
| 2. Settlement checkbox | ✅ done (+ Django admin UI) | custom portal optional |
| 3. Delivery push | ✅ polling endpoints done | app polling UI + optional FCM/websocket pending |
| 4. Bangla duplicate message | ✅ done | none needed |