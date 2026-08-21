# new5 — Changes Summary

## 1. Signup error messages now show detailed debug info

**Problem:** Signup failures returned a generic "Request failed (400)" popup with no useful detail.

**Fix (frontend):**
- `services/api.ts` — `request()` now uses `extractErrorMessage()` for all error responses instead of only checking `error` / `non_field_errors` keys
- `extractErrorMessage()` improved to parse DRF field-level validation errors and map field names to Bengali labels (e.g. `ইমেইল: ...`, `ফোন নম্বর: ...`)
- `app/auth/register.tsx` — already displayed `err.message`, now gets the detailed string

**Fix (backend):**
- `api/views.py` — `RegisterView.create()` now wraps `serializer.save()` in try/except, logs tracebacks to server console, and returns a 400 with debug info on unexpected DB errors

---

## 2. One cart = one order card (bulk orders grouped)

**Problem:** Adding 2 items to the cart and placing the order showed 2 separate order cards in the customer Orders page.

**Fix:**
- `app/(customer)/orders.tsx` — orders created within 2 seconds of each other are grouped into a single card. The card shows:
  - A range header (e.g. "Orders #5–6")
  - Each item listed with title, quantity, and price
  - Combined total
  - Per-item TRX ID input fields (with item label when multi)
  - Single review button per item

---

## 3. Location permission page now has a Skip button

**Problem:** The "Enable Location" screen on first launch forced users to grant GPS permission with no way to skip.

**Fix:**
- `app/index.tsx` — added a "Skip" button below "Allow Location Access" that navigates directly to `/auth/login`

---

## 4. Admin bKash info available in customer My Account page

**Problem:** After delivery, customers had to pay the final 50% but had no way to see the admin's bKash number without going back to checkout.

**Fix:**
- `app/(customer)/account.tsx` — added a "Show Admin bKash" button that opens a modal displaying:
  - QR code placeholder
  - bKash number (`01570237742`) with copy-to-clipboard
  - Instructions to send money and enter TrxID in the Orders page
- Code pattern copied from `app/(customer)/payment.tsx` checkout page

---

## 5. Farmer bKash number required at signup + editable in profile

**Problem:** Admin had no way to know which bKash number to send farmer payments to.

**Fix (backend):**
- `api/models.py` — added `bkash_number` field to User model
- `api/migrations/0020_user_bkash_number.py` — migration for the new field
- `api/serializers.py` — `RegisterSerializer` now requires `bkash_number` for farmers via `validate()`. `UserSerializer` includes `bkash_number` in fields

**Fix (frontend):**
- `services/api.ts` — `User` type includes `bkash_number`, `register()` accepts it
- `contexts/AuthContext.tsx` — `register()` passes `bkash_number` through
- `app/auth/register.tsx` — bKash number input shown when role is "farmer", validated as required
- `app/(farmer)/account.tsx` — bKash number section with inline edit + save button

---

## 6. Admin Farmer Dues page

**Problem:** Admin needed a clear view of which farmers are owed money and how much, with a way to mark as paid.

**Fix:**
- `api/templates/admin/farmer_due.html` — new admin page showing:
  - Table of farmers with pending dues
  - Columns: Farmer name, Username, bKash Number, Pending Amount (90% of customer paid), Paid status
  - "Mark Paid" button per farmer (sets `settlement_paid=True` on all their unpaid payments)
  - Total pending amount footer
- `api/admin.py` — `farmer_due_view` (GET) aggregates farmer_payout from completed orders where settlement_paid=False. `farmer_due_mark_view` (POST) marks payments as settled
- `nobanno/settings.py` — "Farmer Dues" link added to admin top menu

**Amount calculation:** Pending amount = SUM of `farmer_payout` for each farmer's completed orders where the payment's `settlement_paid` is False. `farmer_payout` = 90% of `total_paid` (platform keeps 10%).

---

## Files changed

| File | Change |
|------|--------|
| `nobobackend/api/models.py` | Added `bkash_number` field to User |
| `nobobackend/api/migrations/0020_user_bkash_number.py` | Migration for bkash_number |
| `nobobackend/api/serializers.py` | RegisterSerializer requires bkash_number for farmers, UserSerializer includes it |
| `nobobackend/api/views.py` | RegisterView error logging |
| `nobobackend/api/admin.py` | Farmer due view + mark paid view |
| `nobobackend/api/templates/admin/farmer_due.html` | Admin farmer dues page template |
| `nobobackend/nobanno/settings.py` | Farmer Dues link in admin nav |
| `frontend/services/api.ts` | extractErrorMessage improved, bkash_number in User type + register |
| `frontend/contexts/AuthContext.tsx` | register() passes bkash_number |
| `frontend/app/auth/register.tsx` | bKash input for farmers, validation |
| `frontend/app/(farmer)/account.tsx` | bKash number edit section |
| `frontend/app/(customer)/orders.tsx` | Order grouping by timestamp |
| `frontend/app/index.tsx` | Skip button on location page |
| `frontend/app/(customer)/account.tsx` | Admin bKash modal |
