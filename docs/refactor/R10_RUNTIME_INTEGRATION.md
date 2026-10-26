# R10 real-runtime integration pass

Date: 2026-09-17. Scope: connect and verify the existing revamped launch path in disposable repository-local workspaces. No product features, GUI redesign, root entrypoint switch, extension-source changes, or legacy changes are part of this pass.

## Root causes and complete traces

### Extensions

**Before R10:**

`TkRevampedApp.open_discord` → `ProfileGUIController.open_selected` → `ExtensionService.get_profile_extension_paths` → enumerate the profile's `Unpacked Extensions/` directory → `ChromiumLauncher.launch_discord` → `build_command` → optional `--disable-extensions-except` and `--load-extension` → Chromium.

Fresh profile creation initialized the profile directory, Preferences, and an empty `Unpacked Extensions/` directory. The open action only enumerated deployments; it did not create them. Deployment was reached through the separate account path: `set_account` → `AccountCompatibilityService.set_account` → `ensure_required_extensions`. A profile without account setup therefore supplied no extension paths. Configuration stopped at the missing deployment step, before command assembly.

R10 also identified that `ensure_required_extensions` did not report an invalid optional source. The current policy keeps the token extractor as an optional discovered source: fresh profiles do not receive it by default, valid existing copies remain in the launch path, and deliberate enablement can deploy it to other profiles. Its repository source is excluded from release builds.

**Current launch path:** `compose` injects the registry-backed `ExtensionService` into the launcher. After checking the profile exists and is stopped, `launch_discord` calls `ensure_enabled_extensions`, which deploys required Autofill and deliberately enabled optional sources. A valid token-extractor copy already in a profile is passed through without refreshing it. Fresh profiles do not get that extension by default. Account configuration is not required. Clicking Open on an already running profile returns without refreshing its deployed extension files.

The registry is `<REPO>\extensions`. Autofill is required and is copied through validated staging into the disposable profile, preserving profile-local `config.js` and extra files. Other valid sources, including the token extractor, are optional; only enabled sources and retained existing copies enter the extension switches. Missing or invalid required sources fail clearly. Deployed directories are validated, including manifest declarations and referenced scripts/icons. Repository sources remain untouched, and the token-extractor source is excluded from release builds.

### Environment

`TkRevampedApp.edit_environment` → `ProfileGUIController.save_environment` → `ProfileService.set_environment` → normalized `environment_preset` / `environment_config` → `ProfileCatalogStore` → disposable `config/profiles.json` → reopened composition → `get_profile_record` → `ChromiumLauncher.build_environment_arguments` → `environment_launch_arguments` → `build_command` → Chromium switches.

The persisted supported settings already reached the launcher. The original GUI selector changed the preset name without refreshing the corresponding displayed values and editability. That made the preset editor misleading and could carry stale displayed values into the saved configuration. R10 refreshes Desktop/Mobile defaults, preserves Custom edits when switching presets, and displays persisted supported Mobile overrides. Save explains that Chromium must be closed and reopened.

Runtime meaning also differed from the labels: `--window-size` requests browser window bounds, not an exact page viewport. Chromium may impose a minimum size. Desktop intentionally emits no environment override. Custom only emits valid configured settings. Mobile emits its supported window/scale/language/touch requests, but the retained `--use-mobile-user-agent` switch did not produce mobile emulation in the installed Windows Chromium.

| Saved setting | Launch consumption | Verified meaning / limitation |
| --- | --- | --- |
| Width and height | `--window-size=W,H` when both exist | Browser window bounds request; page viewport differs and minimum bounds may apply. One missing dimension generates no size switch and is identified in runtime notes. |
| Device scale factor | `--force-device-scale-factor=N` | Custom runtime measured `devicePixelRatio=1.25`. |
| Language | `--lang=LOCALE` | Browser locale request; Custom runtime measured `navigator.language=fr-FR`. Website language preferences are not separately configured. |
| Touch mode | `--touch-events=enabled` or `disabled` | Touch event support request; enabled cases exposed `ontouchstart`, while `maxTouchPoints` remained zero. |
| Mobile mode | Retained `--use-mobile-user-agent` request | Unsupported as Windows mobile device emulation; measured user agent remained Windows desktop. GUI labels it unsupported and disables editing. |
| Timezone | Persisted only; no launch switch | Unsupported override. GUI labels it saved only and disables editing; runtime retained host `Asia/Bangkok`. |

The architecture is unchanged. `environment_runtime_notes`, launcher warnings, and the editor identify limited or unsupported behavior instead of presenting it as effective device emulation. The Windows mobile user-agent limitation also matches [Chromium's primary source](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/components/embedder_support/user_agent_utils.cc): mobile user-agent behavior is gated to Android/iOS.

### Proxy

`TkRevampedApp.edit_proxy` → `ProfileGUIController.save_proxy` → `ProfileService.set_proxy` → normalized `proxy_enabled`, `proxy_scheme`, `proxy_host`, `proxy_port` → disposable `config/profiles.json` → reopened composition → `get_profile_record` → `ChromiumLauncher.build_proxy_arguments` → `proxy_launch_arguments` → `--proxy-server=scheme://host:port` → real Chromium process.

For valid supported unauthenticated saved endpoints, this path was already connected; no missing saved-proxy-to-launch handoff was found. HTTP, HTTPS, SOCKS4, and SOCKS5 endpoints are supported by the existing argument builder. Proxy Off removes endpoint fields and emits no proxy switch.

The reported external-IP failure was not reproduced against a local unauthenticated HTTP fixture. The generated switch reached the actual process, and the local proxy received `http://r10-proxy.invalid/r10-fixture`. That reserved destination succeeded through the fixture proxy; no external proxy endpoint or public egress-IP comparison was tested.

An additional GUI defect was found: parsing a pasted authenticated proxy displayed a warning, but discarded the credentials before Save. The controller then received an unauthenticated endpoint and could save it despite the warning. R10 retains a boolean authenticated-input marker and rejects enabled Save after that parse; no proxy credentials are retained or stored. Parsing an unauthenticated endpoint or selecting Off permits continuing. Proxy authentication remains unsupported. Save explains the close-and-reopen requirement.

### Account compatibility and synthetic mode

`TkRevampedApp.set_account` → GUI-only `@example.invalid` suffix check → `ProfileGUIController.set_account` → `AccountCompatibilityService.set_account` → legacy-compatible `email:password[:totp]` normalization → deploy built-ins / enable developer mode → atomic profile-local `Unpacked Extensions/discord-autofill-extension/config.js` write → later launcher deploy preserves that local config → Chromium loads Autofill → its existing content-script configuration is available on matching Discord pages.

The launcher does not place account credentials on the command line. No authentication-token extraction was implemented or invoked. Real smoke cases did not configure accounts or navigate to Discord.

The suffix restriction is intentional R9/R9B disposable-development safety scaffolding implemented in the hard-coded Tk GUI boundary. It is not an account-service restriction: `AccountCompatibilityService` retains the legacy-compatible input contract. `revamped.main` separately requires a workspace strictly below repository `tmp/`. R10 preserves both development boundaries.

A future interactive/product mode should explicitly select production state paths and permit user-supplied account identifiers through its account UI, with masked secret display, no secret logging, deliberate account removal, and a separately planned secure-storage migration. Synthetic development/testing mode should retain disposable state and `@example.invalid` inputs. Product-mode enablement and credential-storage migration were not performed here.

## Runtime results

- **Extension runtime: PASS (historical R10 evidence).** The then-configured built-ins were supplied in every real launch and reported `ENABLED` by the running Chromium extensions page. R14 supersedes that historical token-extractor configuration and requires only the approved Autofill built-in.
- **Proxy runtime: PASS for the local unauthenticated HTTP fixture.** The actual process contained the configured proxy switch, the fixture proxy recorded the requested reserved hostname, and the restarted Proxy Off case contained no proxy switch and used the direct local fixture.
- **Environment runtime: PASS for supported requests and truthful limitations.** Actual processes received the saved switches; window bounds, scale, language, and touch-event differences were measured. Mobile emulation and timezone override remain explicitly unsupported.

Evidence: [`tmp/r10 real runtime l2cs_byr/r10-runtime-evidence.json`](../../tmp/r10%20real%20runtime%20l2cs_byr/r10-runtime-evidence.json). The evidence records generated argv, executed argv, actual process argv, browser version, runtime measurements, enabled extension metadata, and fixture requests. All four launches used `Chrome/152.0.7977.82` and the report result is `PASS`.

| Real launch | Measured outer bounds | Measured inner viewport | DPR | Language | Touch events / points | Timezone |
| --- | --- | --- | --- | --- | --- | --- |
| Desktop / Proxy Off | 780 × 580 | 764 × 451 | 1 | en-US | false / 0 | Asia/Bangkok |
| Mobile / Proxy Off | 516 × 844 | 500 × 715 | 1 | en-US | true / 0 | Asia/Bangkok |
| Custom / HTTP Proxy | 1002 × 702 | 986 × 572 | 1.25 | fr-FR | true / 0 | Asia/Bangkok |
| Custom / Proxy Off after restart | 1002 × 702 | 986 × 572 | 1.25 | fr-FR | true / 0 | Asia/Bangkok |

Mobile requested 390 × 844; observed width illustrates Chromium's minimum window size. Custom requested 1000 × 700; rounding at DPR 1.25 produced measured 1002 × 702 outer bounds. These are observations of headless Chromium on this Windows host, not guarantees for visible GUI chrome or website layout.

## Exact generated Custom / HTTP Proxy launch plan

Each JSON string below is one argv element. There are no account credentials or external endpoint secrets to redact. The local ephemeral proxy endpoint is included exactly as tested.

```json
[
  "<REPO>\\browser\\chrome.exe",
  "--user-data-dir=<REPO>\\tmp\\r10 real runtime l2cs_byr\\profiles\\profile_0003",
  "--new-window",
  "--no-first-run",
  "--no-default-browser-check",
  "--disable-sync",
  "--process-per-site",
  "--window-size=1000,700",
  "--force-device-scale-factor=1.25",
  "--lang=fr-FR",
  "--touch-events=enabled",
  "--proxy-server=http://127.0.0.1:64132",
  "https://discord.com/app",
  "--disable-extensions-except=<REPO>\\tmp\\r10 real runtime l2cs_byr\\profiles\\profile_0003\\Unpacked Extensions\\discord-autofill-extension",
  "--load-extension=<REPO>\\tmp\\r10 real runtime l2cs_byr\\profiles\\profile_0003\\Unpacked Extensions\\discord-autofill-extension"
]
```

The smoke harness captures this generated production launch plan, then replaces only `https://discord.com/app` with a safe local fixture destination and adds diagnostic flags at the process-factory boundary:

```text
--headless=new
--disable-gpu
--disable-background-networking
--remote-debugging-address=127.0.0.1
--remote-debugging-port=0
```

For the proxy case the replacement destination is `http://r10-proxy.invalid/r10-fixture`; direct cases use `http://127.0.0.1:64131/r10-fixture`. All generated non-URL arguments were compared against the actual process argv. The smoke inspected `chrome://extensions` through a loopback-only diagnostic connection. It invoked no extension account or token-extraction actions. The fixture proxy does not forward traffic.

## Files changed for R10

- `revamped/extensions.py`: require the approved Autofill source and fail clearly on invalid required sources.
- `revamped/launcher.py`: deploy and merge required extensions at launch after the running guard; report environment runtime limitations without secrets.
- `revamped/main.py`: inject the shared extension service into the launcher.
- `revamped/environment.py`: document existing switch meanings and expose unsupported/limited runtime notes.
- `revamped/gui.py`: refresh environment preset state, identify unsupported controls, reject authenticated proxy input, and explain when saved changes apply.
- `tests/test_r6_extensions_accounts.py`: cover required Autofill deployment and optional-source discovery without auto-deploying the token extractor.
- `tests/test_r10_extensions.py`: registry/deployment/real command-assembly checks, missing/invalid source failures, repair, source integrity.
- `tests/test_r10_environment.py`: saved settings through restart, actual command assembly, editor state, unsupported notes.
- `tests/test_r10_runtime_integration.py`: composed GUI-to-launch settings, the approved built-in without accounts, Proxy Off, and running-profile deployment guard.
- `tests/test_r10_proxy_gui.py`: real controller/persistence with editor callbacks; authenticated input rejection, unauthenticated reparse, explicit Off, and absence of saved credentials.
- `tests/browser_smoke_r10.py`: opt-in real Chromium smoke with local direct/proxy fixtures and retained workspace evidence.
- `docs/refactor/R10_RUNTIME_INTEGRATION.md`: this trace and verification report.

`main.py` at the repository root, all repository extension sources, and legacy remained unchanged relative to the task-start snapshot. The working tree already contained unrelated legacy and other changes before R10; those were preserved, not reset or included as R10 changes. Disposable smoke state is retained under repository `tmp/` for inspection. No existing profile data was used or removed.

## Test results

Focused extension checks: 5 R10 tests and 8 existing R6 tests passed. The opt-in real smoke completed four actual Chromium launches and reported `PASS`.

Final broad automated run: `python -B -m unittest discover -s tests -p 'test*.py'` ran 272 tests, with one unavailable-symlink skip and no failures. This includes 17 R10 tests. `python -B scripts/verify.py` and `python -B scripts/verify_revamped.py` gates passed, including syntax/imports, legacy suite, compatibility, frozen integrity, comparison, and source-tree safety. `git diff --check` passed.

A hidden real Tk smoke also passed shell construction/shutdown, actual preset-change callbacks/editability, Custom environment Save, and proxy Save using real widgets and disposable state. Its one-off script/result are retained in `tmp/r10-evidence/gui_editor_smoke.py` and `tmp/r10-evidence/gui-editor-result.json`.

The first real Chromium attempt inside the restricted Codex process environment could start the browser but its renderer/GPU subprocesses failed with access-denied crashes. Repeating the smoke outside that execution restriction passed all four cases with Chromium's own sandbox still enabled; no `--no-sandbox` workaround or product launch flag was added. The successful measurements above use the final integration code.

Re-run real smoke with:

```powershell
python -B tests/browser_smoke_r10.py
```

The diagnostic script uses the existing `psutil` dependency and optional diagnostic-only `websocket-client`; it adds no product dependency. It creates its own repository-local workspace and stops only browser processes it spawned.

## Remaining manual tests

1. Open a newly created disposable profile from the visible revamped GUI without configuring an account. Confirm only the approved Autofill built-in appears enabled in `chrome://extensions`; confirm the token-extractor source is absent from the launch.
2. Switch Desktop → Mobile → Custom in the environment dialog. Confirm the displayed values/editability change correctly and Custom edits survive switching away and back. Save, close Chromium, reopen, and inspect visible window size, scale, language, and touch-event behavior. Do not expect mobile device emulation or timezone override.
3. Configure an authorized unauthenticated external proxy, close and reopen the profile, and compare its public egress IP against Proxy Off. This external-network result was not tested by the local smoke. HTTPS/SOCKS4/SOCKS5 endpoints need their own reachable endpoint verification.
4. Paste and Parse an authenticated proxy string, then confirm enabled Save is rejected and no credentials are stored. Test ordinary `host:port` input and switching to Off.
5. Restart the manager on the same disposable workspace and confirm saved names, environment, and proxy state remain. Confirm Open on an already running profile does not redeploy its extensions.
6. Confirm the account dialog continues to reject non-`@example.invalid` input in disposable development mode. Use synthetic credentials only; production account workflows remain outside R10.
