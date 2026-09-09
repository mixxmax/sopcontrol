# Phase E — External side-effect primitives (2026-09-09)

Core provides classifiers, credential tickets, registrations, and idempotent
receipts. Product breakers (JobsDB WAF, portal policy) stay in policy packs.

## CLI

```bash
sopctl effect network . --url https://api.example.com --allow-host api.example.com
sopctl effect issue-network-ticket . --url https://api.example.com --show-secret
sopctl effect browser . --profile main --approved-profile main --url https://example.com
sopctl effect credential-grant . --scope 'cookies:portal' --fingerprint fp1 --show-secret
sopctl effect db-summary . --engine sqlite --operation insert --object jobs --rows 3
sopctl effect background . --kind queue --command 'worker consume' --pid 123
sopctl effect idempotent-write . --key push-1 --action portal.push --result-digest abc
```

## Adapters

| Adapter | Role |
| --- | --- |
| `adapters/effects/network.py` | Host/method/scheme classification |
| `adapters/effects/browser.py` | Profile/CDP/page/human-challenge classification |
| `adapters/effects/credential.py` | Scoped TTL capability tickets |
| `adapters/effects/database.py` | Write/txn digests + counts |
| `adapters/effects/process.py` | Background/scheduler/queue registration |

Secrets and page bodies are never written to ControlEvent detail.
