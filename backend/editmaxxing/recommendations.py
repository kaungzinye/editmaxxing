"""Project recommendations, capture revisions, and evidence-backed pair decisions."""

import copy
import hashlib
import json

from .provider import get_provider
from .service import Problem

MOVEMENTS = (
    "Tuck your hair behind one ear.",
    "Tap your fingertips together once.",
    "Tilt your head slightly before speaking.",
    "Lean slightly toward the camera, then settle back.",
)


def publish(project, source_id, editorial):
    if project["recommendations"]["status"] == "ready":
        return
    for kind, choices in (("hooks", editorial["hooks"]), ("titles", editorial["titles"])):
        for i, choice in enumerate(choices):
            rid = kind[0] + "_" + hashlib.sha256(f"{source_id}:{i}".encode()).hexdigest()[:18]
            record = {
                "id": rid,
                "generated_text": choice["proposed_text"],
                "text_revision": 1,
                "rationale_revision": 1,
                "mechanism": choice["mechanism"],
                "rationale": choice["rationale"],
                "evidence_word_ids": choice["evidence_word_ids"],
                "validation": "supported",
            }
            if kind == "hooks":
                record.update(
                    proposed_text=choice["proposed_text"],
                    take_id=None,
                    candidates=[],
                    clips=[],
                    movement=MOVEMENTS[i],
                    action_enabled=False,
                    capture_revision=1,
                )
            else:
                record.update(
                    text=choice["proposed_text"],
                    missing_slots=[],
                    template_id=(choice.get("template") or {}).get("template_id"),
                    slots={s["name"]: s["value"] for s in (choice.get("template") or {}).get("slots", [])},
                )
            project[kind].append(record)
    project["recommendations"] = {"status": "ready", "short_set_reason": editorial["short_set_reason"]}


def check_capture(project, hook, candidate=None):
    candidate = candidate or next((c for c in hook["candidates"] if c["take_id"] == hook["take_id"]), None)
    if candidate is None or candidate["capture_revision"] != hook["capture_revision"]:
        raise Problem(
            "capture_stale", "Record or select a take for the current words and physical action.", 409
        )
    take = project["takes"][candidate["take_id"]]
    words = [w for w in project["words"] if w["id"] in take["word_ids"]]
    if words and max(w["end_ms"] for w in words) - min(w["start_ms"] for w in words) >= 3000:
        raise Problem("hook_too_long", "Record the spoken hook in under three seconds.", 409)
    source = project["sources"][candidate["source_id"]]
    script = next(s for s in source["hook_scripts"] if s["hook_id"] == hook["id"])
    if script["text"] != hook["proposed_text"] or hook["action_enabled"] != (
        script["action_start_ms"] is not None
    ):
        raise Problem(
            "capture_stale", "The selected recording must match the current capture instructions.", 409
        )


def update_hook(service, pid, token, hook_id, request):
    with service.store.tx() as db:
        p = service.require(db, pid, token)
        hook = next((h for h in p["hooks"] if h["id"] == hook_id), None)
        if hook is None:
            raise Problem("hook_missing", "Hook does not exist.", 404)
        changes = request.model_dump(exclude_none=True)
        if not changes:
            raise Problem("invalid_hook", "Supply hook text, movement, or a recorded take ID.")
        if request.base_revision is not None and request.base_revision != hook["text_revision"]:
            raise Problem("revision_conflict", "Refresh the hook before applying this edit.", 409)
        capture_changed = False
        if request.proposed_text is not None:
            text = request.proposed_text.strip()
            if not text or len(text.split()) >= 12:
                raise Problem("invalid_hook", "Spoken hooks require one to eleven words.")
            if text != hook["proposed_text"]:
                hook.update(proposed_text=text, text_revision=hook["text_revision"] + 1, validation="pending")
                capture_changed = True
        if request.movement is not None:
            if request.movement not in MOVEMENTS:
                raise Problem("invalid_movement", "Choose one of the supported physical actions.")
            capture_changed |= hook["action_enabled"] and hook["movement"] != request.movement
            hook["movement"] = request.movement
        if request.action_enabled is not None:
            capture_changed |= hook["action_enabled"] != request.action_enabled
            hook["action_enabled"] = request.action_enabled
        if capture_changed:
            hook["capture_revision"] += 1
            hook.update(take_id=None, clips=[])
        if request.take_id is not None:
            candidate = next((c for c in hook["candidates"] if c["take_id"] == request.take_id), None)
            if candidate is None or not candidate["clips"]:
                raise Problem("invalid_hook", "Choose a reviewed candidate for this hook.")
            check_capture(p, hook, candidate)
            hook.update(take_id=candidate["take_id"], clips=candidate["clips"])
        service.store.save(db, pid, p)
        return copy.deepcopy(hook)


def update_title(service, pid, token, title_id, request):
    with service.store.tx() as db:
        p = service.require(db, pid, token)
        title = next((t for t in p["titles"] if t["id"] == title_id), None)
        if title is None:
            raise Problem("title_missing", "Title does not exist.", 404)
        if title["text_revision"] != request.base_revision:
            raise Problem("revision_conflict", "Refresh the title before applying this edit.", 409)
        text = request.text.strip()
        if not text:
            raise Problem("invalid_title", "Title text requires visible characters.")
        if text != title["text"]:
            title.update(text=text, text_revision=title["text_revision"] + 1, validation="pending")
        service.store.save(db, pid, p)
        return copy.deepcopy(title)


def assess_pairs(service, pid, token, request):
    """Assess immutable request inputs outside the project write transaction."""
    with service.store.tx() as db:
        project = copy.deepcopy(service.require(db, pid, token))
        service.check_revision(project, request.plan_revision)
    checked = {}
    for combination in request.combinations:
        hook = next((h for h in project["hooks"] if h["id"] == combination.hook_id), None)
        title = next((t for t in project["titles"] if t["id"] == combination.visual_title_id), None)
        if not hook or not title or not combination.use_title:
            continue
        effective_title = title["text"]
        if (
            project["plan"]["selected_hook_id"] == hook["id"]
            and project["plan"]["selected_visual_title_id"] == title["id"]
            and project["plan"]["hook_overlay"] is not None
        ):
            effective_title = project["plan"]["hook_overlay"]["text"]
        context = {
            "spoken": hook["proposed_text"],
            "title": combination.overlay.text if combination.overlay else effective_title,
            "spoken_evidence": hook["evidence_word_ids"],
            "title_evidence": title["evidence_word_ids"],
            "words": [w for w in project["words"] if project["sources"][w["source_id"]]["role"] == "body"],
        }
        key = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        assessment = project["pair_assessments"].get(key)
        if assessment is None:
            fixture = all(project["sources"][w["source_id"]].get("fixture", False) for w in context["words"])
            assessment = get_provider(service.settings, fixture=fixture).assess_pair(context).model_dump()
        if not assessment["supported"] or assessment["contradictory"] or assessment["repetitive"]:
            raise Problem("invalid_pair", f"{combination.id}: {assessment['reason']}")
        checked[combination.id] = (hook["text_revision"], title["text_revision"])
        with service.store.tx() as db:
            live = service.require(db, pid, token)
            live["pair_assessments"][key] = assessment
            service.store.save(db, pid, live)
    return checked
