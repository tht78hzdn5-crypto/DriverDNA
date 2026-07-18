"""Garage61Client: token auth, lap listing/filtering, CSV fetch, sync state.

Built after M0b (the API probe). Auth via GARAGE61_TOKEN — environment only,
never persisted, printed, or logged. Capabilities (other-driver lap access,
pagination, rate limits, API-vs-manual export parity) are documented from
observed behavior in docs/garage61-api.md before anything is built on them.
"""
