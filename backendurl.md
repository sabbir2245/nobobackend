# Backend URL & Integration Info for Frontend

This file is for the frontend AI/team. It documents how to reach the Nobanno
backend, auth, and the full API surface.

---

## Backend Base URL

| Environment | Base URL |
|-------------|----------|
| Local dev    | `http://localhost:8000/api/` |
| Production   | `https://yourdomain.com/api/` (replace with the real domain) |

- **Admin panel:** `http://localhost:8000/admin/`
- **API browser (browsable API):** `http://localhost:8000/api/`

> All endpoints below are relative to the base URL (they already include `/api/`).

---

## Authentication

Token-based. Register/login returns a token; send it on every request:

```
Authorization: Token <token>
```

### Register — `POST auth/register/`
```json
{
  "username": "john",
  "email": "john@test.com",
  "password": "secret123",
  "role": "customer",        // farmer | customer | deliveryman
  "name": "John",
  "phone_number": "01710000000",
  "location": 4539           // Union/Upazila id (see Locations below)
}
```
Response: `{ "token": "...", "user": {...} }`

### Login — `POST auth/login/`
```json
{ "email_or_phone": "john@test.com", "password": "secret123" }
```
> Login accepts email **or** phone. Login **rotates the token** — the previous
> token is revoked. Store the newest token after each login.

### Profile — `GET auth/profile/`
Returns the logged-in user. Also supports PATCH for updates.

### Logout — `POST auth/logout/`
Deletes the current token. `Authorization` header required.

---

## Roles & permissions

| Role | Can do |
|------|--------|
| `customer` | create orders, demo pay, review, view own orders |
| `farmer` | create posts, view wallet |
| `deliveryman` | set service areas, accept/deliver batches |
| `admin` / staff | product types, areas, analytics, manage users |

---

## Main endpoints

### Locations (cascading dropdowns)
- `GET locations/?level=division`
- `GET locations/?level=district&parent_id=<division_id>`
- `GET locations/?level=upazila&parent_id=<district_id>`
- `GET locations/?level=union&parent_id=<upazila_id>`
- Response is flat; use `id` as the `location` field when registering/creating posts.

### Product types (admin)
- `GET product-types/` — public list
- `POST product-types/` — admin only (`{ "name_en": "...", "name_bn": "..." }`)

### Posts
- `GET posts/` — list, filters: `?search=`, `?product_type=`, `?farmer_id=`, `?area=`, `?upazila=`, `?district=`, `?union=<customer_union_id>` (adds `distance_km`)
- `POST posts/` — farmer only; body includes `location` (union/upazila id)
- `GET posts/<id>/`

### Areas (admin)
- `GET areas/` — public list
- `POST areas/` — admin only

### Orders
- `POST orders/` — customer only `{ "post": <id>, "quantity_kg": "10.00", "delivery_address": "..." }`
- `POST orders/bulk_create/` — customer only
  ```json
  { "items": [{ "post": 1, "quantity_kg": "10.00" }, ...], "delivery_address": "..." }
  ```
- `GET orders/` — filtered by role (customers see own, farmers see own posts' orders)
- `POST orders/<id>/complete/`, `POST orders/<id>/cancel/`

### Batches (delivery)
- `GET batches/` — admin/farmer/deliveryman scoped
- `GET batches/available/` — deliveryman (pending batches in their service areas)
- `POST batches/<id>/accept/`, `POST batches/<id>/deliver/` — deliveryman

### Deliveryman service areas
- `GET deliveryman/service-areas/`
- `POST deliveryman/service-areas/` — `{ "service_areas": [<area_id>] }`

---

## ⭐ Payment — use DEMO PAY to bypass bKash (no real money)

For frontend testing, **never call the real bKash flow** — use demo pay:

```
POST payments/demo/
Authorization: Token <customer_token>
```
```json
{
  "items": [
    { "post": 1, "quantity_kg": "60.00" },
    { "post": 2, "quantity_kg": "50.00" }
  ],
  "delivery_address": "456 Test Ave, Dhaka"
}
```
**Demo pay creates the orders AND marks them paid (success) in one step.** It
returns the created orders (`201`). This is the intended way to test the full
buy flow without touching the payment gateway.

### Real bKash (only for production/merchant testing)
- `POST payments/bkash/initiate/` — returns `bkash_url` for redirect
- `GET payments/bkash/callback/?paymentID=...&status=...` — bKash redirects here
- `GET payments/bkash/status/<transaction_id>/` — check status
- `POST payments/bkash/refund/` — refund

---

## Dashboards

- `GET farmer/wallet/` — farmer earnings, pending payouts, recent orders
- `GET admin/analytics/` — admin metrics (GMV, profit, user counts)

## Reviews

- `POST reviews/` — customer only; **requires a completed order** for that post.
  Rating 1–5, duplicate review blocked.
- `GET reviews/?farmer_id=`, `?post_id=`, `?customer_id=`

---

## Quick reference

| Purpose            | Method | Endpoint |
|--------------------|--------|----------|
| Register           | POST   | `auth/register/` |
| Login              | POST   | `auth/login/` |
| Profile            | GET    | `auth/profile/` |
| Logout             | POST   | `auth/logout/` |
| Locations          | GET    | `locations/?level=...` |
| Create post        | POST   | `posts/` |
| List posts         | GET    | `posts/` |
| Create order       | POST   | `orders/` |
| **Demo pay**       | POST   | `payments/demo/` |
| Create area        | POST   | `areas/` |
| Batches available  | GET    | `batches/available/` |
| Farmer wallet      | GET    | `farmer/wallet/` |
| Admin analytics    | GET    | `admin/analytics/` |

---

## Handy notes for the frontend team

- Auth header format: `Authorization: Token <token>`.
- Re-login whenever a 401 happens — tokens are rotated on every login.
- Orders are only `completed` after a batch is delivered (or the order is
  completed directly). Reviews require a completed order.
- In production, replace `http://localhost:8000/api/` with the live HTTPS base URL.