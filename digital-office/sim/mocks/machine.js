/* Mock backend for machine (מכונה) — serves a healthy host + nine running containers and one exited job so
   the real UI (static/index.html + app.js inline script) runs standalone with no FastAPI
   backend / docker socket. Real UI code is untouched; only window.fetch is intercepted.
   Endpoints (relative, as the app calls them): GET api/overview, GET api/cleanup/options,
   POST api/cleanup/:action. Polled ~every 5s by the real page. */
(function(){
  function rnd(a,b){ return a + Math.random()*(b-a); }
  function clamp(v,a,b){ return Math.max(a,Math.min(b,v)); }
  function jitter(v,amt,lo,hi){ return clamp(v + rnd(-amt,amt), lo==null?0:lo, hi==null?100:hi); }

  // ── static "healthy host" baseline ─────────────────────────────────────────
  var GB = 1024*1024*1024;
  var MEM_TOTAL = 16*GB, DISK_TOTAL = 200*GB;
  var startedAt = Date.now();

  // per-container baseline (name -> [image, cpuBase, memMB, health|null, status — 'running' when not said])
  var CONTAINERS = [
    ['traefik',      'traefik:v3.3',                    1.2,  48,  null],
    ['n8n',          'n8nio/n8n:1.68.0',                6.5,  620, 'healthy'],
    ['n8n-postgres', 'postgres:17-alpine',              2.1,  180, 'healthy'],
    ['supabase-db',  'supabase/postgres:15.6.1.146',    3.4,  310, 'healthy'],
    ['redis',        'redis:7-alpine',                  0.6,  32,  'healthy'],
    ['apitools',     'apitools:latest',                 4.8,  410, null],
    ['my-docs',      'my-docs:latest',                  1.8,  150, null],
    ['mailview',     'mailview:latest',                 1.0,  95,  null],
    // what a real office also has, and a screen has to survive: a name longer than its column, and a
    // job that ran once and exited (a healthy office keeps a handful of those)
    ['browser42-task-watchdog', 'browser42-watchdog:latest',         0.9, 18, null],
    ['authentik-bootstrap',     'ghcr.io/goauthentik/server:2025.2', 0,   0,  null, 'exited']
  ];
  var RUNNING = CONTAINERS.filter(function(row){ return !row[5]; }).length;

  function makeContainers(){
    var now = Date.now();
    return CONTAINERS.map(function(row, i){
      var name = row[0], image = row[1], cpuBase = row[2], memMB = row[3], health = row[4], up = !row[5];
      var cpu = up ? Math.round(jitter(cpuBase, cpuBase*0.35, 0.1, 95) * 100) / 100 : 0;
      var memUsed = up ? Math.round(memMB * (1 + rnd(-0.06,0.06)) * 1024*1024) : 0;
      var memLimit = MEM_TOTAL;
      return {
        id: 'sim' + (100000+i).toString(16),
        name: name,
        raw_name: name + '-bina-deployment',
        image: image,
        status: row[5] || 'running',
        health: health,
        started_at: new Date(startedAt - (i+1)*3600*1000).toISOString(),
        restart_count: 0,
        labels: {},
        cpu_percent: cpu,
        memory: { used: memUsed, limit: memLimit, percent: Math.round((memUsed/memLimit*100)*10)/10 },
        pids: up ? Math.round(jitter(8 + i*3, 4, 1, 200)) : 0,
        net: up ? { rx: Math.round(rnd(2e6, 9e8)), tx: Math.round(rnd(1e6, 4e8)) } : { rx: 0, tx: 0 }
      };
    });
  }

  // ── rolling history for the resource chart (server normally keeps ~180 pts
  //    @10s ≈ 30min; seed a chunk then keep appending so the chart breathes) ──
  var HISTORY_MAX = 180;
  var history = [];
  (function seedHistory(){
    var n = 60, now = Date.now();
    var cpu = 22, mem = 38, disk = 41, rx = 4e5, tx = 1.5e5;
    for (var i = n; i > 0; i--){
      cpu = jitter(cpu, 4, 4, 70); mem = jitter(mem, 1.5, 20, 70); disk = jitter(disk, 0.3, 20, 70);
      rx = clamp(rx + rnd(-1e5,1e5), 5e4, 5e6); tx = clamp(tx + rnd(-4e4,4e4), 2e4, 2e6);
      history.push({ t: Math.round((now - i*10000)/1000)*1, cpu: Math.round(cpu*10)/10,
                     mem: Math.round(mem*10)/10, disk: Math.round(disk*10)/10,
                     running: RUNNING, rx: Math.round(rx), tx: Math.round(tx) });
    }
  })();
  var _lastCpu = history[history.length-1].cpu, _lastMem = history[history.length-1].mem,
      _lastDisk = history[history.length-1].disk, _lastRx = history[history.length-1].rx,
      _lastTx = history[history.length-1].tx;

  function tick(){
    _lastCpu = jitter(_lastCpu, 4, 4, 70);
    _lastMem = jitter(_lastMem, 1.2, 20, 70);
    _lastDisk = jitter(_lastDisk, 0.2, 20, 70);
    _lastRx = clamp(_lastRx + rnd(-1e5,1e5), 5e4, 5e6);
    _lastTx = clamp(_lastTx + rnd(-4e4,4e4), 2e4, 2e6);
    history.push({ t: Math.round(Date.now()/1000), cpu: Math.round(_lastCpu*10)/10,
                   mem: Math.round(_lastMem*10)/10, disk: Math.round(_lastDisk*10)/10,
                   running: RUNNING, rx: Math.round(_lastRx), tx: Math.round(_lastTx) });
    if (history.length > HISTORY_MAX) history.shift();
  }

  function isoNow(){ return new Date().toISOString(); }

  function buildOverview(){
    tick();
    var containers = makeContainers();
    var running = RUNNING;           // every service is up in this healthy snapshot; the job has exited
    var unhealthy = 0;
    var netTotals = containers.reduce(function(a,c){ a.rx += c.net.rx; a.tx += c.net.tx; return a; }, {rx:0,tx:0});
    var last = history[history.length-1];
    var diskUsed = Math.round(DISK_TOTAL * (last.disk/100));
    var memUsed = Math.round(MEM_TOTAL * (last.mem/100));

    return {
      generated_at: isoNow(),
      host: {
        hostname: 'bina-deployment',
        os: 'Debian GNU/Linux 12 (bookworm)',
        kernel: '6.1.0-25-amd64',
        architecture: 'x86_64',
        uptime_seconds: Math.round((Date.now() - startedAt)/1000) + 9*86400
      },
      cpu: {
        model: 'Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz',
        cores: 4,
        load1: Math.round(jitter(0.6, 0.3, 0.05, 3)*100)/100,
        load5: Math.round(jitter(0.7, 0.2, 0.05, 3)*100)/100,
        load15: Math.round(jitter(0.75, 0.15, 0.05, 3)*100)/100,
        percent: last.cpu
      },
      memory: {
        total: MEM_TOTAL,
        available: MEM_TOTAL - memUsed,
        used: memUsed,
        percent: last.mem,
        swap_total: 2*GB,
        swap_used: Math.round(0.05*GB)
      },
      storage: {
        root: { path: '/', total: DISK_TOTAL, used: diskUsed, free: DISK_TOTAL - diskUsed, percent: last.disk },
        top_paths: [
          { label: 'Docker',          path: '/var/lib/docker',                        size: Math.round(38*GB) },
          { label: 'Deployment',      path: '/root/deployment-hacohen',               size: Math.round(9.5*GB) },
          { label: 'apitools storage',path: '/root/deployment-hacohen/apitools/storage', size: Math.round(6.2*GB) },
          { label: 'FV benchmarks',   path: '/root/deployment-hacohen/feature-validation', size: Math.round(1.1*GB) },
          { label: 'OS /usr',         path: '/usr',                                   size: Math.round(4.8*GB) },
          { label: 'var logs',        path: '/var/log',                               size: Math.round(0.6*GB) },
          { label: 'home',            path: '/home',                                  size: Math.round(0.3*GB) }
        ],
        docker_df: {
          Images: containers.map(function(c,i){ return { Size: Math.round(rnd(1.2,4.5)*GB), VirtualSize: Math.round(rnd(1.2,4.5)*GB), Containers: 1 }; }),
          Volumes: [
            { UsageData: { Size: Math.round(2.1*GB) } },
            { UsageData: { Size: Math.round(0.8*GB) } },
            { UsageData: { Size: Math.round(1.4*GB) } }
          ],
          Containers: containers.map(function(){ return {}; }),
          // ONE record: a count of one is what a screen says wrong («1 רשומות») and what a mock of round numbers never asks of it
          BuildCache: [{}]
        },
        generated_at: isoNow()
      },
      docker: { containers_total: containers.length, containers_running: running, containers_unhealthy: unhealthy },
      net: { rx_total: netTotals.rx, tx_total: netTotals.tx },
      containers: containers,
      cleanup_enabled: false,
      cleanup_allowed_actions: [],
      cache_age_s: Math.round(rnd(0,4)*10)/10,
      history: history.slice(),
      net_rate: { rx: last.rx, tx: last.tx }
    };
  }

  var CLEANUP_OPTIONS = [
    { id: 'docker_container_prune',     title: 'Prune stopped containers',    risk: 'low',    description: 'Remove containers that are already stopped. Running services are untouched.' },
    { id: 'docker_image_prune_dangling',title: 'Prune dangling images',       risk: 'low',    description: 'Remove untagged image layers left by rebuilds.' },
    { id: 'docker_builder_prune_all',   title: 'Prune Docker build cache',    risk: 'low',    description: 'Remove rebuild cache. Future builds may take longer.' },
    { id: 'docker_image_prune_all',     title: 'Prune inactive images',       risk: 'medium', description: 'Remove images not used by any container. They can be pulled or rebuilt again.' }
  ];

  function buildCleanupOptions(){
    var options = CLEANUP_OPTIONS.map(function(o){
      return Object.assign({}, o, { enabled: false, disabled_reason: 'Not in MACHINE_CLEANUP_ALLOWED_ACTIONS' });
    });
    return { enabled: false, allowed_actions: [], options: options };
  }

  // Shared harness (build.mjs MOCK_PRELUDE): handlers return plain objects → auto-JSON, or
  // window.__json(obj,status) for a non-200. `options` route is listed before the generic cleanup
  // action route so it wins. The cleanup action only 403s on POST (real behavior); GET → empty ok.
  window.__mock([
    [/api\/overview/,         function(){ return buildOverview(); }],
    [/api\/cleanup\/options/, function(){ return buildCleanupOptions(); }],
    [/api\/cleanup\/[^/?]+/,  function(u, opts){
      if ((opts && opts.method ? opts.method : 'GET').toUpperCase() !== 'POST') return {};
      var actionId = (u.match(/api\/cleanup\/([^/?]+)/) || [])[1];
      return window.__json({ detail: 'Cleanup action is disabled. Add ' + actionId + ' to MACHINE_CLEANUP_ALLOWED_ACTIONS to enable it.' }, 403);
    }],
    [/api\/storage/,          function(){ return buildOverview().storage; }]
  ], function(u){ if (/\/api\//.test(u) || /^api\//.test(u)) return {}; });
})();
