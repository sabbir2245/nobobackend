# Nobanno Backend — API Reference for Frontend Developers

Complete guide to the Nobanno API. The backend is a Django REST Framework app
served at **`https://nobannoapp.online/api/`**.

- **Live base URL:** `https://nobannoapp.online/api/`
- **Admin panel:** `https://nobannoapp.online/admin/`
- All endpoints below are **relative to the base URL** (they already include `/api/`).

---

## Authentication

Token-based auth. After login/register you get a `token`; send it on every
authenticated request:

```
Authorization: Token <token>
```

- Tokens are **rotated on every login** — the old token is revoked. Store the newest one.
- On a `401`, re-login to get a fresh token.
- Token TTL: 7 days by default (`TOKEN_TTL_SECONDS`).

---

## Roles

| Role | Can do |
|------|--------|
| `customer` | create orders, demo pay, review, view own orders |
| `farmer` | create posts, view wallet, has bKash number |
| `deliveryman` | set service areas, accept/deliver batches |
| `admin` / staff | manage product types, areas, users, analytics |

---

## Auth endpoints

### Register — `POST auth/register/`
**Public.** Body:
```json
{
  "username": "john",
  "email": "john@test.com",
  "password": "secret123",
  "role": "customer",
  "name": "John",
  "phone_number": "01710000000",
  "address": "Dhaka",
  "location": 4539
}
```
- `role`: `farmer` | `customer` | `deliveryman`
- `location`: a **Union, Upazila, or ward (city corporation area)** id (from the Locations endpoint). Required.
- `bkash_number` (optional): bKash number for farmers (for receiving payouts).
- On a **duplicate email or phone**, the error message is Bangla:
  `Please use a new email/phone number (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন).`
- Response `201`:
```json
{ "token": "...", "user": { "id": 1, "username": "john", "email": "...", "role": "customer", "...": "..." } }
```

### Login — `POST auth/login/`
**Public.** Accepts **email or phone**:
```json
{ "email_or_phone": "john@test.com", "password": "secret123" }
```
Response `200`: `{ "token": "...", "user": {...} }`

### Profile — `GET auth/profile/`
**Auth required.** Returns the logged-in user. Also supports `PATCH` for updates
(`name`, `email`, `phone_number`, `address`, `location`).

### Update profile — `PATCH profile/update/`
**Auth required.** Body: `{ "name", "phone_number", "address", "email", "location" }`
(`location` must be a Union/Upazila id).

### Logout — `POST auth/logout/`
**Auth required.** Deletes the current token.

### Forgot password — `POST auth/forgot-password/`
**Public.** Body:
```json
{ "email": "john@test.com", "method": "email" }
```
`method`: `email` | `sms`. Sends a 6-digit OTP (5 min expiry). Always returns a
generic "If an account exists..." message (doesn't reveal account existence).

### Reset password — `POST auth/reset-password/`
**Public.** Body:
```json
{ "email": "john@test.com", "otp": "123456", "new_password": "newpass123" }
```
`new_password` min length 8. On success, revokes all old tokens.

---

## Locations (cascading dropdowns)

### `GET locations/`
**Public.** Flat list of Bangladeshi admin locations.
Query params: `level` + `parent_id`:
- `GET locations/?level=division`
- `GET locations/?level=district&parent_id=<division_id>`
- `GET locations/?level=upazila&parent_id=<district_id>`
- `GET locations/?level=union&parent_id=<upazila_id>`
- `GET locations/?level=ward&parent_id=<district_id>` — Dhaka city corporation areas (DNCC/DSCC). These are ward-level areas whose `parent` is the **Dhaka district** (not an upazila), so for Dhaka the client should call `ward` directly with the district as parent. Only Dhaka currently has ward-level data.

Response item:
```json
{
  "id": 4539, "geo_id": 26, "name_en": "Dhaka", "name_bn": "ঢাকা",
  "level": "district", "parent": 3, "latitude": 23.81, "longitude": 90.41,
  "city_corp": "DNCC", "ward_no": "12"
}
```
`city_corp` (DNCC/DSCC) and `ward_no` are present for ward-level city corporation areas; empty otherwise.
Use the `id` as the `location` field when registering / creating posts. Registration also accepts a `ward` (city corporation area) id.

---

## Product types

### `GET product-types/`
**Public.** List:
```json
{ "id": 1, "name_en": "Carrot", "name_bn": "গাজর", "max_price_limit": "120.00", "created_at": "..." }
```
`POST product-types/`, `PATCH product-types/<id>/set_max_price/` are admin-only.

---

## Posts

### `GET posts/`
**Public.** List posts, newest first. Filters (query params):
- `search` — title/description contains
- `product_type` — id
- `farmer_id` — id
- `area`, `upazila`, `district` — location filters
- `union` — **your union id** → adds `distance_km` (approx km from district centroid). Not a hard filter.

### `GET posts/search_by_keyword/?q=<text>&union=<union_id>`
**Public.** Keyword search with distance.

### `GET posts/<id>/`
**Public.** Single post.

### `POST posts/`
**Farmer only.** `multipart/form-data` (use FormData when uploading images):
```
title, description, total_weight_kg, price_per_kg, location, product_type(optional)
quantity_type (optional: "kg" | "piece", default "kg")
est_weight_kg (required only when quantity_type="piece")
uploaded_images (up to 3 files)
```
- **Per-KG** (`quantity_type="kg"`, default): `total_weight_kg` = stock in kg, `price_per_kg` = price per kg.
- **Per-PIECE** (`quantity_type="piece"`): `total_weight_kg` = stock in pieces, `price_per_kg` = price per piece,
  and `est_weight_kg` (estimated weight per piece) is **required** so the weight-based delivery pooling still works.
- Response also includes `effective_weight_kg` (stock expressed in kg for delivery pooling).
Response includes:
```json
{
  "id": 1, "title": "Fresh Carrots", "description": "...",
  "total_weight_kg": "100.00", "price_per_kg": "50.00",
  "quantity_type": "kg", "est_weight_kg": null, "effective_weight_kg": "100.00",
  "total_price": 5000.0, "farmer": 2, "farmer_name": "Rahim",
  "farmer_phone": "017...", "farmer_avg_rating": 4.5,
  "product_type": 1, "product_type_name_bn": "গাজর",
  "images": [ { "id": 1, "image": "https://...", "created_at": "..." } ],
  "location": { "id": 4539, "level": "union", "name_en": "...", "division": "...", "district": "...", "upazila": "...", "union": "..." },
  "distance_km": 12.34, "created_at": "..."
}
```
> Note: `farmer_phone` is `null` for unauthenticated users. `collection_point_address` is hidden for unauthenticated users.

### `PATCH posts/<id>/update/`
**Owner only.** Accepts JSON or multipart (for images). Also `GET`/`DELETE posts/<id>/` (owner).

---

## Orders

Orders now support **multiple products from multiple farmers** via nested
`OrderItem` objects. Both `POST orders/` and `POST orders/bulk_create/` create
a **single Order** with one or more `OrderItem` rows.

### `POST orders/`
**Customer only.** Body:
```json
{ "items": [ { "post": 1, "quantity_kg": "10.00" } ], "delivery_address": "456 Test Ave, Dhaka" }
```
Creates one Order + one OrderItem. `quantity_kg` is interpreted as **kg** for
per-KG posts and **pieces** for per-piece posts.

### `POST orders/bulk_create/`
**Customer only.** Body:
```json
{
  "items": [
    { "post": 1, "quantity_kg": "10.00" },
    { "post": 2, "quantity_kg": "5.00" }
  ],
  "delivery_address": "456 Test Ave"
}
```
Creates one Order + N OrderItems. Stock is decremented for each post. Fees are
computed per-item: subtotal = quantity × price_per_kg, then platform fee (10%)
and farmer payout (90%) are summed at the order level.

### `GET orders/`
**Auth required.** Scoped by role: customers see own, farmers see orders
containing their items, deliverymen see orders in their batches, admins see all.
Farmer query uses `items__farmer` with `.distinct()`.

### `POST orders/<id>/complete/`
**Customer/admin.** Completes a pending order.

### `POST orders/<id>/cancel/`
**Customer/farmer/admin.** Cancels a pending order, restores stock per item.

### `DELETE orders/<id>/`
**Owner/customer.** Deletes a pending order and restores stock per item.

Order object (full shape):
```json
{
  "id": 1,
  "customer": 3, "customer_name": "John", "customer_phone": "017...",
  "status": "pending",
  "total_paid": "500.00", "platform_fee": "50.00", "farmer_payout": "450.00",
  "advance_paid": false, "final_paid": false,
  "delivery_address": "...", "created_at": "...",

  "items": [
    {
      "id": 1, "order": 1, "post": 1, "farmer": 2,
      "post_title": "Fresh Carrots", "post_image_url": "https://...",
      "farmer_name": "Rahim", "farmer_phone": "017...",
      "quantity_kg": "10.00", "quantity_type": "kg", "est_weight_kg": null,
      "price_per_kg": "50.00", "subtotal": "500.00"
    }
  ],

  "post": 1,
  "post_title": "Fresh Carrots",
  "post_farmer_name": "Rahim", "post_farmer_id": 2, "post_farmer_phone": "017...",
  "quantity_kg": "10.00", "quantity_type": "kg", "est_weight_kg": null,
  "bkash_payment_status": null, "paid_amount": null
}
```
The top-level `post`, `post_title`, `post_farmer_name`, `quantity_kg`, etc. are
**legacy convenience fields** derived from the first OrderItem for backward
compat. Use `items[]` for the full breakdown.

---

## Payment — use DEMO PAY for testing (no real money)

### `POST payments/demo/`
**Customer only.** The intended way to test the buy flow — creates the orders
**and** marks them paid/success in one step, skipping the real gateway.
```json
{ "items": [ { "post": 1, "quantity_kg": "60.00" } ], "delivery_address": "456 Test Ave, Dhaka" }
```
Response `201`: the created Order object (single, with `items[]` array).

### Real bKash (production/merchant only)
- `POST payments/bkash/initiate/` — `{ "amount": 500, "order_id": 1 }` → returns `{ bkash_url, transaction_id, payment_id_bkash, ... }`
- `GET payments/bkash/callback/?paymentID=...&status=...` — bKash redirects the browser here
- `GET payments/bkash/status/<transaction_id>/` — check payment status
- `POST payments/bkash/refund/` — refund (admin)

### Manual bKash Send Money (admin-verified)
Customer sends money via bKash Send Money to a platform number, submits the
trx ID + sender number. Admin reviews and approves in the admin panel.

#### `POST payments/manual-bkash/submit/`
**Customer only.** Submit a manual bKash payment for admin verification.
```json
{
  "order_id": 1,
  "payment_type": "advance",
  "trx_id": "9A8B7C6D5E",
  "sender_number": "01710000000"
}
```
- `payment_type`: `"advance"` (50%) or `"final"` (50%)
- `sender_number`: the bKash number the money was sent FROM
- `amount` (optional, admin only): override the auto-calculated amount
- Response `201`: `{ submission_id, order_id, payment_type, amount, trx_id, sender_number, status: "pending" }`
- Duplicate check is per **(trx_id, order_id, payment_type)** — same trx_id can be used for different orders or different payment types.

#### `GET payments/manual-bkash/list/`
**Admin only.** List all manual bKash submissions.
Query param: `?status=pending|approved|rejected`
Response: array of submission objects.

#### `POST payments/manual-bkash/<id>/approve/`
**Admin only.** Approve a pending submission. Creates a Payment record, links
to the order, updates order payment flags, appends settlement XLSX.
The Payment.transaction_id is stored as `MANUAL-{trx_id}-O{order_id}`.
```json
{ "note": "Verified on bKash portal" }
```
Response: `{ id, status: "approved", payment_id, order_id }`

#### `POST payments/manual-bkash/<id>/reject/`
**Admin only.** Reject a pending submission.
```json
{ "note": "Trx ID not found" }
```
Response: `{ id, status: "rejected" }`

---

## Reviews

### `POST reviews/`
**Customer only.** Body (JSON or multipart for images):
```json
{ "post": 1, "rating": 5, "comment": "Great quality" }
```
`uploaded_images` (up to 3) for multipart. Rules:
- Rating must be 1–5.
- Requires a **completed** order containing an `OrderItem` for that post (checked via `OrderItem`).
- **Duplicate reviews blocked** (one per customer per post) → `400` `{ "non_field_errors": "You have already reviewed this product." }`

### `GET reviews/`
**Public.** Query params: `?post_id=`, `?farmer_id=`, `?customer_id=`.

Review object:
```json
{
  "id": 1, "post": 1, "customer": 3, "rating": 5, "comment": "...",
  "customer_username": "john", "customer_name": "John",
  "post_title": "Fresh Carrots", "farmer_username": "rahim", "farmer_id": 2,
  "images": [ { "id": 1, "image": "https://...", "image_url": "https://..." } ],
  "created_at": "..."
}
```

---

## Farmer wallet

### `GET farmer/wallet/`
**Farmer only.** Queries via `OrderItem.farmer`. Response:
```json
{
  "pending_payouts": "500.00",
  "total_earnings": "4500.00",
  "total_commission_deductions": "500.00",
  "recent_transactions": [ { order... }, ... ]
}
```
- `pending_payouts`: sum of `OrderItem.subtotal` for orders with status `pending`/`approved`, advance paid but final not yet paid.
- `total_earnings`: sum of `OrderItem.subtotal` for all orders (all statuses).

---

## Delivery system

### Areas — `GET areas/`
**Public.** Admin manages (create/update/delete). Item:
```json
{ "id": 1, "name": "Dhaka North", "upazilas": [1,2,3], "threshold_kg": "50.00", "is_active": true }
```

### Service areas — `GET/POST deliveryman/service-areas/`
**Deliveryman only.**
- `GET` → `{ "service_areas": [1, 2, 3] }`
- `POST` body: `{ "service_areas": [1, 2, 3] }` → `{ "status": "ok", "service_areas": [...] }`

### Batches
- `GET batches/` — scoped by role (admin/farmer/deliveryman)
- `GET batches/available/` — **deliveryman**: pending batches in their service areas
- `GET batches/mine/` — **deliveryman**: batches assigned to them
- `POST batches/<id>/accept/` — **deliveryman**: claim a pending batch
- `POST batches/<id>/deliver/` — **deliveryman**: mark delivered (completes all member orders)

Batch object:
```json
{
  "id": 1, "status": "pending",
  "area": { "id": 1, "name": "Dhaka North", "upazilas": [1,2], "threshold_kg": "50.00", "is_active": true },
  "union": { "id": 4539, "level": "union", "name_en": "...", ... },
  "product_type": 1, "product_type_name_en": "Carrot", "product_type_name_bn": "গাজর",
  "total_quantity_kg": "100.00", "total_value": "5000.00",
  "deliveryman": 5, "deliveryman_name": "Karim", "deliveryman_phone": "018...",
  "items": [ { "id": 1, "order": 1, "post_title": "...", "quantity_kg": "10.00", "farmer": 2, "farmer_name": "...", "farmer_phone": "...", "order_status": "pending", "collection_point_address": "..." } ],
  "created_at": "...", "assigned_at": null, "delivered_at": null
}
```

---

## Notifications (real-time delivery updates)

Backend stores delivery handover notifications that the app polls for real-time
updates. A future FCM/websocket layer can push the same records to devices.

### `GET notifications/`
**Auth required.** Returns the logged-in user's notifications, newest first.
Created automatically on batch events: `batch_assigned`, `batch_picked_up`,
`batch_in_transit`, `payment_verified`, `batch_delivered`.

### `GET notifications/unread_count/`
**Auth required.** → `{ "unread_count": 3 }`

### `POST notifications/<id>/read/`
**Auth required.** Marks one notification read.

### `POST notifications/read_all/`
**Auth required.** Marks all the user's notifications read → `{ "status": "ok" }`.

Notification object:
```json
{
  "id": 1, "notification_type": "batch_delivered",
  "title": "Batch #12 delivered",
  "message": "Your order has been delivered...",
  "batch_id": 12, "order_id": 34, "is_read": false,
  "created_at": "..."
}
```

---

## Farmer-due settlement (admin checkbox)

The settlement XLSX + CORPnet BEFTN export exist; this is the **backend** that the
website admin portal's tick-box interface calls to mark a farmer's payout as paid.
Dues are now computed per-OrderItem (one row per farmer per order).

### `GET payments/settlement/dues/?unpaid=true`
**Admin only.** Lists farmer-due settlement rows, one per OrderItem per order.
`unpaid=true` (default) returns only rows whose farmer payout is **not**
yet marked paid. Row includes `farmer_id`, `farmer_name`, `order_id`,
`payout_amount` (OrderItem.subtotal), `settlement_appended`, `settlement_paid`,
`settlement_paid_at`.

### `POST payments/settlement/dues/`
**Admin only.** Mark a payment's farmer payout as settled/paid (or unmark it).
Body: `{ "payment_id": 123, "paid": true }`. Returns the updated row.

---

## Admin analytics

### `GET admin/analytics/`
**Admin only.** Response:
```json
{
  "metrics": { "total_gmv": "...", "completed_gmv": "...", "realized_profit": "...", "pending_profit": "..." },
  "user_stats": { "active_users": 5, "farmers": 2, "customers": 3 },
  "hotspots": [ { "type": "post", "id": 1, "label": "...", "lat": 23.8, "lng": 90.4, "owner": "...", "location": "..." } ]
}
```

---

## Quick reference

| Purpose | Method | Endpoint |
|---------|--------|----------|
| Register | POST | `auth/register/` |
| Login | POST | `auth/login/` |
| Profile | GET/PATCH | `auth/profile/` |
| Update profile | PATCH | `profile/update/` |
| Logout | POST | `auth/logout/` |
| Forgot password | POST | `auth/forgot-password/` |
| Reset password | POST | `auth/reset-password/` |
| Locations | GET | `locations/?level=...` |
| Product types | GET | `product-types/` |
| List posts | GET | `posts/` |
| Create post | POST | `posts/` |
| Search posts | GET | `posts/search_by_keyword/?q=...&union=...` |
| My notifications | GET | `notifications/` |
| Unread count | GET | `notifications/unread_count/` |
| Mark notif read | POST | `notifications/<id>/read/` |
| Mark all read | POST | `notifications/read_all/` |
| Settlement dues | GET | `payments/settlement/dues/` |
| Mark due paid | POST | `payments/settlement/dues/` |
| Create order | POST | `orders/` (items[]) |
| Bulk create | POST | `orders/bulk_create/` (items[]) |
| **Demo pay** | POST | `payments/demo/` |
| Manual bKash submit | POST | `payments/manual-bkash/submit/` |
| Manual bKash list | GET | `payments/manual-bkash/list/` |
| Manual bKash approve | POST | `payments/manual-bkash/<id>/approve/` |
| Manual bKash reject | POST | `payments/manual-bkash/<id>/reject/` |
| Review | POST | `reviews/` |
| Farmer wallet | GET | `farmer/wallet/` |
| Areas | GET | `areas/` |
| Service areas | GET/POST | `deliveryman/service-areas/` |
| Batches available | GET | `batches/available/` |
| My batches | GET | `batches/mine/` |
| Accept batch | POST | `batches/<id>/accept/` |
| Deliver batch | POST | `batches/<id>/deliver/` |
| Admin analytics | GET | `admin/analytics/` |

---

## Handy notes

- **Auth header:** `Authorization: Token <token>`.
- **Re-login on 401** — tokens rotate on every login.
- **Images:** send via `multipart/form-data` (FormData) with field `uploaded_images` (max 3). In React Native: `formData.append('uploaded_images', { uri, name, type })`.
- **Money/quantity are strings** (decimal) in responses — parse with `Number()` / `parseFloat`.
- **Orders are multi-product.** Each order has an `items[]` array. Use `items` for per-product details; the top-level legacy fields (`post_title`, `quantity_kg`, etc.) reflect the first item only.
- **Orders complete** only after a batch is delivered (or the order is completed directly). Reviews require a completed order with an `OrderItem` for that post.
- **403** on payment/role-gated actions usually means the token's role doesn't match the endpoint.
- Production base URL: `https://nobannoapp.online/api/`.
