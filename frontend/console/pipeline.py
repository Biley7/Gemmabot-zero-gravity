"""The execution pipeline, the action timeline and the console status strip.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

These three blocks are how the product's central claim reads at a glance:

    AI proposes  →  GemmaBot verifies  →  the robot executes

Pipeline
--------
``pipeline_stages()`` turns one run's real artifacts — the instruction, the
plan the loop produced, ``verify_plan``'s checks, whether an ``ApprovedPlan``
was sealed and the simulator timeline that executed it — into the six stages
INPUT · PLAN · VERIFY · SIMULATE · APPROVE · EXECUTE with the state each one
really reached.  A stage nothing produced stays ``idle``; a stage that was
skipped by an earlier failure says ``skipped``; a stage that was never reached
is never drawn as a pass.

Status strip
------------
The four checks at the bottom are ``harness.VERIFICATION_CHECKS`` — the same
records the verifier and the vision validator emit — under console labels:
PLAN VALID · NO COLLISION · IN BOUNDS · GOAL REACHABLE.  An unproven check
(``ok is None``) is drawn as ``–``, never as a tick.

Action timeline
---------------
``timeline_rows()`` lists the plan's actions with the message the simulator
itself logged for each one (``simulator.step``), and marks where the execution
stands: ``done``, ``blocked`` (the step the simulator refused) and ``pending``
(the actions after a halt).  A run that was never approved lists its proposed
actions as ``pending`` — a plan is not an execution.

Public surface
--------------
PIPELINE_STAGES / STAGE_STATES / STATUS_CHECKS     the vocabulary
pipeline_stages(...)      -> list[dict]  one stage per pipeline step
pipeline_html(stages)     -> str
status_checks(report)     -> list[dict]  the four checks as a status strip row
status_strip_html(rows)   -> str
timeline_rows(actions, ...) -> list[dict]
timeline_html(rows)       -> str
"""
from __future__ import annotations

from frontend.components.blocks import escape as _e
from frontend.simulation.player import action_label

# The pipeline, in order.  ``id`` is what the DOM carries, ``label`` is what
# the console prints.
PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    ("input", "Input"),
    ("plan", "Plan"),
    ("verify", "Verify"),
    ("simulate", "Simulate"),
    ("approve", "Approve"),
    ("execute", "Execute"),
)

# The states a stage can be in.  "idle" means nothing has happened yet;
# "skipped" means an earlier stage failed, so this one never ran; only
# "passed" claims success.
STAGE_STATES: tuple[str, ...] = ("idle", "running", "passed", "failed", "skipped")

# The harness checks, under the console's labels, in the order the status strip
# reads left to right.  The ids are the verifier's own, so a strip row and a
# check record are always the same check — the order is the console's, which is
# why it is not simply ``VERIFICATION_CHECKS``.
STATUS_CHECKS: tuple[tuple[str, str], ...] = (
    ("valid_actions", "Plan valid"),
    ("no_collisions", "No collision"),
    ("in_bounds", "In bounds"),
    ("goal_reachable", "Goal reachable"),
)

_MARKS: dict[object, str] = {True: "✓", False: "✗", None: "–"}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _stage(stage_id: str, label: str, state: str, detail: str = "") -> dict:
    """One stage record.  An unknown state is refused, not drawn as a pass."""
    return {
        "id": stage_id,
        "label": label,
        "state": state if state in STAGE_STATES else "idle",
        "detail": detail,
    }


def pipeline_stages(
    *,
    instruction: str = "",
    phase: str | None = None,
    actions: list | None = None,
    verification: dict | None = None,
    approved: bool | None = None,
    timeline: dict | None = None,
    error: str | None = None,
) -> list[dict]:
    """The six stages, each in the state this run really put it in.

    Parameters
    ----------
    instruction:
        What the operator asked for; drives INPUT.
    phase:
        What is happening right now (``"plan"`` / ``"verify"`` /
        ``"execute"``) while a run is in flight, else ``None``.
    actions:
        The plan the loop produced (``None`` when nothing runnable came out).
    verification:
        ``harness.verify_plan()``'s report for that plan, or ``None``.
    approved:
        Whether an ``ApprovedPlan`` was sealed (``None`` when nothing was
        verifier-approved).
    timeline:
        The simulator's execution of that approval, or ``None``.
    error:
        The loop's final failure reason, when it had one.
    """
    started = bool(
        phase
        or actions is not None
        or verification is not None
        or approved is not None
        or timeline is not None
        or error
    )
    count = len(actions) if isinstance(actions, list) else None
    reason = str(error or "").strip()
    verdict_ok = (verification or {}).get("ok")
    verdict = verdict_ok if verdict_ok is True or verdict_ok is False else None
    halted = (timeline or {}).get("halted")
    sim_ok = None if timeline is None else bool(timeline.get("ok")) and not halted

    stages: list[dict] = []

    # ── INPUT ────────────────────────────────────────────────────────────
    stages.append(_stage(
        "input",
        "Input",
        "passed" if str(instruction or "").strip() else "idle",
        str(instruction or "").strip() or "no instruction",
    ))

    # ── PLAN ─────────────────────────────────────────────────────────────
    if phase == "plan":
        plan_state, plan_detail = "running", "asking the model for a plan"
    elif actions is not None:
        plan_state = "passed"
        plan_detail = f"{count} action{'s' if count != 1 else ''} proposed"
    elif started:
        plan_state, plan_detail = "failed", reason or "no plan came out of the loop"
    else:
        plan_state, plan_detail = "idle", "waiting for an instruction"
    stages.append(_stage("plan", "Plan", plan_state, plan_detail))

    # ── VERIFY ───────────────────────────────────────────────────────────
    if phase == "verify":
        verify_state, verify_detail = "running", "the verifier is judging an attempt"
    elif verdict is True:
        verify_state = "passed"
        verify_detail = "all four checks passed"
    elif verdict is False:
        verify_state, verify_detail = "failed", str((verification or {}).get("reason") or "refused")
    elif not started or actions is None:
        verify_state, verify_detail = ("skipped" if started else "idle"), "nothing to verify"
    else:
        verify_state, verify_detail = "idle", "not evaluated"
    stages.append(_stage("verify", "Verify", verify_state, verify_detail))

    # ── SIMULATE ─────────────────────────────────────────────────────────
    if timeline is not None:
        if sim_ok:
            steps = len(timeline.get("steps") or [])
            cells = int(timeline.get("cells") or 0)
            sim_state = "passed"
            sim_detail = (
                f"{steps} step{'s' if steps != 1 else ''} · "
                f"{cells} cell{'s' if cells != 1 else ''}"
            )
        else:
            sim_state = "failed"
            sim_detail = f"the simulator halted ({halted})" if halted else "the simulator refused the plan"
    elif phase == "execute":
        sim_state, sim_detail = "running", "stepping the approved plan through the simulator"
    elif not started:
        sim_state, sim_detail = "idle", "not simulated"
    elif approved is False or actions is None:
        sim_state, sim_detail = "skipped", "nothing was approved to simulate"
    else:
        sim_state, sim_detail = "idle", "not simulated"
    stages.append(_stage("simulate", "Simulate", sim_state, sim_detail))

    # ── APPROVE ──────────────────────────────────────────────────────────
    if approved is True:
        approve_state, approve_detail = "passed", "the execution gate sealed the plan"
    elif approved is False and verdict is True:
        approve_state, approve_detail = "failed", "the execution gate refused a verified plan"
    elif not started:
        approve_state, approve_detail = "idle", "not approved"
    elif verdict is not True:
        approve_state, approve_detail = "skipped", "nothing passed verification to approve"
    else:
        approve_state, approve_detail = "idle", "not approved"
    stages.append(_stage("approve", "Approve", approve_state, approve_detail))

    # ── EXECUTE ──────────────────────────────────────────────────────────
    if timeline is not None:
        if sim_ok:
            execute_state = "passed"
            execute_detail = (
                "the robot reached the goal" if timeline.get("reached")
                else "the plan ran — the robot stopped short of the goal"
            )
        else:
            execute_state = "failed"
            execute_detail = "execution was refused" if halted else "the plan did not run"
    elif phase == "execute":
        execute_state, execute_detail = "running", "executing the approved plan"
    elif not started:
        execute_state, execute_detail = "idle", "not executed"
    elif approved is not True:
        execute_state, execute_detail = "skipped", "nothing was approved to execute"
    else:
        execute_state, execute_detail = "idle", "not executed"
    stages.append(_stage("execute", "Execute", execute_state, execute_detail))

    return stages


def pipeline_html(stages: list[dict]) -> str:
    """The pipeline strip: one node per stage, arrows between them."""
    nodes: list[str] = []
    for stage in stages:
        state = stage.get("state", "idle")
        title = f"{stage.get('label', '')} — {state}"
        if stage.get("detail"):
            title = f"{title}: {stage['detail']}"
        nodes.append(
            f"<div class='gb-pipe-stage' data-pipe-stage='{_e(stage.get('id', ''))}' "
            f"data-state='{_e(state)}' title='{_e(title)}'>"
            f"<span class='gb-pipe-label'>{_e(str(stage.get('label', '')).upper())}</span>"
            f"<span class='gb-pipe-detail'>{_e(stage.get('detail', ''))}</span>"
            f"</div>"
        )
    return f"<div class='gb-pipe'>{''.join(nodes)}</div>"


# ---------------------------------------------------------------------------
# Status strip — the four harness checks
# ---------------------------------------------------------------------------

def status_checks(verification: dict | None) -> list[dict]:
    """The four checks as status-strip rows, in the verifier's own order.

    A check the report does not carry — or carries with a non-boolean verdict —
    is unproven (``ok=None``) and drawn as ``–``.
    """
    provided: dict[str, dict] = {}
    for entry in (verification or {}).get("checks") or []:
        if isinstance(entry, dict) and entry.get("id"):
            provided[str(entry["id"])] = entry

    rows: list[dict] = []
    for check_id, label in STATUS_CHECKS:
        entry = provided.get(check_id) or {}
        verdict = entry.get("ok")
        ok = verdict if verdict is True or verdict is False else None
        rows.append({
            "id": check_id,
            "label": label,
            "ok": ok,
            "mark": _MARKS[ok],
            "detail": str(entry.get("detail") or "not evaluated"),
        })
    return rows


def status_strip_html(rows: list[dict]) -> str:
    """The bottom status: what the verifier proved about the last plan."""
    items: list[str] = []
    for row in rows:
        ok = row.get("ok")
        verdict = "true" if ok is True else ("false" if ok is False else "none")
        label = str(row.get("label", "")).upper()
        title = f"{label}: {row.get('detail', '')} ({verdict})"
        items.append(
            f"<div class='gb-status-item' data-status-check='{_e(row.get('id', ''))}' "
            f"data-verdict='{verdict}' title='{_e(title)}'>"
            f"<span class='gb-status-mark'>{_e(row.get('mark', '–'))}</span>"
            f"<span class='gb-status-label'>{_e(label)}</span>"
            f"</div>"
        )
    return f"<div class='gb-statusstrip'>{''.join(items)}</div>"


# ---------------------------------------------------------------------------
# Action timeline
# ---------------------------------------------------------------------------

def timeline_rows(
    actions: list | None,
    *,
    timeline: dict | None = None,
) -> list[dict]:
    """One row per plan action, with the simulator's own message for it.

    *timeline* is ``player.build_timeline()``'s execution of the approved plan.
    Its ``steps`` carry the message the simulator logged for each action; the
    step that halted is marked ``blocked`` and the actions after it stay
    ``pending``.  Without a timeline the plan was proposed but never executed,
    so every row is ``pending``.
    """
    actions = [action for action in (actions or []) if isinstance(action, dict)]
    steps = [
        step for step in ((timeline or {}).get("steps") or [])
        if isinstance(step, dict) and step.get("index")
    ]
    by_index = {int(step["index"]): step for step in steps}
    executed = max(by_index) if by_index else 0
    halted_at = next(
        (index for index, step in by_index.items() if step.get("halted")), None
    )

    rows: list[dict] = []
    for index, action in enumerate(actions, start=1):
        step = by_index.get(index) or {}
        if index == halted_at:
            state = "blocked"
        elif index <= executed:
            state = "done"
        else:
            state = "pending"
        if halted_at is not None:
            current = index == halted_at
        else:
            current = executed > 0 and index == executed
        rows.append({
            "index": index,
            "label": action_label(action),
            "message": str(step.get("message") or ""),
            "state": state,
            "current": current,
        })
    return rows


def timeline_html(rows: list[dict]) -> str:
    """The action timeline: numbered, monospace, with the current row marked."""
    if not rows:
        return (
            "<div class='gb-tl'>"
            "<div class='gb-tl-row' data-state='pending'>"
            "<span class='gb-tl-idx'>--</span>"
            "<span class='gb-tl-cmd'>no actions</span>"
            "<span class='gb-tl-msg'>the plan is empty</span>"
            "</div></div>"
        )
    body: list[str] = []
    for row in rows:
        state = row.get("state", "pending")
        current = "true" if row.get("current") else "false"
        title = f"{row.get('label', '')}"
        if row.get("message"):
            title = f"{title} — {row['message']}"
        body.append(
            f"<div class='gb-tl-row' data-action='{int(row.get('index', 0))}' "
            f"data-state='{_e(state)}' data-current='{current}' "
            f"title='{_e(title)}'>"
            f"<span class='gb-tl-idx'>{int(row.get('index', 0)):02d}</span>"
            f"<span class='gb-tl-cmd'>{_e(str(row.get('label', '')).upper())}</span>"
            f"<span class='gb-tl-msg'>{_e(row.get('message', ''))}</span>"
            f"</div>"
        )
    return f"<div class='gb-tl' data-actions='{len(rows)}'>{''.join(body)}</div>"
