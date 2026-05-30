# Display Glass EMG Handwriting Input — Use Auto-Handwriting on a Focused `<input>`

## Context

The `test/` build's "EMG handwriting strip" (a `<canvas>` activated by tap, with strokes processed via the standard W3C `navigator.createHandwritingRecognizer` API) does not work on Hypernova. Internal research clarifies why:

- The standard Web Handwriting API is designed for **touch/stylus pointer strokes on a screen**. EMG handwriting on Meta wearables has **no visual stroke component** — the Ceres wristband captures muscle signals and an on-device model decodes them to text. There are no pointer events to feed `createHandwritingRecognizer`.
- Hypernova exposes EMG-recognized text to web apps via the **`MetaGlassSDK` JavaScript bridge**, which is auto-injected into every Hypernova WebApp page (`window.MetaGlassSDK`). The `MetaGlassSDK.autoHandwriting` module is **enabled by default** and automatically starts an EMG session **the moment a standard text input receives focus**, applying recognized text directly to that element's DOM (sources: `wiki/Smartglass/webapp/sdk/api/auto-handwriting/`, `wiki/Smartglass/webapp/sdk/api/handwriting/`).
- The SDK wiki carries an explicit confidentiality warning: *"Never publicly host code that directly invokes any MetaGlassSDK methods."* The `test/` directory is served from a public GitHub Pages repo, so the implementation **must not reference `MetaGlassSDK` at all**. Auto-handwriting lets us achieve this — by simply using a standard `<input>` element, EMG works on Hypernova with zero SDK calls in our code.

Goal: replace the broken canvas-based strip with a standard text input so EMG handwriting automatically activates when the user focuses (highlights) it on Hypernova, and falls back gracefully to keyboard typing everywhere else. Keep this change isolated to `test/` so the live URL is unaffected.

## Approach

### New stop-entry layout (preserves the balanced visual)

The `.hw-strip` keeps its place above the numpad, but its internals change from `[✎ icon] [canvas + placeholder + ghost preview]` to `[✎ icon] [<input>]`. Tapping the strip focuses the input → on Hypernova, `MetaGlassSDK.autoHandwriting` (default-on) starts an EMG session and writes recognized digits into the input as the user "writes in the air" — exactly satisfying the user's intent: *"load EMG handwriting when the text box is highlighted."*

Single source of truth: the input is bound to `state.stopNumber` via an `input` event listener (strips non-digits and caps to 6 chars). The big top `.stop-number` display continues to show `state.stopNumber`, so the user sees their EMG writing instantly mirrored in the big focal display. The numpad also writes to `state.stopNumber` and the input stays in sync — numpad ⇄ EMG are fully interchangeable mid-entry.

Active visual: when the input is focused, the strip gets the existing cyan-dashed border + glow (already defined via `.hw-strip__activator.active` in `test/styles.css`) — driven by CSS `:focus-within` instead of an explicit JS class.

### What gets removed

All canvas/stroke/recognizer JS becomes dead weight:
- `hwState`, `initHwRecognizer`, `getHwCanvas`, `clearHwCanvas`, `updateHwPreview`, `syncHwClearBtn`, `activateHandwriting`, `deactivateHandwriting`, `clearHandwriting`, `commitHandwriting`, `scheduleRecognize`, `runRecognize`, `setupHandwritingEvents`, and the `setupHandwritingEvents()` call inside `init()`.
- `handleAction` cases `'hw-activate'`, `'hw-clear'`, `'hw-enter'`.
- The `<canvas id="hw-canvas">`, `.hw-strip__placeholder`, `.hw-strip__preview` markup.
- The CSS rules that target those classes (`#hw-canvas`, `.hw-strip__placeholder`, `.hw-strip__preview`, `.hw-strip__activator.active #hw-canvas`).

### What stays

- `.hw-strip`, `.hw-strip__activator`, `.hw-strip__icon`, `.hw-strip__canvas-wrap` shells are reused/lightly renamed to wrap the input.
- The numpad layout (top row `[⌫ 0 GO]`, then 1-9) and all its actions: `num`, `num-clear`, `num-delete`, `num-go`.
- Big top `.stop-number` display + circular `×` clear button.
- `updateStopDisplay()`, the existing 6-digit max in `case 'num':`, the GO toast/navigate logic.
- Numpad 2D arrow-grid focus traversal in `moveFocus()` — unchanged (still 3×4 grid).

### `num-go` / `num-delete` behavior

Simplified since there's no separate handwriting commit step:
- `num-go`: navigate to player if `state.stopNumber.length > 0`, else show "Enter a stop number first" toast. (No commit step needed — input is already synced to `state.stopNumber` live.)
- `num-delete`: slice last digit off `state.stopNumber`; sync to input.
- `num-clear`: empty `state.stopNumber`; sync to input.

### Why this is safe for public GitHub Pages hosting

The code base contains **zero references** to `MetaGlassSDK`, `window.MetaGlassSDK`, `handwriting`, EMG, or any Meta-internal API surface. It is just `<input type="text" inputmode="numeric">` with normal `input`/`focus` events. Auto-handwriting is provided by the Hypernova runtime and operates on the focused element from outside our page — our code does not know it exists. This complies with the confidentiality warning and works identically on regular browsers (where typing/numpad both still function).

## Files to Modify

All changes are confined to `test/` so the original deployment at `https://joypeaceee.github.io/museum-audio-tour/` stays untouched.

- `/Users/shanchu/Documents/Develop/museum-audio-tour/test/index.html`
  - Inside `.hw-strip__canvas-wrap`, replace `<canvas>` + placeholder + preview spans with a single `<input id="hw-input" class="hw-strip__input focusable" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="off" placeholder="Handwrite digits">`.
  - The outer `.hw-strip__activator` becomes a `<label for="hw-input">` (tap anywhere in the strip focuses the input, including the ✎ icon). Drop `data-action="hw-activate"` and `id="hw-box"`.

- `/Users/shanchu/Documents/Develop/museum-audio-tour/test/styles.css`
  - Add `.hw-strip__input` rule: transparent background, no border, monospace font matching `.stop-number` aesthetic but smaller (~18 px), color `var(--accent-secondary)` or `--text-primary`, letter-spacing 2 px, full width of canvas-wrap, `outline: none`, placeholder uses `var(--text-muted)` italic 13 px.
  - Replace `.hw-strip__activator.active` selector with `.hw-strip__activator:focus-within` for the cyan-dashed border + glow.
  - Remove `#hw-canvas`, `.hw-strip__placeholder`, `.hw-strip__preview`, `.hw-strip__activator.active #hw-canvas` rules.
  - Keep `.hw-strip`, `.hw-strip__icon`, `.hw-strip__canvas-wrap` as the row + icon + flex wrapper.

- `/Users/shanchu/Documents/Develop/museum-audio-tour/test/app.js`
  - Delete the entire EMG HANDWRITING section (lines ~556–798): `hwState`, `initHwRecognizer`, `getHwCanvas`, `clearHwCanvas`, `updateHwPreview`, `syncHwClearBtn`, `activateHandwriting`, `deactivateHandwriting`, `clearHandwriting`, `commitHandwriting`, `scheduleRecognize`, `runRecognize`, `setupHandwritingEvents`.
  - Remove `setupHandwritingEvents();` call from `init()`.
  - Remove `'hw-activate'`, `'hw-clear'`, `'hw-enter'` cases from `handleAction`.
  - Remove `deactivateHandwriting()` call inside `onScreenEnter('stop-entry')`; replace with `document.getElementById('hw-input').value = '';`.
  - Update `updateStopDisplay()` to also write `state.stopNumber` into `#hw-input.value` (so numpad input stays mirrored in the strip).
  - Simplify `num-go`, `num-delete`, `num-clear` cases as described in "Behavior" above (no commitHandwriting calls).
  - Add a single new event listener in `setupEvents()` (or `init()`): on `#hw-input` `input`, set `state.stopNumber = e.target.value.replace(/\D/g, '').slice(0, 6)` then `updateStopDisplay()`. This is the EMG → state bridge.

### Reuse

- All existing color tokens (`--accent-primary`, `--focus-ring`, `--focus-glow`, `--bg-tertiary`, `--bg-card`, `--radius-md`) — no new design tokens needed.
- Existing `showToast()`, `updateStopDisplay()`, `navigateTo()`, `focusFirst()`, `moveFocus()` — unchanged.
- Existing back-button + numpad keyboard handling (`Escape`, digit-key shortcuts, `Backspace`) in `setupEvents()` — unchanged.

## Verification

1. **Hypernova EMG (primary path)**: load `https://joypeaceee.github.io/museum-audio-tour/test/` on Hypernova → pick a museum → tap the handwriting strip → input gets focus and shows the cyan dashed/glow border → write digits "in the air" with the wristband → digits appear in the strip input and the big top display simultaneously → tap GO → navigate to player.
2. **Numpad path**: tap digits on the numpad → big display and strip input both update → GO navigates.
3. **Mixed path**: type "1" on numpad → write "2" via EMG → big display shows "12" → backspace once → "1" → GO → navigate to Stop #1.
4. **Live URL unaffected**: `https://joypeaceee.github.io/museum-audio-tour/` continues to serve the original design (no handwriting, original numpad order). Verify by comparing against pre-existing screenshots.
5. **Non-Hypernova fallback**: open `test/index.html` in a regular browser (or `python3 server.py` then `http://localhost:8000/test/`) → tap the strip → the input focuses; typing on the physical keyboard fills it; numpad buttons still work; GO navigates. (No EMG, no canvas — keyboard works because it's now a real `<input>`.)
6. **Confidentiality scan**: `git grep -i 'metaglass\|emg\|handwriting' test/` should return only the directory-style comments / placeholder text — **no** runtime references to `MetaGlassSDK` or any Meta-internal symbol. Our code is fully agnostic.
7. **Focus order**: from the back button, Tab/ArrowDown should land on `× clear` → handwriting input → numpad cells (⌫, 0, GO, then 1-9). Arrow-key 2D grid still works on numpad.
8. **Screen reset**: navigate Back, then re-enter stop-entry → input is empty, big display shows "---", focus is on the first focusable.
