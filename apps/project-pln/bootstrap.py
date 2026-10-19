"""project-pln bootstrap — write the DECLARED starting state of a fresh office into Plane.

NOT an executable, and not a Django management command: it is fed to Django on stdin, which is the
only way to run ORM code inside the container without adding a file to the image or a route to the
product:

    ./scripts/dc exec -T -e PLANE_BOOTSTRAP=… project-pln \\
        python3 /app/backend/manage.py shell < apps/project-pln/bootstrap.py

`hooks/onboard` is the only caller. Everything it needs arrives in the environment, so no argument
ever carries a secret:

    PLANE_BOOTSTRAP        bootstrap.yaml, rendered to JSON by the hook
    PLANE_OWNER_EMAIL      the owner's login (his identity in this office: n8n's owner by default)
    PLANE_OWNER_PASSWORD   his password, minted by the hook into .env when the office has none
    PLANE_OWNER_FIRSTNAME / PLANE_OWNER_LASTNAME

WHY THE ORM AND NOT THE API. These are exactly the rows Plane's own god-mode sign-up view and its
workspace/project serializers write (`Instance.is_setup_done`, `InstanceAdmin`, `User`+`Profile`,
`Workspace`+`WorkspaceMember`, `Project`+`State`+`Label`, `ProjectMember`). Driving the API instead
would mean a hook logging into a CSRF-protected browser flow; driving SQL would mean guessing at
columns the model layer owns (username, sort_order, sequence_id). This is the product's own code
path — the only version of "the starting state" that cannot drift from the product.

IDEMPOTENT. Every object is looked up before it is written and reported as `kept`; a user's password
is set only when the user is CREATED, so re-running never invalidates a password the owner has since
changed — which matters, because this runs on every `./bbox run`.

SAFE ON AN INSTANCE THAT IS ALREADY SOMEONE'S. If an instance admin exists under a different email,
this refuses to add a second one and says so: an office's Plane is not a place to quietly acquire a
second owner. Nothing else is touched.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.utils import timezone

from plane.db.models import (
    APIToken,
    Issue,
    Label,
    Profile,
    Project,
    ProjectMember,
    State,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration

TAG = "[project-pln]"
TIMEZONE = "Asia/Jerusalem"
OFFICE_TOKEN_LABEL = "office-agent"
# The handover consent. Releasing another person's administrator row is not something a bring-up
# hook may conclude on its own — see the guard below.
TAKE_OVER = (os.environ.get("PLANE_OWNER_TAKE_OVER") or "").strip().lower() in ("1", "true", "yes")
ONBOARDING_DONE = {"profile_complete": True, "workspace_create": True,
                   "workspace_invite": True, "workspace_join": True}
MOBILE_ONBOARDING_DONE = {"profile_complete": True, "workspace_create": True, "workspace_join": True}

created: list[str] = []
kept: list[str] = []
problems: list[str] = []
result: dict = {}


def log(msg: str) -> None:
    print(f"{TAG} {msg}", flush=True)


def need(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def stop(code: int = 1) -> None:
    """Leave through the front door: the hook reads this line, and the exit code is its verdict."""
    print("RESULT|" + json.dumps({**result, "created": created, "kept": kept,
                                  "problems": problems}, ensure_ascii=False), flush=True)
    sys.exit(code)


def config() -> dict:
    raw = need("PLANE_BOOTSTRAP")
    if not raw:
        problems.append("PLANE_BOOTSTRAP is empty — the hook did not render bootstrap.yaml")
        return {}
    try:
        return json.loads(raw)
    except ValueError as e:
        problems.append(f"PLANE_BOOTSTRAP is not valid JSON: {e}")
        return {}


# ── the office's own credentials, in the credential plane ───────────────────────────────────────
# Two accounts a person would otherwise have to create by clicking, and one of them he could not
# create without a browser at all (the office's API key):
#
#   plane_local_admin-local        the owner's sign-in — email + password + origin
#   plane_local_api_token-local    the key the office itself uses against the API (X-API-Key)
#
# They are INSTANCES in `connections` (`http://connections:8990`), which is what this deployment
# means by "a stored secret": one copy, revealed field by field and audit-logged, surviving this
# container, its volumes and a rebuild — the same place the local forge's token and the mail/drive
# accounts live. Never in Plane's database in readable form, never printed here, never in argv.
#
# Canonical ids (`<protocol>-local`), exactly as the vault's own `create_instance` documents: a
# platform service's built-in engine must keep ONE name, or every re-run would look like a new
# account and the owner would accumulate rows he dare not delete.

def vault(path: str, method: str = "GET", body: dict | None = None):
    """Talk to the vault. Returns (json, http_status); a transport failure is status -1."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{VAULT}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}"), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:300]}, e.code
    except Exception as e:                                          # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}, -1


def vault_account(iid: str, protocol: str, label: str, secret: dict, hint: str) -> None:
    """Create the account, or refresh the one already there — this runs on every bring-up.

    The update is a MERGE (`PUT …/secret`), so a field this run does not carry (a password it must
    not overwrite) keeps the value the vault already holds.
    """
    if iid in instances:
        out, code = vault(f"/api/instances/{iid}/secret", "PUT", {"secret": secret})
        verb = "updated"
    else:
        out, code = vault("/api/instances", "POST",
                          {"id": iid, "protocol": protocol, "label": label,
                           "secret": secret, "account_hint": hint})
        verb = "created"
    if code not in (200, 201):
        problems.append(f"storing {iid} in the credential plane failed (HTTP {code}): "
                        f"{out.get('error', out)}")
        log(f"could not store {iid} in the credential plane — it is listed under problems")
        return
    kept.append(f"vault:{iid}")
    log(f"{verb} the account '{label}' in the credential plane")


def office_api_token() -> str:
    """The office's key. Minted once, then reused — idempotent by a stable label.

    Plane's own UI mints these under Profile settings, and nothing about the row needs a browser.
    A token the owner REVOKED is deliberately not resurrected here: `is_active` is what the API
    checks, and silently undoing a revocation is the one thing a key-minting hook must never do.
    """
    row = APIToken.objects.filter(user=user, label=OFFICE_TOKEN_LABEL).first()
    if row is None:
        row = APIToken.objects.create(label=OFFICE_TOKEN_LABEL, user=user, user_type=0,
                                      description="the office's own key (apps/project-pln)")
        created.append("api_token")
        log("minted the office's API key")
    else:
        kept.append("api_token")
    return row.token


VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")


def vault_env(path: str) -> tuple[str, int]:
    """The PLAINTEXT body of a credential-plane route (`vault()` parses JSON, which is the masked
    shape for `/api/export/<service>`). Returns (body, status); a transport failure is status -1."""
    req = urllib.request.Request(f"{VAULT}{path}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")[:300], e.code
    except Exception as e:                                          # noqa: BLE001
        return f"{type(e).__name__}: {e}", -1


def declared_values() -> dict:
    """What the credential plane SAYS the owner's login is — the vault override first, then .env.

    `GET /api/export/project-pln?format=env` is the platform's own answer to "what is this service's
    credential": it resolves every connection `apps/project-pln/app.json` declares through the vault
    (a value edited in the console's credential screen lives there) and nothing else, with the caller
    identified from the docker socket. So an edit in that screen reaches this account on the next
    bring-up, and `.env` remains the seed for an office that has never touched it.

    `format=env` and NOT the route's default JSON body, which is MASKED on purpose
    (`env={k: mask(v)}`, `mask()` being `v[:3] + "…" + v[-2:]`). This function used to read the
    mask as if it were the declaration, and on 2026-10-01 that is exactly what happened: the owner
    arrived here as `sol…om` (`person8@example.com` under `mask()`), so the bootstrap CREATED a
    user with that address, made him the instance administrator and the owner of the declared
    workspace, and released the real owner — all while reporting success. A masked value is a
    rendering of a secret, never the secret.
    """
    body, code = vault_env("/api/export/project-pln?format=env")
    if code not in (200, 201):
        return {}
    out: dict = {}
    for line in body.splitlines():
        key, _, val = line.partition("=")
        if key.strip() and val:
            out[key.strip()] = val
    return out

cfg = config()
email = need("PLANE_OWNER_EMAIL").lower()
password = need("PLANE_OWNER_PASSWORD")
# The credential plane outranks the values the hook passed in: it is where the owner edits them.
#
# RESOLVED HERE, BEFORE THE GUARD BELOW ASKS WHOSE INSTANCE THIS IS. It used to be resolved after it,
# so the guard judged the address the hook passed and everything below then acted for another one.
# hp-laptop, 2026-10-06: `.env` had just been set to the instance's real administrator, the credential
# plane's container still carried the line it was created with (`ci@local.dev`, the CI placeholder
# the hook itself refuses) — the guard saw the real owner and passed, and the applier revived the
# placeholder's administrator row and handed it the declared workspace, reporting success. The
# guard exists for exactly that ("a second owner is not something a bring-up hook gets to decide"):
# it has to see the address that will be acted for.
_declared = declared_values()
if _declared.get("PLANE_OWNER_EMAIL"):
    declared_email = str(_declared["PLANE_OWNER_EMAIL"]).strip().lower()
    if declared_email != email:
        log(f"the credential plane names {declared_email} as the owner — using it")
        email = declared_email
if _declared.get("PLANE_OWNER_PASSWORD"):
    password = str(_declared["PLANE_OWNER_PASSWORD"])
    log("using the owner's password from the credential plane")
first_name = need("PLANE_OWNER_FIRSTNAME") or email.split("@")[0]
last_name = need("PLANE_OWNER_LASTNAME")

instance = Instance.objects.first()
if instance is None:
    problems.append("no Instance row — the api entrypoint has not registered this deployment")
if not email:
    problems.append("PLANE_OWNER_EMAIL is empty")
if problems:
    log("cannot bootstrap: " + "; ".join(problems))
    stop()

ws_cfg = cfg.get("workspace") or {}
ws_name = (ws_cfg.get("name") or "Office").strip()
ws_slug = (ws_cfg.get("slug") or "office").strip()

# ── the guard that comes before everything else ─────────────────────────────────────────────────
# `InstanceAdmin.user` is `null=True, on_delete=SET_NULL`: a deleted user leaves the row behind,
# pointing at nobody. Such a row is not an administrator — counting it as one would refuse to
# bootstrap an instance that in fact has nobody able to sign in. (Found by deleting a user on a
# scratch instance: `existing_admin.user.email` raised, and the row kept `admins` at 1 while the
# instance had no owner at all.)
dangling = InstanceAdmin.all_objects.filter(user__isnull=True, deleted_at__isnull=True).count()
if dangling:
    problems.append(f"{dangling} instance-admin row(s) point at a deleted user — ignored")
existing_admin = InstanceAdmin.objects.filter(user__isnull=False).select_related("user").first()
if existing_admin and (existing_admin.user.email or "").lower() != email:
    admin_email = existing_admin.user.email
    if not TAKE_OVER:
        log(f"this instance already has an administrator ({admin_email}) — leaving it alone.")
        log("a second owner is not something a bring-up hook gets to decide; to hand this instance to a")
        log(f"different person, set PLANE_OWNER_EMAIL={admin_email} in .env.")
        if not instance.is_setup_done:
            instance.is_setup_done = True
            instance.save()
            log("is_setup_done was still false — set it so that administrator can sign in.")
        result["skipped"] = "existing_admin"
        stop(0)
    # The handover. Declared AND explicit: the operator names whose instance this is
    # (PLANE_OWNER_EMAIL) and says it a second time with PLANE_OWNER_TAKE_OVER=1, because releasing an
    # administrator is not something a `bbox run` may conclude on its own — a typo in one variable
    # would otherwise move an instance out from under its owner. The old row is SOFT-deleted and named
    # in the output, so running again with the old address puts it back.
    existing_admin.delete()
    log(f"PLANE_OWNER_TAKE_OVER is set: released the administrator row of {admin_email}")
    problems.append(f"released {admin_email} as instance administrator (PLANE_OWNER_TAKE_OVER)")

# ── the owner ───────────────────────────────────────────────────────────────────────────────────
user = User.objects.filter(email=email).first()
if user is None:
    if not password:
        problems.append("no password supplied and no user to keep — the hook must mint one")
        log("; ".join(problems))
        stop()
    # `username` is a uuid, exactly as Plane's own sign-up view does it: the login is the email
    # (USERNAME_FIELD = "email"), and a derived username would collide with a person whose email
    # differs only in the parts a derivation drops.
    user = User(email=email, username=uuid.uuid4().hex, first_name=first_name, last_name=last_name,
                display_name=(f"{first_name} {last_name}".strip() or email),
                is_password_autoset=False, is_active=True, user_timezone=TIMEZONE,
                last_active=timezone.now(), last_login_time=timezone.now())
    user.set_password(password)
    user.save()
    created.append("user")
    log(f"created the owner {email}")
else:
    kept.append("user")
    # THE DECLARED PASSWORD WINS, even for an account that already exists. That is what turns "the
    # login lives in .env and the vault holds the same value" into a fact rather than a hope, and it
    # is the recovery path for a forgotten password (one command). The cost, stated plainly in
    # AGENT.md: a password changed INSIDE Plane is reverted by the next bring-up — change it in .env.
    # AN EXISTING OWNER KEEPS HIS PASSWORD. A person who registered himself chose those credentials,
    # and a bring-up that resets them every run would be an account takeover by configuration — the
    # hand-over (PLANE_OWNER_TAKE_OVER) changes his ROLE, not his secrets. To rotate deliberately,
    # say so: PLANE_OWNER_SET_PASSWORD=1 (and then read the value where every other one lives, the
    # credential plane's `project-pln-owner` row).
    if password and os.environ.get("PLANE_OWNER_SET_PASSWORD") == "1" and not user.check_password(password):
        user.set_password(password)
        user.save()
        kept.append("user(password)")
        log("set the owner's password from .env (PLANE_OWNER_SET_PASSWORD=1)")
    else:
        log(f"owner {email} already exists — password untouched "
            f"(set PLANE_OWNER_SET_PASSWORD=1 to rotate it)")

# A profile that exists but never finished onboarding opens on Plane's own onboarding screen, and its
# stored language overrides the Hebrew default. Both are corrected here rather than by a person.
profile, made = Profile.objects.get_or_create(
    user=user,
    defaults={"company_name": ws_name, "language": "he", "is_onboarded": True,
              "onboarding_step": ONBOARDING_DONE, "is_tour_completed": True,
              "is_navigation_tour_completed": True, "is_mobile_onboarded": True,
              "mobile_onboarding_step": MOBILE_ONBOARDING_DONE},
)
if made:
    created.append("profile")
else:
    fixed = []
    for field, value in (("is_onboarded", True), ("language", "he"), ("is_tour_completed", True),
                         ("is_navigation_tour_completed", True), ("is_mobile_onboarded", True),
                         ("onboarding_step", ONBOARDING_DONE),
                         ("mobile_onboarding_step", MOBILE_ONBOARDING_DONE)):
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            fixed.append(field)
    if fixed:
        profile.save()
        kept.append("profile(" + ",".join(fixed) + ")")
    else:
        kept.append("profile")

# The admin row is the ONE row here that cannot simply be re-created: its unique key is
# `(instance, user)` with NO `deleted_at` in it, so Plane's soft-deleted residue (the `objects`
# manager hides it, the index still holds it) turns a plain create into
# `duplicate key value violates unique constraint "instance_admins_instance_id_user_id_…"`.
# Measured on a scratch instance. So: revive it when it is there, create it only when it is not.
admin = InstanceAdmin.objects.filter(user=user, instance=instance).first()
if admin is not None:
    kept.append("instance_admin")
else:
    stale = InstanceAdmin.all_objects.filter(user=user, instance=instance).first()
    if stale is not None:
        stale.deleted_at = None
        stale.role = stale.role or 20
        stale.save()
        kept.append("instance_admin(revived)")
        log("revived this user's soft-deleted instance-admin row")
    else:
        InstanceAdmin.objects.create(user=user, instance=instance, role=20)
        created.append("instance_admin")

# ── the sign-up door: closed, because this instance HAS an owner now (DGO-14) ────────────────────
# `ENABLE_SIGNUP=0` in the compose is not enough on its own, and that is not obvious: the API's
# `enable_signup` comes from `get_configuration_value` — the `instance_configurations` TABLE first,
# the environment only as its default. This instance was registered on 2026-09-29 while the value
# was still "1", so the row says "1" and the flag kept reading true with the env saying 0 (measured
# 2026-10-01: `GET /api/instances/` → `enable_signup: true`, container env `ENABLE_SIGNUP=0`).
# An open registration form on a company host creates accounts, so it is closed here — the one
# moment it is safe, right after the declared owner exists (this line is only reached with one).
# `DISABLE_WORKSPACE_CREATION` is deliberately NOT touched: the owner may still open a workspace.
signup, made = InstanceConfiguration.objects.get_or_create(
    key="ENABLE_SIGNUP", defaults={"value": "0"})
if made:
    created.append("signup(off)")
    log("sign-up is now closed (ENABLE_SIGNUP=0) — the instance has an owner")
elif str(signup.value) != "0":
    was = signup.value
    signup.value = "0"
    signup.save()
    kept.append("signup(off)")
    log(f"closed the sign-up door: the instance configuration said ENABLE_SIGNUP={was!r}, and it "
        f"outranks the environment (which already said 0)")
    # `/api/instances/` caches its own body in Redis (`:1:/api/instances/`, TTL measured at 5945s on
    # 2026-10-01), so the flag a browser reads is the CACHED one: flipping the row without dropping
    # the key leaves the sign-up form enabled for up to ~100 minutes and reports the change as done.
    try:
        from django.core.cache import cache
        cache.delete("/api/instances/")
        log("dropped the cached /api/instances/ body so the flag flips now, not in 100 minutes")
    except Exception as e:                                       # noqa: BLE001
        problems.append(f"the sign-up flag changed but its cache entry could not be dropped "
                        f"({type(e).__name__}: {e}) — the API keeps answering the old value until "
                        f"the entry expires")
else:
    kept.append("signup(off)")

# ── the workspace ───────────────────────────────────────────────────────────────────────────────
ws, made = Workspace.objects.get_or_create(
    slug=ws_slug,
    defaults={"name": ws_name, "owner": user, "created_by": user, "organization_size": "1-10",
              "timezone": TIMEZONE},
)
(created if made else kept).append("workspace")
WorkspaceMember.objects.get_or_create(workspace=ws, member=user,
                                      defaults={"role": 20, "created_by": user})
# The DECLARED workspace belongs to the DECLARED owner. `Workspace.owner` is what the workspace
# settings screen shows and what "who owns this" answers; leaving it on a machine account while the
# person who actually uses Plane is only a member is the kind of half-migrated state that reads as a
# bug six months later. Only the declared workspace is touched — any other workspace on the instance
# (the owner's own, an abandoned test) is left exactly as it is.
if ws.owner_id != user.id:
    previous = ws.owner.email if ws.owner else None
    ws.owner = user
    ws.save()
    kept.append("workspace(owner)")
    log(f"workspace '{ws.slug}' now belongs to {email}" + (f" (was {previous})" if previous else ""))
# The profile remembers where the person last was; without it the web app opens on the workspace
# PICKER for a user who has exactly one workspace.
if profile.last_workspace_id != ws.id:
    profile.last_workspace_id = ws.id
    profile.save()
    log(f"profile points at workspace '{ws.slug}'")

# EVERY project in the declared workspace, not only the declared ones (DGO-10, measured 2026-10-01).
#
# Plane's permission is PER PROJECT: a workspace member without a `ProjectMember` row gets 403 from
# that project's issues — and the office's own API key IS the owner's token, so `spans.py` (the
# ‏כל-מקביל lane) and anything else reading project data through it goes blind on exactly the
# projects added later. Not hypothetical: after the hand-over the DGO project listed two members
# (the agent and the previous machine account) and NOT the owner, `GET …/projects/<id>/` answered
# `is_member: false`, the issues call answered 403, and the timeline collapsed from 36 spans to one.
# Projects arrive from the plan applier and from a human, so the invariant belongs here — where the
# owner is known and this script already runs on every bring-up.
for project in Project.objects.filter(workspace=ws):
    if not ProjectMember.objects.filter(project=project, member=user, workspace=ws).exists():
        ProjectMember.objects.get_or_create(project=project, member=user, workspace=ws,
                                           defaults={"role": 20, "created_by": user})
        created.append(f"project_member:{project.identifier}")
        log(f"added {email} as a member of project '{project.identifier}'")

# ── the first project, its states and its labels ────────────────────────────────────────────────
for p_cfg in cfg.get("projects") or []:
    ident = (p_cfg.get("identifier") or "GEN").strip()
    project, made = Project.objects.get_or_create(
        workspace=ws, identifier=ident,
        defaults={"name": p_cfg.get("name") or ident, "created_by": user, "timezone": TIMEZONE},
    )
    (created if made else kept).append(f"project:{ident}")
    # Project membership is not a formality: every project-scoped endpoint answers 403 for a
    # workspace member without this row, and the row's own save() is what creates the matching
    # ProjectUserProperty (it aggregates the member's project sort order).
    ProjectMember.objects.get_or_create(project=project, member=user, workspace=ws,
                                       defaults={"role": 20, "created_by": user})
    default_state = None
    for s_cfg in p_cfg.get("states") or []:
        state, made = State.objects.get_or_create(
            workspace=ws, project=project, name=s_cfg["name"],
            defaults={"group": s_cfg.get("group") or "backlog",
                      "color": s_cfg.get("color") or "#60646C",
                      "default": bool(s_cfg.get("default")),
                      "created_by": user},
        )
        (created if made else kept).append(f"state:{s_cfg['name']}")
        # State.save() derives the slug from the name, and slugify() strips Hebrew — so a Hebrew
        # state keeps an empty slug unless it is filled after the fact.
        if not state.slug and s_cfg.get("slug"):
            State.objects.filter(pk=state.pk).update(slug=s_cfg["slug"])
        if s_cfg.get("default"):
            default_state = state
    if project.default_state is None and default_state is not None:
        project.default_state = default_state
        project.save()
    for l_cfg in p_cfg.get("labels") or []:
        _label, made = Label.objects.get_or_create(
            workspace=ws, project=project, name=l_cfg["name"],
            defaults={"color": l_cfg.get("color") or "#60646C", "created_by": user},
        )
        (created if made else kept).append(f"label:{l_cfg['name']}")
    # The starting work items. ONCE, and only into an EMPTY project: this is a starting state, not a
    # content sync — re-creating them on every bring-up (or after the owner deletes one) would be the
    # hook fighting him. Wiring is deliberately minimal (name, state, priority) and a failure here is
    # reported, never fatal: the project and its states are what the office cannot work without.
    items = p_cfg.get("work_items") or []
    if items and not Issue.objects.filter(workspace=ws, project=project).exists():
        states = {st.name: st for st in State.objects.filter(workspace=ws, project=project)}
        try:
            from plane.db.models import Label as _L, IssueLabel  # noqa: F401  (label attach below)
        except Exception:                                            # noqa: BLE001
            IssueLabel = None
        for idx, i_cfg in enumerate(items, start=1):
            state = states.get(i_cfg.get("state")) or default_state
            try:
                issue = Issue(workspace=ws, project=project, name=i_cfg["name"], state=state,
                              priority=i_cfg.get("priority") or "none", created_by=user)
                issue.save(created_by_id=user.id, disable_auto_set_user=True)
                created.append(f"work_item:{i_cfg['name'][:18]}")
                for lname in i_cfg.get("labels") or []:
                    label = Label.objects.filter(workspace=ws, project=project, name=lname).first()
                    if label and IssueLabel is not None:
                        IssueLabel.objects.get_or_create(workspace=ws, project=project, issue=issue,
                                                         label=label, defaults={"created_by": user})
            except Exception as e:                                   # noqa: BLE001
                problems.append(f"could not create the starting item {i_cfg.get('name')!r}: "
                                f"{type(e).__name__}: {e}")
                break

instances: dict = {}
_listing, _code = vault("/api/instances")
if _code not in (200, 201):
    problems.append(f"the credential plane is unreachable at {VAULT} (HTTP {_code}) — the owner's "
                    "login and the office's key cannot be stored there (sign-in still works)")
else:
    instances = {i.get("id"): i for i in (_listing.get("instances") or [])}

origin = (os.environ.get("WEB_URL") or "http://plane.localhost:8080").rstrip("/")
# The deployment's own host: the agent accounts' addresses are `<slug>@<host>`, so nothing here
# assumes localhost — on the VPS this is the real domain, and the addresses follow it.
web_host = urllib.parse.urlparse(origin).hostname or "office.local"

# A PASSWORD IS STORED AS THE OWNER'S SIGN-IN ONLY WHEN IT IS HIS PASSWORD. An owner who keeps his
# own (DGO-13: "an existing owner keeps his password", above) is not signing in with whatever .env
# carries — and on an office that RECEIVED this instance from another one, .env carries a value that
# was minted here for nobody (hp-laptop, 2026-10-06: the Plane moved from the MacBook with its owner,
# and this office's line was the CI one). Writing that into the credential screen as "the owner's
# login" is handing him a password that opens nothing.
if password and not user.check_password(password):
    log("the owner keeps a password of his own — the one in .env is not his, and is not stored as his sign-in")
    password = ""
if _code in (200, 201):
    if password:
        vault_account("plane_local_admin-local", "plane_local_admin",
                      "Plane — כניסת בעל הלשכה",
                      {"kind": "password", "username": user.email, "password": password,
                       "base_url": origin, "host": origin},
                      f"{user.email} @ {origin}")
    else:
        log("no password of the owner's in this run — the stored sign-in is left untouched")
    token = office_api_token()
    vault_account("plane_local_api_token-local", "plane_local_api_token",
                  "Plane — מפתח ה־API של הלשכה",
                  {"kind": "pat", "token": token, "username": user.email,
                   "base_url": origin, "host": origin},
                  f"{OFFICE_TOKEN_LABEL} @ {origin}")
    # The console's credential screen shows PROVIDER ROWS, and a row's value comes from the vault
    # override or .env — so both secrets are also written as their row's value. Idempotent (the same
    # value every run) and it is what makes the screen read "נשמר" rather than "לא מוגדר" on an
    # office whose .env never heard of these keys. `POST /api/set/<cid>` is the screen's own edit
    # path, so this is the same write the owner's click makes.
    if password:
        vault("/api/set/project-pln-owner", "POST",
              {"field": "PLANE_OWNER_PASSWORD", "value": password})
    vault("/api/set/project-pln-api-key", "POST",
          {"field": "PLANE_LOCAL_API_TOKEN", "value": token})

# ── the office's agents, as accounts ────────────────────────────────────────────────────────────
# A plan file names an ASSIGNEE. For that name to mean a Plane member, the account has to exist, be
# a member of the declared workspace, hold a token the agent can act with, and be discoverable in the
# vault — so all four are created here, from the declaration, exactly like the owner's account.
for a_cfg in cfg.get("agents") or []:
    slug = (a_cfg.get("slug") or "").strip().lower()
    if not slug:
        continue
    a_name = a_cfg.get("name") or slug
    a_email = (a_cfg.get("email") or f"{slug}@{web_host}").lower()
    a_label = a_cfg.get("token_label") or f"{slug}-agent"
    # AN AGENT IS THE SAME AGENT WHEREVER THE INSTANCE RUNS: it is found by the label of its own key
    # before it is looked for by an address, because the address is derived from THIS deployment's
    # host. An instance that moved between offices kept the agent (`azaria@plane.console.localhost`,
    # his key, 70 work items assigned to him) and was then asked for `azaria@plane.localhost` — so a
    # second עזריה was created, with a second key, owning nothing (hp-laptop, 2026-10-06).
    held = APIToken.objects.filter(label=a_label, user__is_bot=False).select_related("user").first()
    a_user = held.user if held else User.objects.filter(email=a_email).first()
    if a_user is None:
        a_user = User(email=a_email, username=uuid.uuid4().hex, first_name=a_name,
                      display_name=a_name, is_password_autoset=True, is_active=True,
                      user_timezone=TIMEZONE)
        a_user.set_unusable_password()
        a_user.save()
        created.append(f"user:{slug}")
        log(f"created the agent account {a_email} ({a_name})")
    else:
        kept.append(f"user:{slug}")
    Profile.objects.get_or_create(
        user=a_user,
        defaults={"company_name": ws_name, "language": "he", "is_onboarded": True,
                  "onboarding_step": ONBOARDING_DONE, "is_tour_completed": True,
                  "is_navigation_tour_completed": True, "is_mobile_onboarded": True,
                  "mobile_onboarding_step": MOBILE_ONBOARDING_DONE})
    WorkspaceMember.objects.get_or_create(workspace=ws, member=a_user,
                                          defaults={"role": 15, "created_by": user})
    for proj in Project.objects.filter(workspace=ws):
        ProjectMember.objects.get_or_create(project=proj, member=a_user, workspace=ws,
                                            defaults={"role": 15, "created_by": user})
    a_token = APIToken.objects.filter(user=a_user, label=a_label).first()
    if a_token is None:
        a_token = APIToken.objects.create(label=a_label, user=a_user, user_type=0,
                                         description=f"{a_name} — the office's agent account")
        created.append(f"api_token:{slug}")
        log(f"minted {a_name}'s API key")
    else:
        kept.append(f"api_token:{slug}")
    if _code in (200, 201):
        # `user_id` is not decoration: plan.py resolves an assignee NAME to a Plane member by reading
        # this instance, and a token alone cannot be mapped back to the person who owns it.
        vault_account(f"plane_local_api_token-{slug}", "plane_local_api_token",
                      f"Plane — {a_name} (סוכן)",
                      {"kind": "pat", "token": a_token.token, "user_id": str(a_user.id),
                       "username": a_user.email, "base_url": origin, "host": origin},
                      f"{a_name} @ {origin}")

# ── the flag that makes sign-in possible at all, and the one that keeps it quiet ────────────────
if not instance.is_setup_done:
    instance.is_setup_done = True
    created.append("is_setup_done")
else:
    kept.append("is_setup_done")
if instance.instance_name in ("", "Plane Community Edition") and ws_name:
    instance.instance_name = ws_name
# Telemetry is off at the model default AND at both call sites (patches/no-phone-home.py); this keeps
# a row created before that patch honest too.
if instance.is_telemetry_enabled:
    instance.is_telemetry_enabled = False
    problems.append("telemetry was enabled on the instance row — turned it off")
instance.save()

result.update({
    "workspace": {"slug": ws.slug, "name": ws.name},
    "owner": {"email": user.email, "id": str(user.id)},
    "counts": {
        "users": User.objects.count(),
        "workspaces": Workspace.objects.count(),
        "projects": Project.objects.count(),
        "states": State.objects.count(),
        "labels": Label.objects.count(),
        "work_items": Issue.objects.count(),
    },
})
log(f"workspace '{ws.slug}' ({ws.name}) — {len(created)} created, {len(kept)} already in place")
stop(0)
