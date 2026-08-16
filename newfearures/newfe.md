# Feature Plan: Farmer Profile page + Reviews survive post deletion

## Goal
1. When a customer clicks a post, the farmer's name is clickable and opens a new
   page showing: farmer name, farmer location, and the farmer's previous reviews.
2. Even if a post is deleted, its reviews stay connected to the farmer (so the
   farmer's profile still shows them).

---

## A. Backend — keep reviews linked to the farmer even if the post is deleted

Currently reviews attach to the farmer only indirectly:
`Review.post` -> `Post.farmer` (`api/models.py`). When a post is deleted (`CASCADE`)
the review is destroyed too.

### 1. `api/models.py` — `Review`
- `post` FK: `on_delete=models.CASCADE` -> `on_delete=models.SET_NULL, null=True, blank=True`
- Add: `farmer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
  blank=True, related_name='reviews', limit_choices_to={'role': 'farmer'})`
- Add snapshot: `post_title = models.CharField(max_length=255, blank=True, default='')`
- Keep `unique_together = ('customer', 'post')` (Postgres treats NULLs as distinct,
  so a customer can still review once per post).

### 2. Migration + data backfill
- `python manage.py makemigrations` for the schema change.
- Add a `RunPython` data migration to backfill existing rows:
  `Review.farmer = review.post.farmer`, `Review.post_title = review.post.title`.

### 3. `api/signals.py` — `update_farmer_rating_stats`
- Read `instance.farmer` instead of `instance.post.farmer`.
- Guard/skip when `farmer` is `None`.

### 4. `api/serializers.py` — `ReviewSerializer`
- `post_title`: fall back to the `post_title` snapshot when `post` is `None`.
- `farmer_username` / `farmer_id`: read from the new `farmer` FK (guard `None`).
- Populate `farmer` on create.

### 5. `api/views.py` — `ReviewViewSet.list`
- `farmer_id` filter: change `post__farmer_id` -> direct `farmer_id`.

### 6. New public Farmer Profile endpoint
- `GET farmers/<id>/` returning farmer `name`, `username`, `location`
  (division/district/upazila/union from `User.location`), `avg_rating`,
  `ratings_count`, `is_verified`.
- Register in `api/urls.py`.

---

## B. Frontend — clickable farmer name -> farmer profile page

### 1. `app/product/[id].tsx`
- Make the farmer name (in the `sellerCard`, ~line 191) a `TouchableOpacity`
  that does `router.push(\`/farmer/\${post.farmer}\`)` (`post.farmer` = farmer id).

### 2. New screen `app/farmer/[id].tsx`
- Header: farmer name + average rating stars.
- Farmer location (from `GET farmers/<id>/`).
- Scrollable list of previous reviews (via `GET reviews/?farmer_id=`).

### 3. `services/api.ts`
- Add `getFarmer(id)` -> `GET /farmers/<id>/`.
- Add `getFarmerReviews(farmerId)` -> `GET /reviews/?farmer_id=<id>`.
- `Review` type already has `farmer_id`, `farmer_username`, `post_title` — no change.

---

## C. Result
- Deleting a post keeps its reviews, still attached to the farmer.
- Customer taps a farmer's name on a product -> new page with the farmer's name,
  location, and all previous reviews.

## D. Deploy & verify
- scp backend files to server, run `migrate`, restart gunicorn, `manage.py check`.
- Test: delete a post in admin -> its review still returned by `reviews/?farmer_id=`.

## Notes
- Farmer location comes from the farmer's own `User.location`; if unset, fall back
  to the post's location on the frontend.
- No frontend API type changes needed beyond the two new `api.ts` functions.

---

# Feature Plan: App-Wide Dark Mode (Manual Toggle)

## Goal
Add a persisted manual **Light / Dark / System** toggle, applied app-wide across
customer, farmer, and deliveryman roles. Light = current look; dark is a new palette.

## Key constraint
All 35 screen/component files bake `Colors.*` values into static
`StyleSheet.create` blocks (resolved once at module load). To react to a theme
change, each style sheet must become a function of the active palette.
`styles/global.ts` (29 refs, used by account screens) has the same issue, plus
inline JSX styles using `Colors.x` (e.g. `app/product/[id].tsx` lines 163-232).

## A. Theme system (new core)
1. `constants/theme.ts` (~25 lines): export `ThemeColors` type; `lightColors`
   (current values, `Colors` kept as alias); `darkColors` (dark equivalents for
   all 16 keys).
2. New `contexts/ThemeContext.tsx` (~70 lines): `ThemeProvider`; state
   `'light'|'dark'|'system'` persisted to AsyncStorage key `nobanno_theme`;
   `system` resolves via `useColorScheme()`; exposes `useTheme()` ->
   `{colors, mode, setMode}` and `useThemedStyles(createStyles)` (memoized).
3. `app/_layout.tsx` (~3 lines): wrap children in `<ThemeProvider>` inside the
   existing Auth/Cart providers.

## B. Mechanical conversion (~35 files, ~170 lines)
For each file with `StyleSheet.create` + `Colors.x`:
- Import `useThemedStyles`.
- In each component: `const styles = useThemedStyles(createStyles);`
- Rename bottom block: `const styles = StyleSheet.create({` ->
  `const createStyles = (Colors: ThemeColors) => StyleSheet.create({`
  (existing `Colors.x` refs work unchanged - `Colors` becomes the param).
- Inline JSX `Colors.x` (mostly `app/product/[id].tsx`): `const { colors } =
  useTheme();` and replace `Colors.x` -> `colors.x`.

- `styles/global.ts` (~35 lines): convert to `createGlobalStyles(Colors)`; update
  the 2 account files importing `globalstyles` (or add a `useGlobalStyles()`).
- 3 role `_layout.tsx` (~15 lines): theme-aware tab bar style + tint colors.

## C. Settings / toggle UI (~80 lines)
- New `components/ThemeToggle.tsx` (~60 lines): segmented Light / Dark / System,
  calls `setMode`, persists automatically.
- Account screens add the toggle (~3 x 6 lines): `app/(customer)/account.tsx`,
  `app/(farmer)/account.tsx`, `app/(deliveryman)/account.tsx`.
- `app.json` (1 line): `userInterfaceStyle: "automatic"`.

## D. Result & verify
- Toggle persists across restarts (AsyncStorage).
- All roles' screens, tab bars, modals, farmer-profile/product screens follow the
  theme. Light remains pixel-identical. No backend changes.

## Scope
~400 lines across ~45 files.