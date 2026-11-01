# Securing Docker Compose apps on a VPS — the owner's exported conversation (verbatim)

The owner handed this document to the office on 2026-10-09. It is an exported Claude conversation of
6 October 2026, «Securing WordPress and Docker Compose Apps on a VPS», kept here **verbatim** because
it is the reference the office's security layers are designed against (work item `ccw-…`/`DGO-461`
and the `sec-*` family). The original PDF is committed beside it: `dgo-security-session.pdf`.

Read it as a source, not as a plan: the office implements the DGO way — every layer declared in an
app's `app.json` and compiled by `platform/manager/reconcile.py`, every event reported as a span to
`any-concurrency` («כל מקביל», the office's own collector: `POST /ingest/span`), and Raphael's
scheduled automations consuming that timeline. Where this document names a tool (Falco, Tetragon,
Vector, Trivy, cosign, docker-bench-security), the question for us is which of them earns its place
in a deployment that already has a compiler, a credential plane, an edge with SSO and a collector.

---
=== page 1 ===
Page 1
Securing WordPress and Docker Compose Apps
on a VPS
Exported conversation with Claude, 6 October 2026
Question 1
How much secure is running WordPress with like a default Docker Compose and traffic on a VPS? So
how, like, what are the measures that someone can get into the WordPress or to running code on the
VPS? How safe is it? And like, what are the standards? Like, when is it? When can it be called
secured?
Answer
A default WordPress Docker Compose setup on a VPS is 
reasonably safe against random attacks but
not hardened
. The containers themselves rarely get broken. The real risks are WordPress plugins, weak
logins, and how the VPS itself is exposed.
How attackers actually get in (most to least common)
\177
Vulnerable plugins or themes.
 This causes about 90% of WordPress compromises. An outdated
plugin with a file-upload or SQL injection bug lets attackers run PHP code inside the container.
\177
Brute-forced logins.
 These target wp-admin, xmlrpc.php, or SSH with password login enabled.
\177
Exposed services.
 A common one is the MySQL port published to the internet in the compose file
(
ports: 3306:3306
).
\177
Weak or default secrets.
 Examples are example passwords copied from compose tutorials and the
root DB password reused everywhere.
\177
Container escape to the host.
 This is rare, but it becomes possible if you mount
/var/run/docker.sock
, run containers 
privileged
, or mount host folders writable.
\177
Unpatched host OS or Docker.
 Old kernels and old Docker versions have known exploits.
Note that Docker publishes ports by bypassing UFW firewall rules. Many people think their firewall blocks
a port when it doesn't.
Hardening checklist
\177
Don't publish the DB port; keep MySQL on an internal Docker network only.
\177
Put a reverse proxy (Caddy, Traefik, or Nginx) in front with HTTPS, and only expose ports 80 and 443.
\177
SSH should use keys only, with password login and root login disabled. Fail2ban or CrowdSec adds
protection.
\177
Keep plugins minimal and auto-update WordPress core, plugins, and themes. Delete unused plugins.
\177
Add 
DISALLOW_FILE_EDIT
 in wp-config, block or rate-limit xmlrpc.php, and use 2FA on admin accounts.
\177
Use strong unique passwords in a 
.env
 file, not hardcoded in the compose file.
\177
Pin image versions and update them regularly. Enable unattended security updates on the host.
\177
Optionally add a WAF like Cloudflare or Wordfence.
\177
Keep automated 
offsite
 backups of the database and wp-content, and test restoring them.
When can it be called "secure"?
=== page 2 ===
Page 2
Nothing is ever fully secure. In practice, a setup counts as reasonably secure when its attack surface is
minimal, everything is patched on a schedule, access requires strong authentication, and you can detect
and recover from a breach. Good reference standards are the 
CIS Benchmarks
 (for Docker and Linux),
OWASP Top 10
 (for web apps), and the official 
WordPress Hardening guide
. For a personal or small
business site, the checklist above already puts you ahead of the vast majority of WordPress installs.
Question 2
So plug-ins and open source code I stalled on vps is the main challenge? Outside automated and
humen pentaton attempts will fail ? Can the containers strictly and reliable block internet access or route
all to proxy that blocks any un intendendt io
Answer
Yes, third-party code is the main risk.
 Once a hardened setup leaves only ports 80/443 open with
key-only SSH, most automated scans and casual pentest attempts will fail. "Will fail" isn't a guarantee,
though. A skilled attacker still has these options:
\177
A zero-day or unpatched bug in WordPress core, a plugin, or PHP
\177
Stolen credentials, such as a phished admin password or a leaked SSH key
\177
Your own mistakes, like a forgotten exposed port, a test plugin left active, or an old backup file in the
web root
\177
Supply chain attacks, where a legitimate plugin gets sold or hijacked and pushes a malicious update
Can containers be reliably blocked from the internet?
 Yes, and it's one of the best hardening steps,
because most real attacks need outbound access to download payloads, phone home, or exfiltrate data.
1
Fully block it.
 A Docker network with 
internal: true
 has no route to the internet at all, and this is
reliable because it's enforced at the kernel level. Put the DB there, and WordPress too if it never needs
outbound.
2
Route through an allowlist proxy.
 WordPress usually needs some outbound access for updates,
plugin downloads, and SMTP. Put WordPress on an internal network and add a proxy container like
Squid or Tinyproxy, which is the only container attached to both networks. Allow just
api.wordpress.org
, 
downloads.wordpress.org
, and your mail provider. Then point WordPress at it
in wp-config with 
WP_PROXY_HOST
 and 
WP_PROXY_PORT
.
3
Add host firewall rules
 in the 
DOCKER-USER
 iptables chain to drop any container egress you didn't
intend. This acts as a second layer if the compose file is ever misconfigured.
There are a few gaps to cover. 
DNS
 can be used to sneak data out, so give internal containers no external
DNS resolver, or use a filtering one. 
Container-to-container
 traffic still works on shared networks, so split
the networks: the proxy reaches WordPress, WordPress reaches the DB, and the proxy never reaches the
DB. Finally, 
inbound traffic is separate
: your reverse proxy needs its own network bridge to WordPress,
which internal networks allow.
With egress locked down, a compromised plugin can still deface the site or mess with the database. But it
struggles to download tools, join a botnet, or send your data anywhere, which turns most breaches from
disasters into cleanups.
Question 3
I want contolability and objervability of every app with a compose so I can see exactly what its
accessing and network and files and services and basically everything moving reliably collected and
gated. Let's say I have 3 apps each having a compose with multiple servicerices. So 4th app that
collects everything moving on the apps and lets gating anything basically
=== page 3 ===
Page 3
Answer
Yes, this is buildable, and it's a known pattern: put all three apps in a sandbox where every exit passes
through a gate you own, then watch the host kernel for everything else. Network traffic is the easiest to see
and block. Files and processes need a kernel-level sensor.
App 1 compose
Internal network only
App 2 compose
Internal network only
App 3 compose
Internal network only
Egress proxy
Allowlist, logs requests
DNS filter
Logs every lookup
Socket proxy
Limits Docker API
eBPF sensor on host (Tetragon or Falco)
Files, processes, connections, can kill
Collector and dashboards
Vector to Loki, Prometheus, Grafana, alerts
What each layer gives you
\177
Network (most reliable).
 Every app runs on 
internal: true
 networks, so the only way out is the
egress proxy and DNS filter. You get a log of every destination and can allow or deny each one per app.
For HTTPS you see the domain (via SNI) but not the content unless you run a TLS-intercepting proxy
like mitmproxy with its CA trusted inside the containers.
\177
Files and processes.
 Tetragon or Falco hook the kernel with eBPF, so they see every file open,
process spawn, and connection from any container, and apps can't hide from them. Falco only alerts.
Tetragon can also enforce, killing a process that, say, writes to 
/var/www
 or spawns a shell.
\177
Gating files without a sensor.
 Use 
read_only: true
 root filesystems, mount only the volumes each
service needs, and drop capabilities (
cap_drop: ALL
). This blocks most unintended writes at zero cost.
\177
Docker API.
 Never give any app the raw Docker socket. The socket proxy exposes only read-only calls
to the tools that need them.
\177
Container resources and logs.
 cAdvisor provides CPU, memory, and IO per container, and Docker's
own logs ship through Vector.
Two warnings
1
The 4th "watcher" app is the most powerful thing on the box, because it runs privileged on the host.
Keep it on its own network, with no inbound internet access to its dashboards except through a VPN or
SSH tunnel. If it's compromised, everything is.
=== page 4 ===
Page 4
2
Start in 
observe mode
: log for a week or two to learn what each app normally touches, then turn rules
into blocks. Enforcing from day one breaks updates, mail, and cron jobs in confusing ways.
Question 4
Deeply investigate on making it reliable so no one can overwrite or interfere or disrupt or overwrite
anything ever. And tell me more about etbf and tetragon falco etc
Answer
No setup can guarantee "no one can ever interfere." 
Anyone who gets root on the host, or controls the
hypervisor (your VPS provider), can in principle disable anything running on that machine,
including the sensors.
 So the realistic goal has three parts: make getting root extremely hard, make
tampering impossible to hide, and make sure the record of what happened lives somewhere the attacker
can't reach.
1. Keep attackers from reaching host root
\177
Rootless Docker or 
userns-remap
.
 Root inside a container then maps to an unprivileged user on the
host, so a container escape lands as "nobody."
\177
Lock down every app container.
 Set 
read_only: true
, 
cap_drop: ALL
, 
no-new-privileges
, keep
the default seccomp profile, add an AppArmor profile, never use 
privileged
, and never mount the
Docker socket.
\177
Use an immutable host OS
 like Flatcar or Fedora CoreOS. 
/usr
 is read-only and updates are atomic
images, so an attacker can't quietly replace system binaries.
\177
Turn on kernel lockdown (integrity mode).
 It blocks loading unsigned kernel modules and writing to
kernel memory, closing the classic rootkit paths.
\177
Harden admin access.
 Use SSH with hardware keys (FIDO2) or short-lived SSH certificates, no
passwords, and ideally SSH reachable only over a VPN like WireGuard or Tailscale.
2. Make config impossible to overwrite silently
\177
Keep all compose files, Tetragon policies, and proxy allowlists in 
git with signed commits
, deployed
by a pull-based job, never edited by hand on the server.
\177
Pin images by digest
 (
image: x@sha256:...
) and verify signatures with cosign, so an image can't be
swapped under the same tag.
\177
Run 
drift detection
: a timer compares running containers and config files against git and alerts on any
difference.
\177
Have Tetragon itself watch and block writes to 
/etc/docker
, the compose directories, and its own
policy folder.
3. Make the evidence tamper-proof
\177
Ship logs off the box in real time
 to a separate machine or service. Attackers can delete local logs,
but not ones already sent.
\177
Store them 
append-only
, for example S3-compatible storage with Object Lock, so even you can't
delete them for N days.
\177
Set up a 
dead-man's switch
: an external monitor alerts you if the sensor or collector 
stops
 sending
heartbeats. Silencing the watcher then becomes the alarm.
\177
Keep 
immutable offsite backups
 so you can always rebuild from a known good state.
4. Resist disruption (DoS)
=== page 5 ===
Page 5
\177
Put Cloudflare or your provider's DDoS protection in front.
\177
Set per-container limits (
mem_limit
, 
cpus
, 
pids_limit
) so one app can't starve the others or the
sensors.
\177
Give the monitoring stack reserved resources and 
restart: always
.
What eBPF actually is
eBPF lets you load small programs into the Linux kernel that run when specific events happen: a file
opens, a process starts, a network connection is made. Before loading, the kernel's 
verifier
 proves each
program is safe (it can't crash the kernel or loop forever). Since every container shares the host kernel, an
eBPF sensor sees everything every container does, and a process inside a container cannot hide from it
or turn it off without host root.
Tetragon
Tetragon is a CNCF project under Cilium that provides security observability and runtime enforcement
using eBPF. Its key strength is that it applies policy and filtering directly in eBPF in the kernel, so it doesn't
just report a bad action, it can stop it at the moment it happens. For example, it can kill a process that tries
to write to a protected path. You write rules as YAML "TracingPolicies" that say which kernel functions to
watch, which arguments to match, and what action to take. Kubernetes is the main target, but you can run
it with plain Docker, where it starts in a privileged container, which suits a compose setup.
Falco
Falco is the older, CNCF-graduated project from Sysdig. It's 
detection only
: it watches syscalls and raises
alerts based on a large ready-made ruleset ("shell spawned in container," "write below /etc," "unexpected
outbound connection"). It's easier to start with because the default rules catch common attacks out of the
box, and Falcosidekick forwards alerts to Slack, Loki, webhooks, and more.
Others worth knowing
\177
Tracee
 (Aqua) is similar to Falco, with strong forensic detail.
\177
KubeArmor
 enforces through LSM hooks (AppArmor or BPF-LSM), which suits per-container
allow-only policies.
\177
auditd
 is the classic Linux audit system: no eBPF, heavier, but a widely accepted compliance record.
Recommended combination
Run Falco for broad detection with good defaults, and Tetragon for targeted enforcement on your crown
jewels: config folders, the Docker socket, and the sensor's own files. Ship both outputs off-host to
append-only storage, with a heartbeat alert. The sensors themselves run privileged, so treat their images
and policies with the same signing and pinning discipline as everything else.
Question 5
What is the official playback for docker compose public exposure of private and public apps on a vps
(some with password some fully public like website). I need the latest official playbook on securing it
Answer
There is 
no single official "playbook"
 for this. In practice, four sources together form the recognized
standard:
\177
Docker's own docs
, especially "Packet filtering and firewalls," "Port publishing," "Rootless mode," and
"Docker Engine security"
\177
CIS Docker Benchmark.
 The latest is version 1.8.0, available to CIS SecureSuite members; older
versions are free as PDFs for non-commercial use.
=== page 6 ===
Page 6
\177
OWASP Docker Security Cheat Sheet
, free and practical
\177
NIST SP 800-190
 (Application Container Security Guide), the formal government reference
The consolidated playbook for mixed public and private apps
1. One front door.
 Only a reverse proxy (Caddy or Traefik) publishes ports, and only 80 and 443. No app
container has a 
ports:
 line. Apps join a shared "edge" network that only the proxy also joins, and their
databases sit on separate internal networks.
2. Don't trust your firewall to cover Docker.
 Docker's official docs warn that Docker and ufw are
incompatible, because published container traffic is rerouted before ufw's rules ever see it. The official fix
is to filter in the 
DOCKER-USER
 chain, which Docker leaves for your own rules. If you must publish a port for
debugging, bind it to 
127.0.0.1:port
 only.
3. Public apps (like the website).
 Proxy to app with HTTPS, security headers, rate limiting, and ideally
Cloudflare in front for DDoS protection and a WAF.
4. Private apps (password-protected).
 In order of strength:
\177
Best:
 Don't expose them at all. Reach them only over WireGuard or Tailscale.
\177
Good:
 Put a zero-trust gate like Cloudflare Access in front.
\177
Minimum:
 Add an SSO gate with 2FA at the proxy (Authelia, Authentik, or oauth2-proxy), so attackers
never even reach the app's own login page. An app's built-in password alone isn't enough, since login
bugs are common.
\177
Admin tools (Portainer, phpMyAdmin, Grafana) should never be public under any option.
5. Per-container hardening.
 This is the OWASP and CIS core: non-root user, 
read_only: true
,
cap_drop: ALL
, 
no-new-privileges:true
, resource limits, no 
privileged
, no Docker socket mounts,
and secrets in files rather than environment variables.
6. Images.
 Pin images by digest and scan them (Trivy or Docker Scout). Use cosign for signatures, since
Docker officially retired its older Content Trust signing.
7. Host.
 Use rootless Docker or 
userns-remap
, automatic security updates, key-only SSH behind a VPN,
and logs shipped off-host.
8. Verify, don't assume.
 Run 
docker-bench-security
 (or CIS-CAT) against the host. Also scan your
VPS from outside with 
nmap
 to confirm only 80 and 443 answer, which catches the Docker firewall bypass
immediately.
Sources referenced
\177
Docker docs: docs.docker.com/engine/network/packet-filtering-firewalls/
\177
CIS Docker Benchmark: cisecurity.org/benchmark/docker
\177
Tetragon: github.com/cilium/tetragon
\177
OWASP Docker Security Cheat Sheet: cheatsheetseries.owasp.org
\177
NIST SP 800-190: csrc.nist.gov
