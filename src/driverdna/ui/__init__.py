"""UI layer (docs/UI-SPEC.md): FastAPI service + built SPA served by
`driverdna ui`. The API contains no business logic — read endpoints are
pass-throughs over the payload/DB read paths, write endpoints wrap the same
audited paths the CLI and chat use. Requires the `ui` extra (fastapi,
uvicorn); the engine never imports this package.
"""
