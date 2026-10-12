"""GemmaBot Guard — the verification interface.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

The product's claim is not "a model made a plan"; it is "the guard stopped an
unsafe plan from executing".  This module is where that claim is drawn:

    PLAN RECEIVED
        ↓
    STRUCTURAL CHECK
        ↓
    BOUNDARY CHECK
        ↓
    COLLISION CHECK
        ↓
    REACHABILITY CHECK
        ↓
    SIMULATION
        ↓
    APPROVED / REJECTED

A verdict banner answers first, the seven stages show the work behind it, the
six outcomes are listed, a refused plan gets the exact failure — ERROR, ACTION,
ATTEMPT, then REPAIR REQUESTED or ✓ REPAIRED PLAN VERIFIED — and the model's own
name is demoted to a muted line at the very bottom.  The safety layer is the
product, so it is the loudest thing in this panel.

Two rules, enforced here rather than trusted:

* **Only deterministic facts are printed.**  Every sentence is composed from
  the verifier's own records — a check id, a verdict, the action index the
  simulator refused, the cell it refused to enter.  A check's ``detail`` string
  and an action dict are never echoed: a plan is parsed from free text, so
  either can carry whatever the model wrote, and a panel that explains a
  rejection must not become a way to print a transcript.  :func:`action_text`
  reads exactly the two fields the simulator reads (``cmd``, ``steps``).
* **Nothing is approved that the verifier did not prove.**  The banner, the
  stages and the checklist all read the same four check records; a check whose
  verdict is ``None`` is drawn unproven and an unproven check is never a tick.
  A plan is APPROVED only when all four passed.

Public surface
--------------
PRODUCT / PURPOSE / GUARD_STAGES / CHECK_STAGES    the vocabulary
GUARD_ITEMS                                        the six outcomes
verdict(meta)      -> dict        APPROVED / REJECTED / NOT EVALUATED
chain(meta)        -> list[dict]  one record per stage
items(meta)        -> list[dict]  the six outcomes with their marks
rejection(meta)    -> dict | None ERROR · ACTION · ATTEMPT · the repair
why(meta)          -> dict | None the refusal in plain language
action_text(action)-> str         "FORWARD ×7" — cmd and steps only
panel_html(meta)   -> str         the whole interface
"""
from __future__ import annotations

from frontend.components import components as DS
from frontend.components.blocks import escape as _e

PRODUCT = "GemmaBot Guard"
PURPOSE = "Validate AI-generated robot plans before execution."

# The seven stages of one verification, in the order they run.  The last one is
# named the way the product names the decision, not by its outcome: its state
# carries the outcome.
GUARD_STAGES: tuple[tuple[str, str], ...] = (
    ("plan",         "Plan received"),
    ("structural",   "Structural check"),
    ("boundary",     "Boundary check"),
    ("collision",    "Collision check"),
    ("reachability", "Reachability check"),
    ("simulation",   "Simulation"),
    ("verdict",      "Approved / rejected"),
)

# Which harness check each middle stage judges.  A stage and a check record are
# the same thing under two names, so the chain can never claim a check the
# verifier did not evaluate.  The order is the harness's own, which is the order
# a simulation meets the properties in.
CHECK_STAGES: tuple[tuple[str, str], ...] = (
    ("structural",   "valid_actions"),
    ("boundary",     "in_bounds"),
    ("collision",    "no_collisions"),
    ("reachability", "goal_reachable"),
)

STAGE_LABEL: dict[str, str] = dict(GUARD_STAGES)
STAGE_FOR_CHECK: dict[str, str] = {check: stage for stage, check in CHECK_STAGES}
CHECK_FOR_STAGE: dict[str, str] = dict(CHECK_STAGES)

# The six outcomes, in the order the product reads them out.  Four are the
# verifier's own checks; SIMULATION and EXECUTION are the two things that
# happen after a plan is approved, and they claim nothing without a timeline.
GUARD_ITEMS: tuple[tuple[str, str], ...] = (
    ("valid_actions",  "Valid plan"),
    ("no_collisions",  "No collision"),
    ("in_bounds",      "Within bounds"),
    ("goal_reachable", "Goal reachable"),
    ("simulation",     "Simulation passed"),
    ("execution",      "Execution approved"),
)

# Check verdicts: True / False / unproven (None).
_MARKS: dict[object, str] = {True: "✓", False: "✕", None: "–"}
# Stage states.  "idle" is a stage nothing has reached; "skipped" is one an
# earlier failure prevented.  Neither is drawn as a pass.
_STAGE_MARKS: dict[str, str] = {
    "passed": "✓", "failed": "✕", "running": "◌", "skipped": "–", "idle": "·",
}

# What a passing check proved, in the guard's own words.  Written here rather
# than read from the check's ``detail`` so no model-supplied text can reach the
# interface through a check record.
PASSED_FACT: dict[str, str] = {
    "valid_actions":  "every action is a simulator command",
    "in_bounds":      "no move left the grid",
    "no_collisions":  "no move entered an obstacle",
    "goal_reachable": "the plan ends on the goal",
}

# Short names for the checks that passed before a refusal, for the why-fold.
_SHORT: dict[str, str] = {
    "structural": "structural",
    "boundary": "boundary",
    "collision": "collision",
    "reachability": "reachability",
}


# ---------------------------------------------------------------------------
# Reading the metadata
# ---------------------------------------------------------------------------

def _ok(value: object) -> bool | None:
    """A check verdict, or ``None`` when the value is not one."""
    return value if value is True or value is False else None


def check(meta: dict, check_id: str) -> dict:
    """One check record from *meta*, or an unproven stand-in.

    The stand-in is what an unproven check reads as: ``ok`` is ``None``, so it
    can only ever be drawn as "–".
    """
    for entry in (meta or {}).get("checks") or []:
        if isinstance(entry, dict) and entry.get("id") == check_id:
            return entry
    return {"id": check_id, "label": check_id, "ok": None, "detail": "", "data": {}}


def _checks(meta: dict) -> list[dict]:
    """A source of check records to read refusals from, in stage order."""
    return [check(meta, check_id) for _, check_id in CHECK_STAGES]


def evaluated(meta: dict) -> bool:
    """Whether the guard has judged anything in this session.

    Nothing judged means no checklist: six unproven marks would read as six
    things the guard looked at.  A session that has not run anything shows the
    process and a verdict of its own instead.
    """
    return (meta or {}).get("status", {}).get("key") != "ready"


def _status_key(meta: dict) -> str:
    """The loop state the run is in (``ready`` / ``thinking`` / ``repairing`` …)."""
    return str(((meta or {}).get("status") or {}).get("key") or "ready")


def _exhausted(meta: dict) -> bool:
    """Whether the repair loop has used every attempt it was allowed.

    The one honest signal that a loop with no plan is *over* rather than still
    working: it cannot repair again, so "no plan came out of the loop" is a
    fact and not a prediction.
    """
    attempts = (meta or {}).get("attempts") or {}
    made = int(attempts.get("count") or 0)
    return made >= max(int(attempts.get("max") or 1), 1)


def _in_flight(meta: dict) -> bool:
    """Whether the loop is still working — a run that has not finished yet."""
    return _status_key(meta) in ("thinking", "repairing") and not _exhausted(meta)


def action_text(action: object) -> str:
    """``FORWARD ×7`` / ``TURN LEFT`` — the fields the simulator reads, nothing else.

    A plan is parsed out of free text, so an action dict can carry any key the
    model wrote.  Only ``cmd`` and ``steps`` are ever rendered, which is why the
    guard can print an action the verifier refused without risking a transcript.
    """
    if not isinstance(action, dict):
        return "?"
    cmd = action.get("cmd")
    if not isinstance(cmd, str) or not cmd:
        return "?"
    label = cmd.replace("_", " ").upper()
    if cmd == "forward":
        try:
            steps = int(action.get("steps", 1))
        except (TypeError, ValueError):
            steps = 1
        if steps != 1:
            label = f"{label} ×{steps}"
    return label


def cell_text(cell: object) -> str | None:
    """``(3, 0)`` for a coordinate pair, or ``None`` when it is not one."""
    if (
        isinstance(cell, (list, tuple))
        and len(cell) == 2
        and all(isinstance(value, int) and not isinstance(value, bool) for value in cell)
    ):
        return f"({cell[0]}, {cell[1]})"
    return None


def _failure(entry: dict) -> dict:
    """One refused check as a headline and the fact behind it.

    Composed from the check's id and the structured facts the verifier recorded
    (``data``): the action index it refused, the command itself and the cell it
    refused to enter.  The check's own ``detail`` string is deliberately not
    used — see the module docstring.
    """
    check_id = str(entry.get("id") or "")
    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    index = data.get("action_index")
    index = index if isinstance(index, int) and not isinstance(index, bool) else None
    action = action_text(data.get("action"))
    step = f"step {index}" if index else "the plan"
    cell = cell_text(data.get("cell"))
    base = {
        "check": check_id,
        "check_label": STAGE_LABEL.get(STAGE_FOR_CHECK.get(check_id, ""), "check"),
        "action": action if action != "?" else None,
        "action_index": index,
        "cell": cell,
    }

    if check_id == "no_collisions":
        return {
            **base,
            "headline": f"Collision at {cell}" if cell else "Collision",
            "fact": f"{step} ({action}) would enter the obstacle at {cell}" if cell
                    else f"{step} ({action}) would enter an obstacle",
        }
    if check_id == "in_bounds":
        return {
            **base,
            "headline": f"Out of bounds at {cell}" if cell else "Out of bounds",
            "fact": f"{step} ({action}) would leave the grid at {cell}" if cell
                    else f"{step} would leave the grid",
        }
    if check_id == "goal_reachable":
        robot, goal = cell_text(data.get("robot")), cell_text(data.get("goal"))
        return {
            **base,
            "headline": "Goal not reached",
            "fact": f"the plan ends with the robot at {robot}; the goal is at {goal}"
                    if robot and goal else "the plan does not end on the goal",
        }
    if check_id == "valid_actions":
        return {
            **base,
            "headline": f"Invalid action at {step}" if index else "Plan is not valid",
            "fact": f"{step} is not a simulator command ({action})" if action != "?"
                    else f"{step} is not a usable action dict",
        }
    # No structured failure to read: say that, rather than quote a detail.
    return {
        **base,
        "headline": "Verification faulted",
        "fact": "the simulator raised while evaluating the plan",
    }


# ---------------------------------------------------------------------------
# The verdict, the stages and the outcomes
# ---------------------------------------------------------------------------

def verdict(meta: dict) -> dict:
    """APPROVED / REJECTED / NOT EVALUATED — the guard's own decision.

    APPROVED requires all four checks to have passed (``meta["verified"]``);
    a refused check, or a plan the verifier could not prove, is REJECTED; a
    session that has not run anything is NOT EVALUATED.  There is no fourth
    case and nothing in between.
    """
    checks = _checks(meta)
    failing = [entry for entry in checks if _ok(entry.get("ok")) is False]
    if failing:
        failure = _failure(failing[0])
        return {
            "key": "rejected",
            "label": "REJECTED",
            "state": "error",
            "detail": f"refused at the {failure['check_label'].lower()} — "
                      f"{failure['headline'].lower()}",
        }
    if (meta or {}).get("verified") is True:
        executed = (meta or {}).get("executed")
        return {
            "key": "approved",
            "label": "APPROVED",
            "state": "success",
            "detail": ("all four checks passed — the plan executed on the simulator"
                       if executed else "all four checks passed — sealed for execution"),
        }
    if any(_ok(entry.get("ok")) is not None for entry in checks):
        # Something was judged and the whole plan still was not proven: the
        # verifier could not reach every check, so nothing was approved.
        return {
            "key": "rejected",
            "label": "REJECTED",
            "state": "error",
            "detail": "the verifier could not prove every check — nothing was approved",
        }
    key = _status_key(meta)
    if key == "thinking":
        detail = "the model is still proposing — no attempt has been judged yet"
    elif key == "repairing" and not _exhausted(meta):
        detail = "the loop is repairing — no attempt has been judged yet"
    elif key in ("repairing", "executing"):
        detail = "the loop produced no plan to verify — nothing was approved"
    else:
        detail = "no plan has been submitted — the guard has decided nothing"
    return {
        "key": "pending",
        "label": "NOT EVALUATED",
        "state": "neutral",
        "detail": detail,
    }


def _stage(stage_id: str, label: str, state: str, detail: str) -> dict:
    """One stage record; an unknown state is refused rather than drawn."""
    return {
        "id": stage_id,
        "label": label,
        "state": state if state in _STAGE_MARKS else "idle",
        "detail": detail,
    }


def chain(meta: dict) -> list[dict]:
    """The seven stages, each in the state this run really put it in."""
    plan = (meta or {}).get("plan") or {}
    count = plan.get("count") if isinstance(plan.get("count"), int) else None
    ready = not evaluated(meta)
    in_flight = _in_flight(meta)
    executed = (meta or {}).get("executed")
    halted = (meta or {}).get("halted")
    decision = verdict(meta)

    if count is not None:
        plan_stage = _stage(
            "plan", "Plan received", "passed",
            f"{count} action{'s' if count != 1 else ''} proposed",
        )
    elif ready:
        plan_stage = _stage(
            "plan", "Plan received", "idle", "waiting for an instruction"
        )
    elif _status_key(meta) == "thinking":
        plan_stage = _stage(
            "plan", "Plan received", "running", "the model is proposing a plan"
        )
    elif _exhausted(meta):
        plan_stage = _stage(
            "plan", "Plan received", "failed", "no plan came out of the loop"
        )
    else:
        plan_stage = _stage(
            "plan", "Plan received", "running", "the loop is repairing — no plan yet"
        )
    stages = [plan_stage]

    failure_seen = False
    for stage_id, check_id in CHECK_STAGES:
        entry = check(meta, check_id)
        ok = _ok(entry.get("ok"))
        label = STAGE_LABEL[stage_id]
        if ok is True:
            stages.append(_stage(stage_id, label, "passed", PASSED_FACT[check_id]))
        elif ok is False:
            stages.append(_stage(stage_id, label, "failed", _failure(entry)["headline"]))
            failure_seen = True
        elif failure_seen:
            stages.append(_stage(stage_id, label, "skipped", "an earlier check failed"))
        elif in_flight:
            stages.append(_stage(stage_id, label, "idle", "not evaluated yet"))
        else:
            stages.append(_stage(
                stage_id, label, "skipped" if count is None and not ready else "idle",
                "nothing to check" if count is None and not ready else "not evaluated",
            ))

    steps = (meta or {}).get("steps")
    if executed is True and not halted:
        sim = _stage(
            "simulation", "Simulation", "passed",
            f"{steps} simulator step{'s' if steps != 1 else ''} applied" if steps
            else "every action was applied by the simulator",
        )
    elif halted:
        sim = _stage("simulation", "Simulation", "failed",
                     f"the simulator refused an action ({halted})")
    elif executed is False:
        sim = _stage("simulation", "Simulation", "failed", "the simulator refused the plan")
    elif ready or in_flight:
        sim = _stage(
            "simulation", "Simulation", "idle",
            "not simulated" if ready else "waiting for an approved plan",
        )
    else:
        sim = _stage("simulation", "Simulation", "skipped",
                     "nothing was approved to simulate")
    stages.append(sim)

    stages.append(_stage(
        "verdict", "Approved / rejected",
        {"approved": "passed", "rejected": "failed"}.get(decision["key"], "idle"),
        ("the guard approved the plan for execution" if decision["key"] == "approved"
         else "the plan was refused — nothing executed" if decision["key"] == "rejected"
         else "no plan has been evaluated"),
    ))
    return stages


def items(meta: dict) -> list[dict]:
    """The six outcomes with their marks — the four checks, then the two after.

    SIMULATION PASSED is claimed only by a timeline the simulator completed, and
    EXECUTION APPROVED only by a sealed approval; both read ``None`` (unproven)
    when nothing ran.
    """
    executed = _ok((meta or {}).get("executed"))
    halted = (meta or {}).get("halted")
    approved = _ok((meta or {}).get("approved"))
    steps = (meta or {}).get("steps")

    sim_ok = None if executed is None else (executed and not halted)
    sim_detail = (
        "nothing was simulated" if executed is None
        else f"the simulator halted ({halted})" if halted
        else f"{steps} simulator steps applied" if steps
        else "every action was applied by the simulator" if executed
        else "the simulator refused the plan"
    )
    exec_detail = (
        "no approved plan" if approved is None
        else "the execution gate refused the plan" if not approved
        else "the execution gate sealed the plan"
    )

    out: list[dict] = []
    for item_id, label in GUARD_ITEMS:
        if item_id == "simulation":
            ok, detail = sim_ok, sim_detail
        elif item_id == "execution":
            ok, detail = approved, exec_detail
        else:
            entry = check(meta, item_id)
            ok = _ok(entry.get("ok"))
            detail = (
                PASSED_FACT[item_id] if ok is True
                else _failure(entry)["headline"] if ok is False
                else "not evaluated"
            )
        out.append({
            "id": item_id, "label": label, "ok": ok,
            "mark": _MARKS[ok], "detail": detail,
        })
    return out


# ---------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------

def _refusal_source(meta: dict) -> dict:
    """Which refusal to report, and why that one.

    The panel shows one story, so the ERROR it names has to be the failure
    belonging to the verdict above it:

    * a run that was **repaired and approved** is explained by the first refusal
      — ``meta["refusal"]``, the attempt the verifier refused before the
      passing one — which is what REPAIRED PLAN VERIFIED refers to;
    * a run that **never passed** is explained by its own last attempt, the same
      plan the banner and the stage chain are already reporting.  (The first
      refusal is a different plan that failed for a different reason, so
      reporting it here would contradict the verdict two lines above.)

    Returns ``{"checks", "attempt", "max_tries", "made", "repaired"}``.
    """
    refusal = (meta or {}).get("refusal")
    refusal = refusal if isinstance(refusal, dict) else None
    attempts = (meta or {}).get("attempts") or {}
    max_tries = max(int(attempts.get("max") or 1), 1)
    made = max(int(attempts.get("count") or 0), 0)
    repaired = verdict(meta)["key"] == "approved" and refusal is not None

    if repaired:
        checks = [e for e in refusal.get("checks") or [] if isinstance(e, dict)]
        attempt = max(int(refusal.get("attempt") or 1), 1)
    else:
        checks = _checks(meta)
        attempt = max(made or int((refusal or {}).get("attempt") or 1), 1)
    return {
        "checks": checks or _checks(meta),
        "attempt": attempt,
        "max_tries": max_tries,
        "made": made,
        "repaired": repaired,
    }


def _repair_state(attempt: int, max_tries: int, repaired: bool) -> dict:
    """REPAIRED PLAN VERIFIED / REPAIR REQUESTED / REPAIR EXHAUSTED."""
    if repaired:
        return {
            "key": "verified",
            "label": "REPAIRED PLAN VERIFIED",
            "detail": f"attempt {attempt} was refused — a later attempt passed every check",
        }
    if attempt < max_tries:
        return {
            "key": "requested",
            "label": "REPAIR REQUESTED",
            "detail": f"attempt {attempt} of {max_tries} was refused — no later attempt passed",
        }
    return {
        "key": "exhausted",
        "label": "REPAIR EXHAUSTED",
        "detail": f"attempt {attempt} of {max_tries} was refused — no attempt remained",
    }


def rejection(meta: dict) -> dict | None:
    """The refusal to report — or ``None`` when nothing was refused.

    The attempt reported is the one :func:`_refusal_source` picked, so the ERROR,
    the ACTION and the ATTEMPT always belong to the same plan the banner above
    them judged.
    """
    source = _refusal_source(meta)
    failing = [entry for entry in source["checks"] if _ok(entry.get("ok")) is False]
    decision = verdict(meta)
    # Nothing was refused when nothing failed, the run was not refused and no
    # earlier attempt was: a plan the guard approved, or a session it has not
    # judged yet, has no failure to explain.
    if not failing and decision["key"] != "rejected" and not source["repaired"]:
        return None

    failure = _failure(failing[0]) if failing else _failure({"id": ""})
    attempt = source["attempt"]
    return {
        "attempt": attempt,
        "attempt_label": f"{attempt} / {source['max_tries']}",
        "attempts_made": source["made"],
        "check": failure["check"],
        "check_label": failure["check_label"],
        "headline": failure["headline"],
        "fact": failure["fact"],
        "action": failure["action"],
        "action_index": failure["action_index"],
        "cell": failure["cell"],
        "repair": _repair_state(attempt, source["max_tries"], source["repaired"]),
    }


def _passed_first(checks: list[dict], failing_id: str) -> str:
    """``structural and boundary checks`` — what passed before a refusal."""
    stop = next(
        (index for index, (_, check_id) in enumerate(CHECK_STAGES) if check_id == failing_id),
        None,
    )
    labels = [
        _SHORT[stage]
        for index, (stage, check_id) in enumerate(CHECK_STAGES)
        if (stop is None or index < stop)
        and _ok(next((e.get("ok") for e in checks if e.get("id") == check_id), None)) is True
    ]
    if not labels:
        return ""
    if len(labels) == 1:
        return f"The {labels[0]} check passed first."
    return f"The {', '.join(labels[:-1])} and {labels[-1]} checks passed first."


def why(meta: dict) -> dict | None:
    """The refusal in plain language — the deterministic result, explained.

    Every clause is composed from a fact the verifier recorded: which attempt
    failed, the check that refused it, the action and cell behind that, which
    checks passed first, and what the loop did next.  No model text and no
    guessed motive.
    """
    refused = rejection(meta)
    if refused is None:
        return None

    source = _refusal_source(meta)
    checks = source["checks"]
    attempt, max_tries = refused["attempt"], source["max_tries"]
    state = refused["repair"]["key"]

    if refused["check"]:
        lines = [
            f"Attempt {attempt} of {max_tries} was refused at the "
            f"{refused['check_label'].lower()}: {refused['fact']}."
        ]
        passed = _passed_first(checks, refused["check"])
        if passed:
            lines.append(passed)
        lines.append(
            "That attempt never reached the simulator, so the robot did not move."
        )
        lines.append({
            "verified": "A repair was requested; the repaired plan passed every check "
                        "and the guard approved it.",
            "requested": "A repair was requested; no later attempt passed, so nothing "
                         "was approved.",
            "exhausted": "No attempt remained, so nothing was approved.",
        }.get(state, "Nothing was approved."))
    else:
        lines = [
            f"Attempt {attempt} of {max_tries} could not be evaluated: the simulator "
            "raised while the verifier was walking the plan, so no check could be proven.",
            "Nothing was approved and nothing executed.",
        ]
    return {"title": "Why was this rejected?", "lines": lines}


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def verdict_html(decision: dict) -> str:
    """The banner: the guard's decision, first and loudest."""
    return (
        f"<div class='gb-guard-verdict' data-verdict='{_e(decision.get('key', 'pending'))}' "
        f"title='{_e(decision.get('detail', ''))}'>"
        f"<span class='gb-guard-verdict-label'>{_e(decision.get('label', ''))}</span>"
        f"<span class='gb-guard-verdict-detail'>{_e(decision.get('detail', ''))}</span>"
        f"</div>"
    )


def chain_html(stages: list[dict]) -> str:
    """The stages one under the other, an arrow between each pair."""
    rows: list[str] = []
    for index, stage in enumerate(stages):
        if index:
            rows.append("<div class='gb-guard-arrow' aria-hidden='true'>↓</div>")
        state = stage.get("state", "idle")
        title = f"{stage.get('label', '')} — {state}"
        if stage.get("detail"):
            title = f"{title}: {stage['detail']}"
        rows.append(
            f"<div class='gb-guard-stage' data-guard-stage='{_e(stage.get('id', ''))}' "
            f"data-state='{_e(state)}' title='{_e(title)}'>"
            f"<span class='gb-guard-mark'>{_e(_STAGE_MARKS[state])}</span>"
            f"<span class='gb-guard-stage-label'>{_e(str(stage.get('label', '')).upper())}</span>"
            f"<span class='gb-guard-stage-detail'>{_e(stage.get('detail', ''))}</span>"
            f"</div>"
        )
    return f"<div class='gb-guard-chain'>{''.join(rows)}</div>"


def items_html(rows: list[dict]) -> str:
    """The six outcomes, one line each, with the mark carrying the verdict."""
    body: list[str] = []
    for row in rows:
        ok = row.get("ok")
        verdict_attr = "true" if ok is True else ("false" if ok is False else "none")
        title = f"{row.get('label', '')}: {row.get('detail', '')} ({verdict_attr})"
        body.append(
            f"<div class='gb-guard-check' data-check='{_e(row.get('id', ''))}' "
            f"data-ok='{verdict_attr}' title='{_e(title)}'>"
            f"<span class='gb-guard-mark'>{_e(row.get('mark', '–'))}</span>"
            f"<span class='gb-guard-check-label'>"
            f"{_e(str(row.get('label', '')).upper())}</span>"
            f"<span class='gb-guard-check-detail'>{_e(row.get('detail', ''))}</span>"
            f"</div>"
        )
    return f"<div class='gb-guard-checks'>{''.join(body)}</div>"


def rejection_html(refused: dict) -> str:
    """✕ PLAN REJECTED · ERROR · ACTION · ATTEMPT · the repair that followed."""
    rows = [
        ("error", "ERROR", refused.get("headline", ""), refused.get("fact", "")),
        ("action", "ACTION", refused.get("action") or "—",
         f"step {refused['action_index']}" if refused.get("action_index") else "no action refused"),
        ("attempt", "ATTEMPT", refused.get("attempt_label", "—"),
         f"{refused.get('attempts_made', 0)} attempt(s) made by the loop"),
    ]
    body: list[str] = []
    for field, label, value, detail in rows:
        body.append(
            f"<div class='gb-guard-reject-row' data-field='{_e(field)}' "
            f"data-value='{_e(value)}' title='{_e(f'{label}: {value} — {detail}')}'>"
            f"<span class='gb-guard-reject-label'>{_e(label)}</span>"
            f"<span class='gb-guard-reject-value'>{_e(value)}</span>"
            f"</div>"
        )
    repair = refused.get("repair") or {}
    repair_key = str(repair.get("key") or "")
    repair_mark = "✓ " if repair_key == "verified" else "→ "
    return (
        f"<div class='gb-guard-reject' data-rejected='true'>"
        f"<div class='gb-guard-reject-head'>✕ PLAN REJECTED</div>"
        f"<div class='gb-guard-reject-fact'>{_e(refused.get('fact', ''))}</div>"
        + "".join(body)
        + f"<div class='gb-guard-repair' data-repair='{_e(repair_key)}' "
        f"title='{_e(repair.get('detail', ''))}'>"
        f"{_e(repair_mark + str(repair.get('label') or ''))}"
        f"<span class='gb-guard-repair-detail'>{_e(repair.get('detail', ''))}</span>"
        f"</div></div>"
    )


def why_html(fold: dict) -> str:
    """The compact "Why was this rejected?" fold — no script, no state to keep."""
    lines = "".join(
        f"<div class='gb-guard-why-line'>{_e(line)}</div>" for line in fold.get("lines", [])
    )
    return (
        f"<details class='gb-guard-why'>"
        f"<summary class='gb-guard-why-summary'>{_e(fold.get('title', ''))}</summary>"
        f"<div class='gb-guard-why-body'>{lines}</div>"
        f"</details>"
    )


def metadata_html(meta: dict) -> str:
    """The model and the run numbers — deliberately the quietest row in the panel."""
    model = (meta or {}).get("model") or {}
    rows = (
        ("model", "Model", model.get("family", "—"), model.get("id")),
        ("backend", "Backend", ((meta or {}).get("backend") or {}).get("label", "—"), None),
        ("attempt", "Attempt", ((meta or {}).get("attempts") or {}).get("label", "—"), None),
        ("plan", "Plan", ((meta or {}).get("plan") or {}).get("label", "—"), None),
        ("latency", "Latency", ((meta or {}).get("latency") or {}).get("label", "—"), None),
    )
    body: list[str] = []
    for field, label, value, detail in rows:
        title = f"{label}: {value}" + (f" — {detail}" if detail else "")
        body.append(
            f"<span class='gb-guard-meta-item' data-field='{_e(field)}' "
            f"data-value='{_e(value)}' title='{_e(title)}'>"
            f"{_e(label)} <span class='gb-guard-meta-value'>{_e(value)}</span></span>"
        )
    return f"<div class='gb-guard-meta'>{''.join(body)}</div>"


def panel_html(meta: dict, *, title: str = PRODUCT) -> str:
    """The whole Guard interface for one run's structured metadata.

    The order is the product's claim: what the guard decided, the seven stages
    behind that decision, the six outcomes, and — when a plan was refused — the
    exact failure and its explanation.  The model's name comes last and quietest.
    """
    status = (meta or {}).get("status") or {}
    head = (
        f"<div class='gb-guard-head'>"
        f"<span class='gb-guard-purpose'>{_e(PURPOSE)}</span>"
        f"{DS.status_chip(status.get('label', '—'), status.get('state', 'neutral'))}"
        f"</div>"
    )

    decision = verdict(meta)
    body = head + verdict_html(decision) + chain_html(chain(meta))

    if evaluated(meta):
        body += items_html(items(meta))

    refused = rejection(meta)
    if refused is not None:
        body += rejection_html(refused)
        fold = why(meta)
        if fold is not None:
            body += why_html(fold)

    body += metadata_html(meta)
    return DS.panel(body, title=title)
