# Cloudflare Tunnel + Access for DriverDNA

The public-URL network shape chosen in SPEC.md A40 (DEPLOY-SPEC H2's
public-URL option). Two properties matter:

- **Outbound-only.** `cloudflared` dials out to Cloudflare's edge, so the VM's
  OCI security list and host firewall keep **zero** inbound ports open. Nothing
  is exposed by an open port.
- **Edge identity (Access).** Cloudflare Access checks identity (email OTP or
  Google/GitHub SSO) at the edge before a request ever reaches the VM. This is
  the outer wall — **DriverDNA's own app-level auth stays on regardless.** Edge
  identity is not a reason for the app to trust an unauthenticated request.

Access requires a domain on your Cloudflare account (~$10/yr) — the single
component of this plan that is not literally free. If you don't want a public
URL, use Tailscale instead (DEPLOY-SPEC H2's private option) and skip this.

**`deploy/driverdna.service` runs `driverdna ui` with `--behind-proxy`**
(SPEC.md A41), which trusts `X-Forwarded-For`/`X-Forwarded-Proto` only from
`127.0.0.1` — exactly the address `cloudflared` connects from when it proxies
to `service: http://127.0.0.1:8710` above. `cloudflared` sets these headers
itself on the tunnel hop (it is not a chained proxy you configure by hand like
nginx/Caddy, where forgetting to overwrite rather than append a
client-supplied value is the usual mistake), so no extra config is needed here
— but it is what makes login throttling and the session cookie's `Secure` flag
key off the real visitor instead of the tunnel's own loopback connection.

## Setup outline (exact commands in docs/DEPLOY-RUNBOOK.md)

1. `cloudflared tunnel login`, then `cloudflared tunnel create driverdna` —
   note the tunnel UUID and the credentials JSON it writes.
2. Copy `config.example.yml` → `/etc/cloudflared/config.yml`; fill in the UUID
   and your hostname (the `service:` stays `http://127.0.0.1:8710`, the port
   `deploy/driverdna.service` binds).
3. `cloudflared tunnel route dns driverdna driverdna.example.com`.
4. Run `cloudflared` as a service (`cloudflared service install`).
5. In the Cloudflare Zero Trust dashboard: add a **self-hosted Access
   application** for the hostname, with a policy that **allowlists your single
   owner email** and nothing else.

## Optional defence-in-depth

Access sends a signed `Cf-Access-Jwt-Assertion` header on every allowed
request. Verifying it against Cloudflare's public keys (and re-checking the
owner email) inside the app would make forging the header useless even if the
tunnel origin were reached directly. Not built here — it costs one dependency
plus a test, and app-level auth already gates every route. Recorded as the
next hardening step if wanted (DEPLOY-SPEC H2).
