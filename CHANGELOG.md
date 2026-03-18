# Changelog — HA Mini App

All notable changes to the HA Mini App are documented here.
Format: [version] — date | summary

---

## [v2.7.0] — 2026-03-18

### ✨ New — Interface Layout Editor
- **🎛️ Full layout editor** — button in app header opens full-screen editor with 2 tabs: Sections and Navigation
- **Section management** — show/hide any section, reassign between pages (🏠/👨‍👩‍👦/💡/📊/☰), reorder with ↑↓ arrows; 16 managed sections total
- **Navigation customization** — change icon (emoji) and label for each of the 5 bottom nav tabs with live preview
- **Persistent layout** — saved to `localStorage` as `ha_layout_v1`, survives reload; Reset button to restore defaults
- **DOM-level reordering** — sections are physically reordered in the DOM via `insertBefore()`, preserving all event listeners and state
- **SW cache bump** — smarthome-v35

---

## [v2.6.0] — 2026-03-18

### ✨ New — Navigation & Structure
- **Bottom Navigation Bar** — fixed 5-tab nav (🏠 Главная / 👨‍👩‍👦 Семья / 💡 Управление / 📊 Данные / ☰ Ещё); active tab icon bounces with spring animation; sections routed by page via CSS

### ✨ New — Dashboard (🏠 Главная)
- **Widget grid** — 4 compact cards (Мощность + color glow / Температура / Свет X/Y / Кто дома X/Y) + wide Prayer times card; tap a widget navigates to relevant page
- **Scenes strip** — horizontal quick-launch chips on home page
- **Context banner** — smart time-aware suggestion: morning→☀️ Утро, late night→🌙 Ночной/выключить, everyone away→🚪 Away; dismiss button

### ✨ New — 📊 Данные page
- **Energy chart** — 24-hour bar chart of power consumption; data stored in localStorage; current hour highlighted; peak hour in red

### ✨ New — 💡 Управление page
- **Security panel** — 🔒 armed/disarmed status bar; presence grid (who's home/away); lights state grid; Home/Away toggle button

### ✨ New — Geofencing
- **Auto home/away** — 📍 toggle in theme picker; saves home coords on first enable; `watchPosition` triggers `homeAwayTap()` when crossing 200 m radius

### ✨ New — Theme personalization
- **Accent color picker** — 6 colors in theme panel (Индиго/Изумруд/Янтарь/Розовый/Голубой/Красный); changes `--accent`, `--accent2`, all glow vars; persists in localStorage

### ✨ New — Animations & Haptics
- **Ripple effect** — click ripple on buttons, widgets, nav tabs, scene chips
- **Skeleton loaders** — shimmer placeholder cards on dashboard before data loads
- **hapticToggle / hapticError / hapticSuccess** — richer vibration patterns
- **SW cache bump** — smarthome-v34

---

## [v2.5.0] — 2026-03-18

### ✨ New — Quick Bottom Sheet (FAB)
- **⚡ FAB now opens a slide-up panel** instead of the old radial menu
- **Lights grid** — toggle each light on/off directly from the sheet (live state, yellow glow when on)
- **Scenes strip** — horizontal scroll with one-tap scene chips (color-coded gradient borders)
- **Quick action row** — 4 buttons: 🔌 Весь выкл / 🤖 Пылесос / 🌙 Ночной / ☀️ Утро
  - Night/Morning auto-finds a matching scene by name or emoji from loaded scenes

### ✨ New — Family section redesign
- **Presence summary bar** — compact horizontal pills at the top of the Семья section; each pill shows avatar + name + green (home) or grey (away) dot; avatars load automatically
- **Full-text tab labels** — tabs now show 💬 Чат / 🔔 Напом / 📸 Фото / 📞 Звонки (instead of emoji-only)
- **Badge slot on Звонки tab** — unread missed-call counter ready

### 🔧 Changed
- **SW cache bump** — smarthome-v33 to invalidate cached assets

---

## [v2.4.0] — 2026-03-18

### ✨ New — Friends App
- **Online presence** — green dot on contact avatars; "онлайн" / "X мин. назад" status via SSE real-time events
- **Contact sheet** — tap contact card to open bottom sheet with quick actions (call, video, message)
- **Text chat** — 💬 Chat tab with conversation list and per-contact thread; 48h history; unread badge; real-time via SSE
- **Live location** — 📍 Location tab; share GPS position for 15/30/60 min; Leaflet map shows all active locations; stop button; SSE location_update/location_stopped events
- **Group admin panel** — group admins can approve / reject pending members directly in the app (PATCH /friends/api/my-group/members/:username)
- **Friends prayer times fix** — now reads from same HA entities as main app via /friends/api/prayers endpoint, guaranteed matching times
- **Call history per contact** — expandable history grouped by peer, last 48h; missed call badge on nav

### ✨ New — HA App
- **Scene gradient cards** — each scene button gets a unique color gradient based on its emoji (night=indigo, morning=orange, cinema=red, etc.)
- **Sparkline chart** — mini temperature trend line under the room temp reading, auto-updates with each status poll
- **Activity timeline** — new collapsible section showing recent activity log + call log (uses /ha-app/api/timeline)
- **SW cache bump** — smarthome-v32 to invalidate cached assets

---

## [v2.3.0] — 2026-03-18

### ✨ New
- **Prayer times timezone fix** — Grozny/Moscow (UTC+3) time used for date and past/next calculation; `timezonestring=Europe/Moscow` added to API call so times are always correct regardless of device timezone

### 🔧 Changed
- **Avatar in call screen +25%** — `.call-avatar-xl` increased from 190 → 240 px, font 76 → 95 px, pulse rings 270/230 → 340/290 px for better visibility

---

## [v2.2.0] — 2026-03-18

### ✨ New
- **iOS-style fullscreen incoming call UI** — caller photo blurred as background, large circular avatar (240 px) with pulse rings, iOS-circle action buttons (Accept / Decline / Mute)
- **Video call placeholder** — avatar visible as placeholder until remote stream arrives (z-index stacking)
- **Push notification action buttons** — Answer / Decline buttons on lock screen notification; Decline works without opening app (Service Worker fetches reject signal directly)
- **Auto-answer** — tapping "Answer" in notification opens app and accepts call automatically (`?auto_answer=1`)
- **SW token storage** — HA token stored in IndexedDB (accessible from Service Worker context) for reject-without-open feature

### 🔧 Changed
- Call overlay layout changed from centered box to fullscreen flex column
- `smarthome-v31` cache version bump

---

## [v2.1.0] — 2026-03-15

### ✨ New
- **Call ringtones** — incoming call plays ringtone loop via Web Audio API; outgoing call plays ringback tone; tones stop on answer/reject/hangup
- **Video call** — video track support in WebRTC peer connection; toggle camera button during call
- **Avatar upload** — circular crop editor (drag + pinch-zoom); stores photo server-side; shown in contacts, call screen, profile

### 🔧 Changed
- Service Worker cache version `smarthome-v30`

---

## [v2.0.0] — 2026-03-10

### ✨ New
- **WebRTC audio/video calls** — peer-to-peer calls between family members via SSE signaling (offer/answer/ICE)
- **TURN/STUN relay** — coturn credentials endpoint for NAT traversal
- **Incoming call detection** — pending call poll on app open + SSE push delivery
- **Push notifications** — Web Push (VAPID) for incoming calls; subscribes on first login

### 🔧 Changed
- Major architecture: added aiohttp web server (port 8766) alongside Telegram bot
- SSE stream at `/ha-app/api/events` for real-time updates

---

## [v1.5.0] — 2026-03-05

### ✨ New
- **Permissions system** — per-user feature access control (lights, cameras, vacuum, shopping, etc.)
- **Family presence** — real-time person.* tracking from HA with last-seen timestamps
- **Shopping list** — shared family list with assignments, quick-add items, mark done
- **Scenes** — one-tap scene activation cards

---

## [v1.0.0] — 2026-02-28

### 🎉 Initial release
- Telegram Mini App (PWA) for Home Assistant control
- Real-time status: power, temperature, humidity, internet
- Climate control — temperature setpoint, floor heating toggle
- Light groups — on/off/brightness per room
- Camera snapshots via Frigate proxy
- Prayer times from HA `input_datetime` entities
- Weather widget (Open-Meteo API)
- Dark theme, animated ambient background
- Service Worker offline cache
