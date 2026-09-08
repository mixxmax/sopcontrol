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
