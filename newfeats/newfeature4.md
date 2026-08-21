# Feature Status Report

Here's the status of each requirement against what's implemented.

## ✅ Done (implemented & working)

| # | Requirement | Status |
|---|-------------|--------|
| 1a | Time Availability numeric field on post creation | `Post.time_availability` (default 0) + farmer `post.tsx` input |
| 2a | Customer initial bid → notifies farmer | `Bid` model, `POST /bids/` |
| 2b | Farmer counter-bid (final price) | counter action + UI |
| 2c | Customer Confirm/Reject counter | accept/reject actions + UI |
| 2d | Confirm → prompt advance payment | escrow advance flow |
| 3a | Advance 50% checkout | `submitEscrowTrx` advance |
| 3e | Admin spreadsheet of farmer dues | `_append_settlement_xlsx` |
| 3b1 | Shipment-stage "Complete your payment" button | customer orders UI |
| 3b2 | Final 50% via same TrxID method | `submitEscrowTrx` final |
| 4a | Batches sorted by proximity | `distance_km` sorting |
| 4b | "Product Picked" pickup confirmation | `pick_up` + delivery dashboard |
| 4d | Shipment Completed | `deliver` |
| 5a | Permanent customer reviews + images | pre-existing Review system |

## ⚠️ Partial / CONFLICTS with spec (built but diverges)

- **3a TrxID cross-check vs SMS** — Spec: verify input TrxID against TrxID extracted from incoming SMS. Implemented: the app just records the manually-entered TrxID and marks the payment success. No SMS ingestion / cross-verification exists. This is the biggest conflict — any TrxID is accepted as paid.
- **3c / 4c "Real-time notification to delivery person"** (handover authorization) — Spec wants a real-time confirmation. Implemented only as a passive status flag (`payment_verified` shown on the delivery dashboard when it refreshes). No FCM/push/websocket layer. Not truly real-time.
- **3b "Farmer Due Settlement list with checkboxes"** — Spec wants an admin UI with tick-boxes to mark dues paid. Implemented only the auto-generated xlsx; no admin checkbox interface exists.

## ❌ Not done

- **1a2 Auto-delete post after time expires** — `time_availability` is stored but no expiry/auto-delete logic runs (the only `is_expired()` in code is for OTPs, not posts).
- **1b Unit selection (per KG vs per piece)** — no unit/quantity-type field anywhere.
- **3a QR code display** — the payment UI mentions "send to the bKash number shown" but there's no QR image (only a text field); placeholder for bKash QR / BanglaQR not present.

## Summary

- 13 fully done
- 3 built-but-conflicting (SMS cross-check, real-time notifications, admin checkbox settlement UI)
- 3 not started (auto-delete expiry, unit selection, QR display)

Suggested starting point: the **SMS TrxID cross-verification** (biggest correctness gap) or the **auto-delete expiry** (simplest).

---

# Post Deletion & Reviews

First confirm whether reviews stay on the farmer profile after a post is deleted. If yes, enable post delete.

## Confirmed: Reviews survive post deletion

From `api/models.py`:
- `Review.post` → `on_delete=SET_NULL` (line 129) — deleting the post only nulls the link, the review row stays.
- `Review.farmer` → `SET_NULL` (kept, line 130) — so it still shows on the farmer profile.
- `post_title` is saved as a snapshot string (line 131), so the farmer profile still shows the product name even after the post is gone.

So enabling delete is safe for reviews.

## Blocker

`Order.post` → `on_delete=CASCADE` (line 100). Deleting a post with any orders would silently delete the orders (and their payments, escrow, batch items, settlement rows). Also `Bid.post` is CASCADE (transient, fine) and `PostImage` CASCADE (fine). Orders have no snapshot fields — they rely entirely on the post FK to show title/farmer/price.

So "enabling post delete" needs one decision:

**Option A — Block deleting posts that have orders (Recommended, safest, minimal):** In the destroy view, if `post.orders.exists()`, return a 400 ("Can't delete — this post has orders"). Otherwise delete. Reviews on posts without orders stay via `SET_NULL`. ~10 lines, no migration.

**Option B — Make orders survive (snapshot):** Change `Order.post` to `SET_NULL` and add `post_title`, `post_price`, farmer snapshot fields + migration + serializer/display changes. More work but lets farmers remove any post.

> **Decision:** Option A vs Option B — choose later.

---

# Per-Piece Products (banana, watermelon) — Plan

Currently everything is kg-only: `Post.total_weight_kg`, `price_per_kg`, `Order.quantity_kg`, and delivery pooling is weight-based (`Area.threshold_kg`, `PendingPool.total_quantity_kg`, `Batch.total_quantity_kg`).

## Backend

1. **Model (`Post`)**: add
   - `quantity_type` = CharField choices `('kg','piece')`, default `'kg'`
   - `piece_count` = PositiveIntegerField (null/blank) — total pieces available
   - `price_per_piece` = DecimalField (null/blank)
2. **`Post.total_price` property**: branch on `quantity_type` → `piece_count * price_per_piece` when piece.
3. **Serializer validation**: if `quantity_type='piece'`, require `piece_count` + `price_per_piece`; if `'kg'`, require kg fields. Reject mixing.
4. **`Order`**: add `quantity_pieces` (Decimal) + branch the order total / escrow 50% amounts on the post's `quantity_type`. Keep `quantity_kg` for kg orders.

## Frontend

5. **Farmer post screen**: add a "Unit" toggle (per KG / per piece); show kg inputs vs piece inputs depending on selection; send `quantity_type` + corresponding fields.
   - If the farmer chooses unit, show another field: **avg kg** (average weight in kg of one product). The farmer inputs this; it's used to calculate `total_weight`.
6. **Product card / order cart**: show the correct unit, quantity picker (kg vs pieces), and compute price per unit.
7. **Order/escrow screens**: display "× N pieces" and correct totals.

## Key conflict — delivery is weight-based

Bananas/watermelons are sold per piece, but the batch/pool system pools orders by weight (500kg threshold). A per-piece order has no weight to add. Options:

- **(i) Treat 1 piece ≈ an estimated kg** (add an optional `est_weight_kg` on the post so piece items still feed the pool/batch). **Recommended** — keeps delivery unchanged.

## Notes

- One migration for the new Post/Order fields. Existing kg posts unaffected (default `quantity_type='kg'`).
- Full test suite run before deploy; push via scp (avoiding the mutagen conflict trap), restart gunicorn.
