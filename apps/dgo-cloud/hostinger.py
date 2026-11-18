"""dgo-cloud.hostinger — the compute provider: buy a VPS, set it up with our install script, fence it, let it go.

Every path and field is from Hostinger's own OpenAPI spec (developers.hostinger.com/openapi/openapi.json, read
2026-11-14; research_notes/DGO cloud 2026-11-15/hostinger-api.md). Bearer token from hPanel → Profile → API; 90
requests a minute (we make a handful per node).

  create(name, script)  POST /api/vps/v1/post-install-scripts   (≤ 48 KB, runs once as /post_install, its output in
                                                                  /post_install.log)
                        POST /api/vps/v1/virtual-machines        item_id = a catalog PRICE id; setup = template,
                                                                  data center, the script, hostname, backups on.
                        200 → the VM; 202 → payment still processing: the VM is found later by its subscription_id,
                        and set up with POST …/{id}/setup once it reads `initial`.
  status(ref)           GET  /api/vps/v1/virtual-machines/{id}  → state (running/initial/error/…), ipv4
  fence(vm)             one firewall «dgo-cloud» for every node: 80 and 443 from anywhere, 22 only from the
                        addresses DGOCLOUD_SSH_FROM names (Bina's own); Hostinger's firewall drops everything else.
  release(ref)          DELETE /api/billing/v1/subscriptions/{id} — the server is not renewed (its data is gone with
                        it; the provisioner calls this only after the keep days).
The catalog (prices) and the templates/data centers are read live and cached for the process.
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("HOSTINGER_API_BASE", "https://developers.hostinger.com").rstrip("/")


class ProviderError(Exception):
    """`unknown` is True when the provider may have DONE it (a purchase that timed out): never tried again blindly."""

    def __init__(self, msg, unknown=False):
        super().__init__(msg)
        self.unknown = unknown


class Hostinger:
    name = "hostinger"

    def __init__(self, token=None, item=None, template=None, datacenters=None, ssh_from=None):
        self.token = token or os.environ.get("HOSTINGER_API_TOKEN", "")
        # KVM 2 billed monthly: the smallest plan a whole office fits in (8 GB; vps1 runs one in 7 GB at 6 used)
        self.item = item or os.environ.get("HOSTINGER_ITEM", "hostingercom-vps-kvm2-usd-1m")
        self.template = (template or os.environ.get("HOSTINGER_TEMPLATE", "Ubuntu 24.04")).lower()
        # Germany, then France, then Lithuania: the VPS locations nearest Israel (Hostinger has no VPS in the NL)
        self.dcs = [d.strip().lower() for d in (datacenters or os.environ.get("HOSTINGER_DATACENTERS", "de,fr,lt"))
                    .split(",") if d.strip()]
        self.ssh_from = [a.strip() for a in (ssh_from or os.environ.get("DGOCLOUD_SSH_FROM", "")).split(",")
                         if a.strip()]
        self._cache = {}

    def configured(self):
        return bool(self.token)

    def _call(self, method, path, body=None, timeout=60, retry=True):
        """retry=False for a call that SPENDS (the purchase): a timeout there may be a server bought, so it is raised
        as unknown instead of asked again — four tries could buy four servers and track one (the second reader's #8)."""
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(4 if retry else 1):
            req = urllib.request.Request(BASE + path, data=data, method=method, headers={
                "Authorization": "Bearer " + self.token, "Content-Type": "application/json",
                "Accept": "application/json", "User-Agent": "dgo-cloud/1"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                    return r.status, (json.loads(raw) if raw else {})
            except urllib.error.HTTPError as e:
                raw = e.read()
                if e.code in (429, 409) and attempt < 3 and retry:
                    time.sleep(min(int(e.headers.get("Retry-After") or 5), 30))
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    d = {"message": raw[:200].decode("utf-8", "replace")}
                errs = d.get("errors")
                raise ProviderError(f"hostinger {method} {path}: HTTP {e.code} {d.get('message', '')}"
                                    + (f" {json.dumps(errs, ensure_ascii=False)[:300]}" if errs else ""))
            except (OSError, ValueError) as e:
                if not retry:
                    raise ProviderError(f"hostinger {method} {path}: no answer ({e}) — it may have happened", True)
                if attempt < 3:
                    time.sleep(3)
                    continue
                raise ProviderError(f"hostinger {method} {path}: {e}")

    # ── what can be bought ───────────────────────────────────────────────────────────────────────────
    def catalog(self):
        if "catalog" not in self._cache:
            _, d = self._call("GET", "/api/billing/v1/catalog?category=VPS")
            self._cache["catalog"] = d if isinstance(d, list) else []
        return self._cache["catalog"]

    def price_of(self, item_id=None):
        """{'id', 'name', 'currency', 'price' (cents), 'first_period_price', 'period', 'period_unit'} or None."""
        item_id = item_id or self.item
        for it in self.catalog():
            for p in it.get("prices") or []:
                if p.get("id") == item_id:
                    return dict(p, plan=it.get("name"))
        return None

    def template_id(self):
        if "template" not in self._cache:
            _, d = self._call("GET", "/api/vps/v1/templates")
            rows = d if isinstance(d, list) else []
            # a plain OS — never a template with a panel (they bring their own web server onto 80/443)
            plain = [t for t in rows if self.template in (t.get("name") or "").lower()
                     and not any(w in (t.get("name") or "").lower() for w in ("panel", "cpanel", "with", "plesk"))]
            if not plain:
                raise ProviderError(f"no Hostinger template named like {self.template!r}")
            self._cache["template"] = plain[0]["id"]
        return self._cache["template"]

    def datacenter_id(self):
        if "dc" not in self._cache:
            _, d = self._call("GET", "/api/vps/v1/data-centers")
            rows = d if isinstance(d, list) else []
            for want in self.dcs:
                hit = [x for x in rows if (x.get("location") or "").lower() == want]
                if hit:
                    self._cache["dc"] = (hit[0]["id"], f"{hit[0].get('city') or ''} {want}".strip())
                    break
            else:
                if not rows:
                    raise ProviderError("Hostinger lists no data center")
                self._cache["dc"] = (rows[0]["id"], rows[0].get("city") or rows[0].get("location") or "")
        return self._cache["dc"]

    def payment_method(self):
        _, d = self._call("GET", "/api/billing/v1/payment-methods")
        usable = [m for m in (d if isinstance(d, list) else []) if not m.get("is_expired") and not m.get("is_suspended")]
        default = [m for m in usable if m.get("is_default")]
        return (default or usable or [None])[0]

    # ── one server ───────────────────────────────────────────────────────────────────────────────────
    def create(self, name, hostname, script):
        """Buy and set up one VPS → {'ref': 'vm:<id>' | 'sub:<subscription_id>', 'datacenter', 'plan', 'script_id'}."""
        if len(script.encode()) > 48 * 1024:
            raise ProviderError("the install script is over Hostinger's 48 KB")
        _, s = self._call("POST", "/api/vps/v1/post-install-scripts", {"name": f"dgo-cloud {name}", "content": script})
        dc, dc_name = self.datacenter_id()
        setup = {"template_id": self.template_id(), "data_center_id": dc, "post_install_script_id": s["id"],
                 "hostname": hostname, "enable_backups": True, "install_monarx": False}
        body = {"item_id": self.item, "setup": setup}
        pm = self.payment_method()
        if pm:
            body["payment_method_id"] = pm["id"]
        code, d = self._call("POST", "/api/vps/v1/virtual-machines", body, timeout=120, retry=False)
        if code == 202 or "virtual_machine" not in d:
            sub = d.get("subscription_id") or (d.get("order") or {}).get("subscription_id")
            if not sub:
                raise ProviderError(f"purchase answered {code} with no subscription id: {str(d)[:200]}")
            return {"ref": f"sub:{sub}", "datacenter": dc_name, "plan": self.item, "script_id": s["id"],
                    "setup": setup}
        vm = d["virtual_machine"]
        return {"ref": f"vm:{vm['id']}", "datacenter": dc_name, "plan": vm.get("plan") or self.item,
                "script_id": s["id"], "setup": setup}

    def status(self, ref, setup=None):
        """→ {'ref' (vm:<id> once known), 'state', 'ip'}. A purchase still paying is found by its subscription and
        set up here once Hostinger shows it `initial`."""
        if ref.startswith("sub:"):
            _, vms = self._call("GET", "/api/vps/v1/virtual-machines")
            hit = [v for v in (vms if isinstance(vms, list) else []) if v.get("subscription_id") == ref[4:]]
            if not hit:
                return {"ref": ref, "state": "paying", "ip": ""}
            vm = hit[0]
            if vm.get("state") == "initial" and setup:
                self._call("POST", f"/api/vps/v1/virtual-machines/{vm['id']}/setup", setup, timeout=120)
            ref = f"vm:{vm['id']}"
        _, vm = self._call("GET", f"/api/vps/v1/virtual-machines/{ref[3:]}")
        ip = ((vm.get("ipv4") or [{}])[0] or {}).get("address", "")
        state = vm.get("state", "")
        if state == "running" and vm.get("actions_lock") == "locked":
            state = "starting"
        return {"ref": ref, "state": state, "ip": ip, "subscription": vm.get("subscription_id", "")}

    def fence(self, ref):
        """The one firewall every node shares, created once, then turned on for this VM."""
        if not ref.startswith("vm:"):
            return
        _, fws = self._call("GET", "/api/vps/v1/firewall")
        rows = fws.get("data", fws) if isinstance(fws, dict) else fws
        fw = next((f for f in rows or [] if f.get("name") == "dgo-cloud"), None)
        rules = [{"protocol": "TCP", "port": "80", "source": "any", "source_detail": "any"},
                 {"protocol": "TCP", "port": "443", "source": "any", "source_detail": "any"},
                 {"protocol": "UDP", "port": "443", "source": "any", "source_detail": "any"}]
        rules += [{"protocol": "TCP", "port": "22", "source": "custom", "source_detail": a} for a in self.ssh_from]
        if not fw:
            _, fw = self._call("POST", "/api/vps/v1/firewall", {"name": "dgo-cloud"})
        self._call("PUT", f"/api/vps/v1/firewall/{fw['id']}/rules", {"rules": rules, "sync": True})
        self._call("POST", f"/api/vps/v1/firewall/{fw['id']}/activate/{ref[3:]}")

    def snapshot(self, ref):
        if ref.startswith("vm:"):
            self._call("POST", f"/api/vps/v1/virtual-machines/{ref[3:]}/snapshot")

    def release(self, ref, subscription=""):
        sub = subscription
        if not sub and ref.startswith("vm:"):
            sub = self.status(ref).get("subscription", "")
        if ref.startswith("sub:"):
            sub = ref[4:]
        if not sub:
            raise ProviderError(f"no subscription to cancel for {ref}")
        self._call("DELETE", f"/api/billing/v1/subscriptions/{sub}")

    def forget_script(self, script_id):
        try:
            self._call("DELETE", f"/api/vps/v1/post-install-scripts/{script_id}")
        except ProviderError:
            pass


class Simulated:
    """A provider for a laptop and the tests: a «server» appears at once on 127.0.0.1 and its install is whatever
    agent.py --simulate does when pointed at this front. It never spends money."""
    name = "simulate"

    def __init__(self):
        self.n = 0

    def configured(self):
        return True

    def price_of(self, item_id=None):
        return {"id": "simulate", "currency": "USD", "price": 0, "period": 1, "period_unit": "month", "plan": "sim"}

    def create(self, name, hostname, script):
        self.n += 1
        # the «server» is tests/sim_node.py: it reads the install script it was given here and runs the real agent
        d = os.environ.get("DGOCLOUD_DATA")
        if d and os.path.isdir(d):
            with open(os.path.join(d, f"sim-{name}.sh"), "w") as f:
                f.write(script)
        return {"ref": f"vm:sim-{name}", "datacenter": "local", "plan": "simulate", "script_id": 0, "setup": {}}

    def status(self, ref, setup=None):
        return {"ref": ref, "state": "running", "ip": "127.0.0.1"}

    def fence(self, ref):
        pass

    def snapshot(self, ref):
        pass

    def release(self, ref, subscription=""):
        pass

    def forget_script(self, script_id):
        pass


def provider():
    kind = os.environ.get("DGOCLOUD_PROVIDER", "hostinger")
    if kind == "simulate":
        return Simulated()
    if kind == "off":
        return None
    return Hostinger()
