# Discord Profile Manager - Codex Development Instructions

## Project goal

Build and maintain a Windows desktop application for managing multiple isolated Discord browser profiles using Ungoogled Chromium.

The user is primarily the product/logic designer and may not be able to manually review complex code.

Therefore, reliability, incremental development, testing, and clear explanations are more important than aggressive refactoring.

---

## Core development rules

1. Read this file before making significant changes.
2. Read REQUIREMENTS.md before implementing features.
3. Inspect existing code before modifying it.
4. Preserve working functionality unless a task explicitly requires changing it.
5. Do not rewrite the entire project without a strong technical reason.
6. Prefer small, testable changes.
7. Do not silently remove features.
8. Do not modify files outside this workspace.
9. Never delete profile data without explicit user action.
10. Never delete or overwrite browser profile data during application updates.
11. Browser runtime, application configuration, and user profiles must remain separated.
12. Handle missing files and corrupted configuration gracefully.
13. Use relative project paths whenever practical.
14. Avoid unnecessary dependencies.
15. Keep Windows compatibility as the primary target.

---

## Current architecture direction

The application should eventually use:

project/
├── app/
├── browser/
├── profiles/
├── config/
├── extensions/
└── logs/

Ungoogled Chromium is the browser runtime.

Profiles contain Chromium user-data.

Application metadata must eventually be stored separately from Chromium's own internal metadata.

---

## Browser rules

Do not depend on:

ungoogled-chromium-portable.exe

The intended runtime is:

browser/chrome.exe

Each browser profile must have isolated user data.

Example:

browser/chrome.exe --user-data-dir=<profile-directory>

Do not modify or patch Chromium source unless explicitly requested.

---

## Profile requirements

Each profile may eventually contain:

* unique profile ID
* display name
* Chromium user-data directory
* account metadata
* browser/environment preset
* optional proxy configuration
* creation date
* last opened date
* application status

Profile data must survive:

* application restart
* application update
* browser update
* application refactoring

---

## Browser environment

Supported direction:

* Desktop
* Mobile
* Custom

Possible configurable properties:

* viewport
* device scale factor
* language
* timezone
* touch/mobile mode

Do not implement deep fingerprint spoofing or anti-detection mechanisms.

---

## Proxy

Proxy support is optional per profile.

A profile must work normally when proxy is disabled.

Do not automatically rotate proxies.

---

## Security

Never use real credentials for development or tests.

Do not print passwords, secrets, tokens, or TOTP secrets into logs.

Where credentials already exist in legacy code, preserve compatibility first, then migrate them separately in a dedicated security milestone.

Do not implement authentication-token extraction.

---

## Change procedure

Before a major implementation:

1. Inspect relevant files.
2. Identify existing behavior.
3. Explain internally what must change.
4. Make the smallest reasonable implementation.
5. Run syntax/static checks.
6. Run available tests.
7. Inspect errors.
8. Fix regressions caused by the change.

After completing the task, report:

* files changed
* what changed
* tests performed
* test results
* known limitations
* anything requiring manual testing

---

## Refactoring

Do not perform large refactors together with feature implementation.

First make functionality work.

Then test it.

Refactor in a separate task.

Never split the application into many modules simply for architectural aesthetics if doing so increases regression risk.

---

## Legacy application

Legacy source represents currently working behavior.

Study it before replacing existing mechanisms.

A working legacy feature should normally be migrated rather than rewritten from assumptions.

---

## Testing philosophy

When possible test:

* fresh install
* existing profile
* missing browser runtime
* invalid profile path
* profile create
* profile rename
* profile delete
* browser launch
* application restart
* malformed configuration

Never use production account credentials for tests.

---

## Communication with user

The user understands product logic better than implementation details.

When reporting changes:

* explain behavior rather than unnecessary implementation theory
* mention exactly what should be manually tested
* clearly report anything uncertain
* never claim something works if it was not tested