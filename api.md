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
| `farmer` | create posts, view wallet |
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
- `location`: a **Union or Upazila** id (from the Locations endpoint). Required.
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

Response item:
```json
{
  "id": 4539, "geo_id": 26, "name_en": "Dhaka", "name_bn": "ঢাকা",
  "level": "district", "parent": 3, "latitude": 23.81, "longitude": 90.41
}
```
Use the `id` as the `location` field when registering / creating posts.

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
uploaded_images (up to 3 files)
```
Response includes:
```json
{
  "id": 1, "title": "Fresh Carrots", "description": "...",
  "total_weight_kg": "100.00", "price_per_kg": "50.00",
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

### `POST orders/`
**Customer only.** Body:
```json
{ "post": 1, "quantity_kg": "10.00", "delivery_address": "456 Test Ave, Dhaka" }
```
Creates order as `pending`, decrements stock, computes fees (10% platform fee).

### `POST orders/bulk_create/`
**Customer only.** Body:
```json
{ "items": [ { "post": 1, "quantity_kg": "10.00" }, { "post": 2, "quantity_kg": "5.00" } ], "delivery_address": "456 Test Ave" }
```

### `GET orders/`
**Auth required.** Scoped by role: customers see own, farmers see orders on their posts, deliverymen see orders in their batches, admins see all.

### `POST orders/<id>/complete/`
**Customer/admin.** Completes a pending order.

### `POST orders/<id>/cancel/`
**Customer/farmer/admin.** Cancels a pending order, restores stock.

Order object fields (subset):
```json
{
  "id": 1, "customer": 3, "customer_name": "John", "customer_phone": "017...",
  "post": 1, "post_title": "Fresh Carrots", "post_farmer_name": "Rahim", "post_farmer_id": 2,
  "quantity_kg": "10.00", "status": "pending",
  "total_paid": "500.00", "platform_fee": "50.00", "farmer_payout": "450.00",
  "delivery_address": "...", "created_at": "...",
  "bkash_payment_status": null, "paid_amount": null
}
```

---

## Payment — use DEMO PAY for testing (no real money)

### `POST payments/demo/`
**Customer only.** The intended way to test the buy flow — creates the orders
**and** marks them paid/success in one step, skipping the real gateway.
```json
{ "items": [ { "post": 1, "quantity_kg": "60.00" } ], "delivery_address": "456 Test Ave, Dhaka" }
```
Response `201`: array of created (completed-payment) orders.

### Real bKash (production/merchant only)
- `POST payments/bkash/initiate/` — `{ "amount": 500, "order_id": 1 }` → returns `{ bkash_url, transaction_id, payment_id_bkash, ... }`
- `GET payments/bkash/callback/?paymentID=...&status=...` — bKash redirects the browser here
- `GET payments/bkash/status/<transaction_id>/` — check payment status
- `POST payments/bkash/refund/` — refund (admin)

---

## Reviews

### `POST reviews/`
**Customer only.** Body (JSON or multipart for images):
```json
{ "post": 1, "rating": 5, "comment": "Great quality" }
```
`uploaded_images` (up to 3) for multipart. Rules:
- Rating must be 1–5.
- Requires a **completed** order for that post.
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
**Farmer only.** Response:
```json
{
  "pending_payouts": "500.00",
  "total_earnings": "4500.00",
  "total_commission_deductions": "500.00",
  "recent_transactions": [ { order... }, ... ]
}
```

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
| Create order | POST | `orders/` |
| Bulk create | POST | `orders/bulk_create/` |
| **Demo pay** | POST | `payments/demo/` |
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
- **Orders complete** only after a batch is delivered (or the order is completed directly). Reviews require a completed order.
- **403** on payment/role-gated actions usually means the token's role doesn't match the endpoint.
- Production base URL: `https://nobannoapp.online/api/`.
