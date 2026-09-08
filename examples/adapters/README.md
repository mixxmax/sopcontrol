# Adapter scaffold (portable events)

Business projects should **not** fork SOP Control to encode their workflow.
Instead, emit / consume versioned `ControlEvent` records.

## Minimal pattern

```python
from sopcontrol.events import ControlEvent, append_event, fingerprint_payload

append_event(
    project_root,
    ControlEvent(
        event_type="preview_created",
        action="your_action_name",
        actor="human",
        harness="cli",
        rule_ids=["YOUR-RULE-ID"],
        input_fingerprint=fingerprint_payload({"rows": 3}),
        side_effect_class="none",
        outcome="planned",
        next_action="wait_for_user_confirm",
    ),
)
```

CLI:

```bash
echo '{"event_type":"user_confirmed","action":"your_action_name","outcome":"ok"}' \
  | sopctl event append .
sopctl event list .
```

Events are stored under `.sopcontrol-local/worktrees/<worktree_id>/events.jsonl`
(gitignored). Rules stay in committed `.sopcontrol/`.

## Capability tickets (one-shot)

```bash
sopctl ticket issue . \
  --action push \
  --input-fingerprint "$(python -c 'from sopcontrol.events import fingerprint_payload; print(fingerprint_payload({"n":1}))')" \
  --side-effect write_tracker \
  --ttl 900
# → JSON includes ticket_id + secret (print once)

sopctl ticket redeem . \
  --ticket-id tkt-… \
  --secret '…' \
  --action push \
  --input-fingerprint '…' \
  --effect write_tracker
```

Python:

```python
from sopcontrol.tickets import issue_ticket, redeem_ticket, TicketError

t = issue_ticket(root, action="push", input_fingerprint="fp", allowed_side_effects=["write_tracker"])
redeem_ticket(root, ticket_id=t.ticket_id, secret=t.secret, action="push", input_fingerprint="fp", side_effect="write_tracker")
```

Tickets bind `project_id`, `worktree_id`, `task_id`/`run_id`, `action`, `input_fingerprint`, allowed side effects, and expiry. They are single-use; env vars alone cannot forge a valid secret.
