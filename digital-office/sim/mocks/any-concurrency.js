/* Mock backend for any-concurrency — serves api/spans with a live-looking span set.
   Real UI code is untouched; only window.fetch is intercepted. */
(function(){
  var SYS = { n8n:['ingest-webhook','extract-invoice','sync-drive','notify'],
              traefik:['route-my-docs','route-mailview','route-indox'],
              docker:['apitools','n8n-worker','postgres','redis'],
              apitools:['ocr','field-extract','ground-truth'],
              gmail:['poll-inbox','fetch-attachments'] };
  function rnd(a,b){ return a + Math.random()*(b-a); }
  function genSpans(hours){
    var now = Date.now(), win = hours*3600*1000, spans = [], id = 0;
    Object.keys(SYS).forEach(function(src){
      SYS[src].forEach(function(proc){
        var n = 3 + Math.floor(Math.random()*11);
        for (var i=0;i<n;i++){
          var dur = Math.floor(rnd(180, 9000));
          var s = now - Math.floor(Math.random()*win);
          var running = Math.random() < 0.14 && (s + dur > now);
          var status = running ? 'running' : (Math.random() < 0.07 ? 'error' : 'success');
          spans.push({ id:'sp'+(id++), src:src, svc:proc, label:proc+' #'+(i+1),
                       status:status, s:s, e: running?null:s+dur, d: running?null:dur });
        }
      });
    });
    // What a real office always shows and chance never would: its containers have been up for days (the
    // system's «N רצות»), and one process runs eight at once (a dense row - the one that offers to expand).
    SYS.docker.forEach(function(proc, i){
      spans.push({ id:'sp'+(id++), src:'docker', svc:proc, label:proc, status:'running', s: now - (i+1)*26*3600e3, e:null, d:null });
    });
    for (var k=0;k<8;k++){
      var live = k < 2, dur = 8200 - k*310;
      spans.push({ id:'sp'+(id++), src:'n8n', svc:'extract-invoice', label:'extract-invoice #p'+(k+1),
                   status: live?'running':'success', s: now - 9000 + k*90, e: live?null:now - 9000 + k*90 + dur, d: live?null:dur });
    }
    return spans;
  }
  // Shared harness (build.mjs MOCK_PRELUDE): return a plain array → auto-JSON; unmatched → realFetch.
  window.__mock([
    [/api\/spans/, function(u){ var m = u.match(/hours=([\d.]+)/); return genSpans(m ? parseFloat(m[1]) : 0.25); }]
  ]);
})();
