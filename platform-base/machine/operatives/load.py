#!/usr/bin/env python3
"""The machine's overview (GET /api/overview), as ONE line an agent can say: load against cores, CPU,
memory, disk, unhealthy containers, and the host under a VM when it is short.

The machine recipe pipes into it — `curl -s http://machine:8080/api/overview | python3
platform-base/machine/operatives/load.py`, or the same path through `./bbox remote <office> machine …`,
whose first line (`HTTP <status>  GET <url>`) it skips and whose office it names. The overview is
~150 KB (every container, the disk's breakdown, the history): read whole, the fields that matter sit
in the middle a model's context cuts out. An answer that is not an overview is printed as it came and
exits 1, so a machine that did not answer is never reported as an idle one.
"""
import json
import re
import sys


def gb(n):
    return f"{(n or 0) / 1e9:.1f} GB"


def main():
    text = sys.stdin.read()
    office = ""
    if text.startswith("HTTP "):
        head, _, text = text.partition("\n")
        m = re.search(r"//[a-z0-9-]+\.([a-z0-9-]+)[:/]", head)
        office = m.group(1) if m else ""
    try:
        doc = json.loads(text)
        cpu, mem = doc["cpu"], doc["memory"]
        if not isinstance(cpu, dict) or not isinstance(mem, dict):      # {"cpu": null} is no overview
            raise TypeError
    except (ValueError, KeyError, TypeError):
        print((text or "(no answer)")[:600])
        return 1
    load, cores = cpu.get("load1"), cpu.get("cores") or 0
    busy = load is not None and cores and load > cores
    pct = cpu.get("percent")
    disk = ((doc.get("storage") or {}).get("root") or {}).get("percent")
    unhealthy = (doc.get("docker") or {}).get("containers_unhealthy") or 0
    # a part the overview did not carry is said as not measured, never as "None"
    parts = [
        f"load {load} on {cores} cores" + (" (busy)" if busy else "") if load is not None else "load not measured",
        f"CPU {pct}%" if pct is not None else "CPU not measured yet",
        # an unreadable /proc/meminfo answers total 0 and percent 0 (app.py _mem_info): not "0% used"
        f"memory {mem['percent']}% ({gb(mem.get('available'))} free)"
        if mem.get("percent") is not None and mem.get("total") else "memory not measured",
        f"disk {disk}%" if disk is not None else "disk not measured",
    ]
    if unhealthy:
        parts.append(f"{unhealthy} unhealthy container(s)")
    vm = doc.get("vm_host") or {}
    if vm.get("short"):
        parts.append(f"the host under the VM is short of memory ({gb(vm.get('mem_free'))} free)")
    print((f"{office}: " if office else "") + ", ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
