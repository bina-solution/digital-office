/* Mock backend for אימות מערכת (feature-validation) — serves development/feature-validation/api/dashboard.html
   with a live-looking, mostly-passing test-suite run. Real UI code is untouched; only window.fetch
   is intercepted. Mirrors development/feature-validation/api/server.py's exact response shapes
   (see summarize_benchmark()) so the dashboard's rendering (feature cards, case rows, detail panes,
   overall banner) works unmodified. */
(function(){
  var realFetch = window.fetch ? window.fetch.bind(window) : null;

  function J(o, status){
    return Promise.resolve(new Response(JSON.stringify(o), {status: status||200, headers:{'Content-Type':'application/json'}}));
  }
  function delay(ms){ return new Promise(function(res){ setTimeout(res, ms); }); }
  function cloneDeep(o){ return JSON.parse(JSON.stringify(o)); }
  function jitter(v){ if (v == null) return v; var d = v*0.12; return Math.round((v + (Math.random()*2-1)*d)*100)/100; }
  function nowIso(){ return new Date().toISOString(); }
  function hashHex(seed){
    var h = 0;
    for (var i=0;i<seed.length;i++){ h = ((h<<5)-h+seed.charCodeAt(i))|0; }
    var hex = (h>>>0).toString(16);
    while (hex.length < 8) hex = '0'+hex;
    return (hex+hex+hex+hex).slice(0,32);
  }

  // ---------------------------------------------------------------------
  // Real scenario.json contents (copied verbatim from development/feature-validation/*/scenario.json)
  // ---------------------------------------------------------------------
  var SCENARIOS = {
    'aligned-value-extraction': {
      feature: 'aligned-value-extraction',
      description: "Validate aligned value extraction (find-after, find-below) using Google Vision OCR on synthetic and real documents.",
      endpoint: '/documentJsonQuery', upload_endpoint: '/documentOcr',
      upload_query_params: {cache:'false'}, cases_source: 'fixtures/fixtures.json',
      query_params: {draw:'1'},
      assertions: [
        {name:'match_present', source:'analysis.result_value', operator:'truthy'},
        {name:'validations_passed', source:'analysis.error', operator:'is_none'},
        {name:'drawing_path_created', source:'analysis.drawing_path', operator:'truthy'},
        {name:'result_value_equals', source:'analysis.result_value', operator:'equals'},
        {name:'aligned_value_equals', source:'analysis.aligned_value', operator:'equals'},
        {name:'text_match_equals', source:'analysis.text_match', operator:'equals'}
      ],
      expected: {match_present:true, validations_passed:true, drawing_path_created:true,
        notes: 'match_text should equal the certificate/account number immediately below the anchor label'}
    },
    'balance-sheet-extraction': {
      feature: 'balance-sheet-extraction',
      description: 'Extract structured balance-sheet data from supplier reconciliation documents via N8N workflow. Validates document balance, date, and first-line fields (ID, amount, date) against expected values.',
      cases_source: 'fixtures/fixtures.json', workflow_id: 'mphF5Nf028u8sIix', webhook_path: 'bs_ex_2',
      requires: ['orchestration'],
      notes: "End-to-end BS extraction via the n8n webhook — runs only with FV_CAPABILITIES including 'orchestration' (live n8n workflow); covered by the indox-e2e lane otherwise."
    },
    'column-extraction': {
      feature: 'column-extraction',
      description: 'Validate column-aware value extraction where header and value may have different horizontal alignments within the same table column.',
      endpoint: '/documentJsonQuery', upload_endpoint: '/documentOcr', cases_source: 'fixtures/fixtures.json',
      query_params: {draw:'1'},
      assertions: [
        {name:'match_present', source:'analysis.result_value', operator:'truthy'},
        {name:'validations_passed', source:'analysis.error', operator:'is_none'},
        {name:'result_value_equals', source:'analysis.result_value', operator:'equals'},
        {name:'aligned_value_equals', source:'analysis.aligned_value', operator:'equals'},
        {name:'text_match_equals', source:'analysis.text_match', operator:'equals'}
      ],
      expected: {match_present:true, validations_passed:true,
        notes: 'Tests column extraction with varying header/value horizontal alignment combinations (left/center/right)'}
    },
    'document-ocr': {
      feature: 'document-ocr',
      description: 'Validate the document OCR upload pipeline: successful uploads, engine selection, unsupported formats, and edge cases.',
      upload_endpoint: '/documentOcr', cases_source: 'fixtures/fixtures.json'
    },
    'find-option-matching': {
      feature: 'find-option-matching',
      description: "Validate 'find option' action: given a list of candidate texts, check which ones appear in the OCR output. Tests correctness with small option sets and timeout resilience with large option sets.",
      endpoint: '/documentJsonQuery', upload_endpoint: '/documentOcr', cases_source: 'fixtures/fixtures.json',
      query_params: {},
      assertions: [
        {name:'no_error', source:'query_response.error', operator:'is_none'},
        {name:'has_result', source:'query_response.result.result', operator:'not_none'},
        {name:'has_matches', source:'query_response.result.result.matches', operator:'not_none'},
        {name:'match_count', source:'analysis.match_count', operator:'equals'},
        {name:'expected_options_found', source:'analysis.matched_option_names', operator:'equals'},
        {name:'no_false_positives', source:'analysis.unexpected_matches', operator:'equals'},
        {name:'completed_within_timeout', source:'analysis.completed', operator:'truthy'}
      ],
      expected: {no_error:true, has_result:true, has_matches:true, completed_within_timeout:true, no_false_positives:[]}
    },
    'integration': {
      feature: 'integration',
      description: 'Validates deployment service integrations: N8N API, Redis, Postgres, Google OCR (apitools), WhatsApp messaging, and N8N-triggered integrations (Google Sheets, Drive, Gmail, Gemini).',
      cases_source: 'fixtures/fixtures.json', requires: ['orchestration'],
      notes: "Full-stack orchestration E2E (n8n/whatsapp/Gemini/Google). Runs only when FV_CAPABILITIES includes 'orchestration'; covered by the indox-e2e lane otherwise."
    },
    'local-ocr': {
      feature: 'local-ocr',
      description: 'Validate the local Tesseract-based OCR engine produces correct text and bounding boxes through the documentJsonQuery pipeline.',
      endpoint: '/documentJsonQuery', upload_endpoint: '/documentOcr',
      upload_query_params: {cache:'false', ocr_engine:'local'}, cases_source: 'fixtures/fixtures.json',
      query_params: {draw:'1'},
      assertions: [
        {name:'match_present', source:'analysis.result_value', operator:'truthy'},
        {name:'validations_passed', source:'analysis.error', operator:'is_none'},
        {name:'result_value_equals', source:'analysis.result_value', operator:'equals'},
        {name:'text_match_equals', source:'analysis.text_match', operator:'equals'}
      ],
      expected: {match_present:true, validations_passed:true,
        notes: 'Tests use synthetic images that bypass OCR cache, forcing local OCR engine usage'}
    }
  };

  var FEATURES_ORDER = ['aligned-value-extraction','balance-sheet-extraction','column-extraction',
    'document-ocr','find-option-matching','integration','local-ocr'];

  // ---------------------------------------------------------------------
  // Raw per-case templates — shape matches a real "results[]" entry inside a
  // benchmarks/*.json file (see summarize_benchmark() in server.py for the
  // exact fields it reads off each entry).
  // ---------------------------------------------------------------------
  function ocrCase(name, q, a, opts){
    opts = opts || {};
    var evalKeys = opts.evalKeys || ['match_present','validations_passed','result_value_equals','text_match_equals'];
    var evaluations = {};
    var failCount = opts.failIdx != null ? 1 : 0;
    evalKeys.forEach(function(k, i){ evaluations[k] = !(opts.failIdx === i); });
    var details = evalKeys.map(function(k, i){
      return {name:k, source:'analysis.'+k, operator: k==='validations_passed' ? 'is_none' : (k==='match_present'?'truthy':'equals'),
        expected: true, actual: evaluations[k], passed: evaluations[k]};
    });
    return {
      name: name,
      status: opts.status || (failCount ? 'error' : 'passed'),
      source_file: null, file_id: null,
      evaluations: evaluations,
      evaluation_details: details,
      query_response: {ocr_json_query: q, status_code: 200},
      analysis: a,
      duration_s: opts.duration_s != null ? opts.duration_s : +(0.8 + Math.random()*2.2).toFixed(2)
    };
  }

  function integrationCase(name, type, integration, description, opts){
    opts = opts || {};
    var qr = opts.query_response || {};
    var evaluations = opts.evaluations || {ok:true};
    var details = Object.keys(evaluations).map(function(k){
      return {name:k, source:'query_response', operator:'truthy', expected:true, actual:evaluations[k], passed:evaluations[k]};
    });
    return {
      name: name, status: opts.status || 'passed', source_file: null, file_id: null,
      evaluations: evaluations, evaluation_details: details,
      query_response: qr, analysis: opts.analysis || {},
      integration: integration, type: type, description: description,
      duration_s: opts.duration_s != null ? opts.duration_s : +(0.1 + Math.random()*0.6).toFixed(2)
    };
  }

  var TEMPLATES = {

    'aligned-value-extraction': [
      ocrCase('after-en',
        {action:'find after', action_value:'Account No', is_rtl:false, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'40218-A', aligned_value:null, text_match:'40218-A', drawing_path:'/app/features/aligned-value-extraction/drawings/after-en.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','drawing_path_created','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:1.9}),
      ocrCase('after-45deg',
        {action:'find after', action_value:'מספר חשבון', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'778341', aligned_value:null, text_match:'778341', drawing_path:'/app/features/aligned-value-extraction/drawings/after-45deg.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','drawing_path_created','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:2.1}),
      ocrCase('after-90deg',
        {action:'find after', action_value:'תעודת זהות', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'55210-C', aligned_value:null, text_match:'55210-C', drawing_path:'/app/features/aligned-value-extraction/drawings/after-90deg.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','drawing_path_created','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:2.3}),
      ocrCase('after-135deg',
        {action:'find after', action_value:'מספר אסמכתא', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'90934-B', aligned_value:null, text_match:'90934-B', drawing_path:'/app/features/aligned-value-extraction/drawings/after-135deg.png',
         error:'low_confidence_rotation: OCR confidence 61% on rotated (135°) text region — below the 80% ideal threshold', match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','drawing_path_created','result_value_equals','aligned_value_equals','text_match_equals'],
         failIdx:1, status:'error', duration_s:2.6}),
      ocrCase('after-180deg',
        {action:'find after', action_value:'סכום לתשלום', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'12,345.00', aligned_value:null, text_match:'12,345.00', drawing_path:'/app/features/aligned-value-extraction/drawings/after-180deg.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','drawing_path_created','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:1.8})
    ],

    'balance-sheet-extraction': [
      integrationCase('goldman', 'n8n_webhook', 'n8n', 'התאמת מאזן ספק — Goldman', {
        query_response:{status_code:200, request_url:'https://n8n.bina-solutions.co.il/webhook/bs_ex_2', request_method:'POST',
          request_body:{supplier:'goldman'}, body:{balance:'0.00', date:'2026-06-30', first_line:{id:'INV-8841', amount:'4,210.00', date:'2026-06-02'}},
          execution_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix/executions/50231',
          workflow_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix', execution_id:50231, execution_status:'success', workflow_id:'mphF5Nf028u8sIix'},
        evaluations:{balance_zero:true, date_matches:true, first_line_matches:true}, duration_s:11.4}),
      integrationCase('mitzparles', 'n8n_webhook', 'n8n', 'התאמת מאזן ספק — Mitzparles', {
        query_response:{status_code:200, request_url:'https://n8n.bina-solutions.co.il/webhook/bs_ex_2', request_method:'POST',
          request_body:{supplier:'mitzparles'}, body:{balance:'0.00', date:'2026-06-30', first_line:{id:'INV-2210', amount:'980.50', date:'2026-06-05'}},
          execution_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix/executions/50232',
          workflow_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix', execution_id:50232, execution_status:'success', workflow_id:'mphF5Nf028u8sIix'},
        evaluations:{balance_zero:true, date_matches:true, first_line_matches:true}, duration_s:9.8}),
      integrationCase('tsinometal', 'n8n_webhook', 'n8n', 'התאמת מאזן ספק — Tsinometal', {
        query_response:{status_code:200, request_url:'https://n8n.bina-solutions.co.il/webhook/bs_ex_2', request_method:'POST',
          request_body:{supplier:'tsinometal'}, body:{balance:'0.00', date:'2026-06-29', first_line:{id:'INV-9012', amount:'15,760.00', date:'2026-05-28'}},
          execution_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix/executions/50233',
          workflow_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix', execution_id:50233, execution_status:'success', workflow_id:'mphF5Nf028u8sIix'},
        evaluations:{balance_zero:true, date_matches:true, first_line_matches:true}, duration_s:13.2}),
      integrationCase('promat', 'n8n_webhook', 'n8n', 'התאמת מאזן ספק — Promat', {
        query_response:{status_code:200, request_url:'https://n8n.bina-solutions.co.il/webhook/bs_ex_2', request_method:'POST',
          request_body:{supplier:'promat'}, body:{balance:'0.00', date:'2026-06-30', first_line:{id:'INV-3345', amount:'2,140.00', date:'2026-06-11'}},
          execution_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix/executions/50234',
          workflow_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix', execution_id:50234, execution_status:'success', workflow_id:'mphF5Nf028u8sIix'},
        evaluations:{balance_zero:true, date_matches:true, first_line_matches:true}, duration_s:10.1}),
      integrationCase('cohen-pur', 'n8n_webhook', 'n8n', 'התאמת מאזן ספק — Cohen Purchasing', {
        query_response:{status_code:200, request_url:'https://n8n.bina-solutions.co.il/webhook/bs_ex_2', request_method:'POST',
          request_body:{supplier:'cohen-pur'}, body:{balance:'0.00', date:'2026-06-28', first_line:{id:'INV-7790', amount:'6,325.40', date:'2026-06-01'}},
          execution_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix/executions/50235',
          workflow_url:'https://n8n.bina-solutions.co.il/workflow/mphF5Nf028u8sIix', execution_id:50235, execution_status:'success', workflow_id:'mphF5Nf028u8sIix'},
        evaluations:{balance_zero:true, date_matches:true, first_line_matches:true}, duration_s:12.6})
    ],

    'column-extraction': [
      ocrCase('below-table-align-hl-vl',
        {action:'find below', action_value:'כמות', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'120', aligned_value:'120', text_match:'120', drawing_path:'/app/features/column-extraction/drawings/below-table-align-hl-vl.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:1.6}),
      ocrCase('below-table-align-hl-vc',
        {action:'find below', action_value:'כמות', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'85', aligned_value:'85', text_match:'85', drawing_path:'/app/features/column-extraction/drawings/below-table-align-hl-vc.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:1.5}),
      ocrCase('below-table-align-hl-vr',
        {action:'find below', action_value:'כמות', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'340', aligned_value:'340', text_match:'340', drawing_path:'/app/features/column-extraction/drawings/below-table-align-hl-vr.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:1.7}),
      ocrCase('below-table-align-hc-vl',
        {action:'find below', action_value:'מחיר יחידה', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'12.00', aligned_value:'12.00', text_match:'12.00', drawing_path:'/app/features/column-extraction/drawings/below-table-align-hc-vl.png', error:null, match_count:null, matched_option_names:null},
        {evalKeys:['match_present','validations_passed','result_value_equals','aligned_value_equals','text_match_equals'], duration_s:1.4})
    ],

    'document-ocr': [
      integrationCase('good-png-default', null, null, 'העלאת PNG תקין — מנוע ברירת מחדל',
        {query_response:{status_code:200, body:{file_hash:hashHex('good-png-default'), file_name:'invoice-sample.png', ocr_engine:'google_vision'}},
         evaluations:{upload_ok:true, file_hash_present:true}, duration_s:0.6}),
      integrationCase('good-png-google', null, null, 'העלאת PNG תקין — מנוע Google Vision',
        {query_response:{status_code:200, body:{file_hash:hashHex('good-png-google'), file_name:'invoice-sample.png', ocr_engine:'google_vision'}},
         evaluations:{upload_ok:true, file_hash_present:true}, duration_s:0.9}),
      integrationCase('good-png-local', null, null, 'העלאת PNG תקין — מנוע Tesseract מקומי',
        {query_response:{status_code:200, body:{file_hash:hashHex('good-png-local'), file_name:'invoice-sample.png', ocr_engine:'local'}},
         evaluations:{upload_ok:true, file_hash_present:true}, duration_s:0.4}),
      integrationCase('unsupported-txt', null, null, 'דחיית קובץ טקסט לא נתמך',
        {query_response:{status_code:200, body:{error:'File type not allowed: text/plain only image/jpeg, image/png allowed'}},
         evaluations:{rejected_correctly:true}, duration_s:0.2}),
      integrationCase('corrupted-png', null, null, 'דחיית קובץ PNG פגום',
        {query_response:{status_code:200, body:{error:'Error processing OCR: cannot identify image file'}},
         evaluations:{rejected_correctly:true}, duration_s:0.3})
    ],

    'find-option-matching': [
      ocrCase('small-option-set-with-matche',
        {action:'find option', action_value:['כן','לא','אחר'], is_rtl:true},
        {result_value:null, aligned_value:null, text_match:null, drawing_path:null, error:null, match_count:1, matched_option_names:['כן']},
        {evalKeys:['no_error','has_result','has_matches','match_count','expected_options_found','no_false_positives','completed_within_timeout'], duration_s:1.1}),
      ocrCase('no-matches-expected',
        {action:'find option', action_value:['XYZ-999','QQQ-000'], is_rtl:false},
        {result_value:null, aligned_value:null, text_match:null, drawing_path:null, error:null, match_count:0, matched_option_names:[]},
        {evalKeys:['no_error','has_result','has_matches','match_count','expected_options_found','no_false_positives','completed_within_timeout'], duration_s:0.9}),
      ocrCase('large-option-set-stress-test',
        {action:'find option', action_value:['אופציה-01','אופציה-02','אופציה-03','... (40 אפשרויות)'], is_rtl:true},
        {result_value:null, aligned_value:null, text_match:null, drawing_path:null, error:null, match_count:3, matched_option_names:['אופציה-07','אופציה-19','אופציה-33']},
        {evalKeys:['no_error','has_result','has_matches','match_count','expected_options_found','no_false_positives','completed_within_timeout'], duration_s:6.4})
    ],

    'integration': [
      integrationCase('n8n-health', 'http', 'n8n', 'N8N health endpoint', {
        query_response:{status_code:200, request_url:'http://n8n:5678/healthz', request_method:'GET', body:{status:'ok'}},
        evaluations:{status_ok:true}, duration_s:0.08}),
      integrationCase('n8n-api-workflows', 'http', 'n8n', 'N8N API – list workflows', {
        query_response:{status_code:200, request_url:'http://n8n:5678/api/v1/workflows', request_method:'GET', body:{data:[{id:'mphF5Nf028u8sIix'},{id:'hnwYN84KY6f51yvX'}]}},
        evaluations:{status_ok:true, has_data:true}, duration_s:0.15}),
      integrationCase('redis-ping', 'redis', 'redis', 'Redis PING command', {
        query_response:{}, evaluations:{connected:true}, duration_s:0.02}),
      integrationCase('redis-set-get', 'redis', 'redis', 'Redis SET/GET roundtrip', {
        query_response:{}, evaluations:{roundtrip_ok:true}, duration_s:0.03}),
      integrationCase('postgres-connectivity', 'postgres', 'postgres', 'Postgres SELECT 1', {
        query_response:{row_count:1, rows:[{ok:1}]}, evaluations:{query_ok:true, has_rows:true}, duration_s:0.05}),
      integrationCase('postgres-n8n-tables', 'postgres', 'postgres', 'Postgres – verify N8N tables exist', {
        query_response:{row_count:1, rows:[{cnt:14}]}, evaluations:{has_tables:true}, duration_s:0.06}),
      integrationCase('apitools-ocr', 'http', 'apitools', 'Apitools Google OCR – upload test image', {
        query_response:{status_code:200, request_url:'http://apitools:8080/documentOcr', request_method:'POST',
          body:{file_hash:hashHex('apitools-ocr-test-image'), file_name:'test-image.png', ocr_engine:'google_vision'}},
        evaluations:{status_ok:true, has_file_hash:true}, duration_s:1.3}),
      integrationCase('whatsapp-connection', 'whatsapp', 'whatsapp', 'WhatsApp connection state', {
        query_response:{status_code:200, is_connected:true}, evaluations:{state_reachable:true, is_connected:true}, duration_s:0.4}),
      integrationCase('n8n-gmail', 'n8n_webhook', 'gmail', 'N8N Gmail integration via webhook workflow (OAuth2 credential may need re-auth)', {
        status:'error',
        query_response:{status_code:200, request_url:'https://n8n.bina-solutions.co.il/webhook/test-integration/gmail', request_method:'POST',
          request_body:{action:'list-labels'}, body:{labels:['INBOX','SENT','Invoices']},
          execution_url:'https://n8n.bina-solutions.co.il/workflow/clTrnzBP2ufCTgy5/executions/8842',
          workflow_url:'https://n8n.bina-solutions.co.il/workflow/clTrnzBP2ufCTgy5', execution_id:8842, execution_status:'success', workflow_id:'clTrnzBP2ufCTgy5',
          error:'Gmail OAuth2 token expires in 2 days — schedule re-authentication'},
        evaluations:{webhook_ok:true, has_data:true}, duration_s:5.7})
    ],

    'local-ocr': [
      ocrCase('ocr-numbers-below',
        {action:'find below', action_value:'סה"כ לתשלום', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'3,450.00', aligned_value:null, text_match:'3,450.00', drawing_path:'/app/features/local-ocr/drawings/ocr-numbers-below.png', error:null, match_count:null, matched_option_names:null},
        {duration_s:0.7}),
      ocrCase('ocr-invoice-number',
        {action:'find after', action_value:'מספר חשבונית', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'INV-20394', aligned_value:null, text_match:'INV-20394', drawing_path:'/app/features/local-ocr/drawings/ocr-invoice-number.png', error:null, match_count:null, matched_option_names:null},
        {duration_s:0.6}),
      ocrCase('ocr-customer-id',
        {action:'find after', action_value:'מספר לקוח', is_rtl:true, tolerances:{max_vertical_gap:120,max_horizontal_offset:80}},
        {result_value:'C-77021', aligned_value:null, text_match:'C-77021', drawing_path:'/app/features/local-ocr/drawings/ocr-customer-id.png', error:null, match_count:null, matched_option_names:null},
        {duration_s:0.5})
    ]
  };

  // ---------------------------------------------------------------------
  // In-memory run store — a run replaces a feature's benchmark with a fresh
  // timestamp (and lightly-jittered durations), so repeated runs feel live
  // without changing the healthy pass/fail picture.
  // ---------------------------------------------------------------------
  var RUN_STORE = {};

  function buildBenchmark(name, tsMs){
    var tmpl = TEMPLATES[name] || [];
    var results = tmpl.map(function(t){
      var r = cloneDeep(t);
      if (r.duration_s != null) r.duration_s = jitter(r.duration_s);
      return r;
    });
    return {
      feature: name,
      timestamp: new Date(tsMs).toISOString(),
      all_passed: true,
      case_count: results.length,
      cases_passed: results.length, // top-level counters are authoritative (script-decided), independent of a case's own `status` flag — see summarize_benchmark()
      failures: [],
      results: results
    };
  }

  FEATURES_ORDER.forEach(function(name, idx){
    // stagger initial "last run" timestamps so the dashboard doesn't look frozen at one instant
    RUN_STORE[name] = buildBenchmark(name, Date.now() - (25 + idx*37) * 60000);
  });

  function summarizeBenchmark(b){
    var results = b.results || [];
    var cases = results.map(function(r){
      var evals = r.evaluations || {};
      var details = r.evaluation_details || [];
      var qr = r.query_response || {};
      var analysis = r.analysis || {};
      var passed = 0, total = 0;
      Object.keys(evals).forEach(function(k){ total++; if (evals[k]) passed++; });
      var entry = {
        name: r.name,
        status: r.status,
        source_file: r.source_file != null ? r.source_file : null,
        file_id: r.file_id != null ? r.file_id : null,
        assertions_passed: passed,
        assertions_total: total,
        ocr_json_query: qr.ocr_json_query != null ? qr.ocr_json_query : null,
        analysis: {
          result_value: analysis.result_value != null ? analysis.result_value : null,
          aligned_value: analysis.aligned_value != null ? analysis.aligned_value : null,
          text_match: analysis.text_match != null ? analysis.text_match : null,
          drawing_path: analysis.drawing_path != null ? analysis.drawing_path : null,
          error: analysis.error != null ? analysis.error : null,
          match_count: analysis.match_count != null ? analysis.match_count : null,
          matched_option_names: analysis.matched_option_names != null ? analysis.matched_option_names : null
        },
        failed_assertions: details.filter(function(d){ return !d.passed; }).map(function(d){
          return {name:d.name, expected:d.expected, actual:d.actual, operator:d.operator};
        })
      };
      if (r.integration) entry.integration = r.integration;
      if (r.type) entry.test_type = r.type;
      if (r.description) entry.description = r.description;
      if (r.duration_s != null) entry.duration_s = r.duration_s;
      if (qr.status_code != null) entry.response_status = qr.status_code;
      if (qr.body != null){
        var bodyStr = typeof qr.body === 'string' ? qr.body : JSON.stringify(qr.body);
        entry.response_body = bodyStr.length > 2000 ? bodyStr.slice(0,2000) : bodyStr;
      }
      if (qr.error) entry.response_error = qr.error;
      if (qr.request_url) entry.request_url = qr.request_url;
      if (qr.request_method) entry.request_method = qr.request_method;
      if (qr.request_body) entry.request_body = qr.request_body;
      if (qr.execution_url) entry.execution_url = qr.execution_url;
      if (qr.workflow_url) entry.workflow_url = qr.workflow_url;
      if (qr.execution_id) entry.execution_id = qr.execution_id;
      if (qr.execution_status) entry.execution_status = qr.execution_status;
      if (qr.workflow_id) entry.workflow_id = qr.workflow_id;
      if (qr.is_connected != null) entry.is_connected = qr.is_connected;
      if (qr.row_count != null) entry.row_count = qr.row_count;
      if (qr.rows) entry.rows_preview = qr.rows.slice(0,5);
      return entry;
    });
    return {
      feature: b.feature, timestamp: b.timestamp, all_passed: b.all_passed,
      case_count: b.case_count, cases_passed: b.cases_passed, failures: b.failures || [],
      cases: cases
    };
  }

  function discoverFeatures(){
    return FEATURES_ORDER.map(function(name){
      var s = SCENARIOS[name] || {};
      return {name:name, description: s.description || '', feature: s.feature || name, path: '/app/features/'+name};
    });
  }

  function stdoutFor(name, bench){
    var lines = ['Running feature: '+name];
    bench.results.forEach(function(r){
      var mark = r.status === 'passed' ? 'PASS' : (r.status === 'error' ? 'WARN' : 'FAIL');
      lines.push('  ['+mark+'] '+r.name+(r.duration_s != null ? ' ('+r.duration_s+'s)' : ''));
    });
    lines.push('Wrote benchmark to benchmarks/benchmark-'+bench.timestamp.replace(/[:.]/g,'-')+'.json');
    lines.push('Cases: '+bench.cases_passed+'/'+bench.case_count+' passed');
    return lines.join('\n')+'\n';
  }

  function historyFor(name){
    var cur = RUN_STORE[name];
    var hist = [];
    var base = new Date(cur.timestamp).getTime();
    for (var i=0;i<6;i++){
      hist.push({
        timestamp: new Date(base - i*6*3600000 - Math.floor(Math.random()*900000)).toISOString(),
        all_passed: true, cases_passed: cur.case_count, case_count: cur.case_count
      });
    }
    return hist;
  }

  function drawingSvg(label){
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420">'
      // a stand-in picture, in the office's palette as VALUES (a picture cannot name a token): the dark
      // ground's olive, a lime frame, and what is written on olive
      + '<rect width="100%" height="100%" fill="#384629"/>'
      + '<rect x="18" y="18" width="604" height="384" rx="10" fill="none" stroke="#a9b84c" stroke-width="3" stroke-dasharray="8 6"/>'
      + '<text x="320" y="200" font-size="20" fill="#f3f5f7" text-anchor="middle" font-family="sans-serif">ציור סימונים מדומה (mock)</text>'
      + '<text x="320" y="232" font-size="13" fill="#a2a8a2" text-anchor="middle" font-family="monospace">'+ (label||'') +'</text>'
      + '</svg>';
    return svg;
  }

  // ---------------------------------------------------------------------
  // Routes — [regex over the path (no query string, leading slash stripped), method, handler]
  // ---------------------------------------------------------------------
  var ROUTES = [
    [/^api\/health$/, 'GET', function(){
      return J({status:'ok', timestamp: nowIso()});
    }],

    [/^api\/status$/, 'GET', function(){
      var featureStatus = FEATURES_ORDER.map(function(name){
        var b = RUN_STORE[name];
        var s = SCENARIOS[name] || {};
        return {name:name, description: s.description||'', all_passed: b.all_passed, cases_passed: b.cases_passed,
          case_count: b.case_count, last_run: b.timestamp, failures: b.failures || []};
      });
      var passed = featureStatus.filter(function(f){ return f.all_passed === true; }).length;
      var total = featureStatus.length;
      var totalCases = featureStatus.reduce(function(s,f){ return s+(f.case_count||0); }, 0);
      var passedCases = featureStatus.reduce(function(s,f){ return s+(f.cases_passed||0); }, 0);
      var overall = (passed === total && total > 0) ? 'all_passed' : (passed > 0 ? 'partial' : 'failing');
      return J({overall_status: overall, features: featureStatus,
        summary:{features_passed:passed, features_total:total, cases_passed:passedCases, cases_total:totalCases},
        timestamp: nowIso()});
    }],

    [/^api\/features$/, 'GET', function(){
      var features = discoverFeatures().map(function(f){
        var b = RUN_STORE[f.name];
        f.latest_benchmark = b ? summarizeBenchmark(b) : null;
        return f;
      });
      return J({features: features});
    }],

    [/^api\/features\/([^/]+)\/benchmarks\/latest$/, 'GET', function(m){
      var name = decodeURIComponent(m[1]);
      var b = RUN_STORE[name];
      if (!b) return J({detail:"No benchmarks for '"+name+"'"}, 404);
      return J(b);
    }],

    [/^api\/features\/([^/]+)\/benchmarks\/(benchmark-[^/]+\.json)$/, 'GET', function(m){
      var name = decodeURIComponent(m[1]);
      var b = RUN_STORE[name];
      if (!b) return J({detail:'Benchmark not found'}, 404);
      return J(b); // single-snapshot mock: any historical filename resolves to the current benchmark
    }],

    [/^api\/features\/([^/]+)\/benchmarks$/, 'GET', function(m){
      var name = decodeURIComponent(m[1]);
      if (!SCENARIOS[name]) return J({detail:"Feature '"+name+"' not found"}, 404);
      var b = RUN_STORE[name];
      return J({feature:name, benchmarks:['benchmark-'+b.timestamp.replace(/[:.]/g,'-')+'.json']});
    }],

    [/^api\/features\/([^/]+)\/history$/, 'GET', function(m){
      var name = decodeURIComponent(m[1]);
      if (!SCENARIOS[name]) return J({detail:"Feature '"+name+"' not found"}, 404);
      return J({feature:name, history: historyFor(name)});
    }],

    [/^api\/features\/([^/]+)\/files\/(.+)$/, 'GET', function(m){
      return Promise.resolve(new Response(drawingSvg(decodeURIComponent(m[2])),
        {status:200, headers:{'Content-Type':'image/svg+xml'}}));
    }],

    [/^api\/features\/([^/]+)\/cases\/([^/]+)\/drawing$/, 'GET', function(m){
      return Promise.resolve(new Response(drawingSvg(decodeURIComponent(m[2])),
        {status:200, headers:{'Content-Type':'image/svg+xml'}}));
    }],

    [/^api\/features\/([^/]+)$/, 'GET', function(m){
      var name = decodeURIComponent(m[1]);
      var s = SCENARIOS[name];
      if (!s) return J({detail:"Feature '"+name+"' not found"}, 404);
      var b = RUN_STORE[name];
      return J({name:name, scenario:s, latest_benchmark: summarizeBenchmark(b),
        benchmark_count:1, benchmark_files:['benchmark-'+b.timestamp.replace(/[:.]/g,'-')+'.json']});
    }],

    [/^api\/run$/, 'POST', function(){
      return delay(900 + Math.random()*700).then(function(){
        var results = {};
        FEATURES_ORDER.forEach(function(name){
          RUN_STORE[name] = buildBenchmark(name, Date.now());
          var b = RUN_STORE[name];
          results[name] = {feature:name, exit_code:0, stdout: stdoutFor(name, b), stderr:'', benchmark:b};
        });
        var passed = Object.keys(results).filter(function(k){ return results[k].benchmark.all_passed; }).length;
        var total = Object.keys(results).length;
        return J({results:results, summary:{total:total, passed:passed, failed: total-passed}, timestamp: nowIso()});
      });
    }],

    [/^api\/run\/([^/]+)$/, 'POST', function(m){
      var name = decodeURIComponent(m[1]);
      if (!SCENARIOS[name]) return J({detail:"Feature '"+name+"' not found"}, 404);
      return delay(500 + Math.random()*700).then(function(){
        RUN_STORE[name] = buildBenchmark(name, Date.now());
        var b = RUN_STORE[name];
        return J({feature:name, exit_code:0, stdout: stdoutFor(name, b), stderr:'', benchmark:b});
      });
    }],

    [/^api\/playground\/upload$/, 'POST', function(m, opts){
      var file = null;
      try { file = opts && opts.body && typeof opts.body.get === 'function' ? opts.body.get('file') : null; } catch(e){}
      var fname = (file && file.name) || 'upload.png';
      var ftype = (file && file.type) || 'image/png';
      var ext = (fname.match(/\.([a-zA-Z0-9]+)$/) || [,'png'])[1].toLowerCase();
      var hash = hashHex(fname + (file && file.size || 0));
      return delay(500 + Math.random()*900).then(function(){
        return J({
          file_name: fname, file_type: ftype, file_extension: ext,
          filepath: '/app/data/uploads/'+hash+'.'+ext, file_hash: hash,
          ocr_ms: Math.round(300 + Math.random()*900), ocr_at: nowIso(),
          ocr_engine: 'google_vision', ocr_apitools_version: '3.4.1', apitools_version: '3.4.1',
          ocr_json: {pages:1, engine:'google_vision', full_text:'(מסמך מדומה) חשבונית מס׳ INV-20394\nסה"כ לתשלום: 3,450.00 ₪',
            blocks:[{text:'INV-20394', bbox:[120,80,260,110]}, {text:'3,450.00', bbox:[140,320,240,350]}]}
        });
      });
    }],

    [/^api\/playground\/query$/, 'POST', function(m, opts){
      var payload = {};
      try { payload = JSON.parse(opts.body); } catch(e){}
      var fileId = payload.file_id;
      var q = payload.ocr_json_query || {};
      var draw = String(payload.draw || '0') === '1';
      return delay(400 + Math.random()*600).then(function(){
        var result;
        if (q.action === 'find option'){
          result = {matches:['אופציה-07','אופציה-19'], match_count:2};
        } else if (q.action === 'find below'){
          result = {result_text:'85', bbox:[140,300,220,330]};
        } else {
          result = {result_text:'INV-20394', bbox:[120,80,260,110]};
        }
        var resp = {
          file_id: fileId, ocr_json_query: q, result: {result:result},
          ocr_engine:'google_vision', ocr_ms: Math.round(300+Math.random()*700), ocr_at: nowIso(),
          ocr_apitools_version:'3.4.1', elapsed_ms: Math.round(50+Math.random()*350), apitools_version:'3.4.1'
        };
        if (draw) resp.drawing_path = '/app/data/drawings/'+(fileId||'mock')+'.png';
        return J(resp);
      });
    }],

    [/^api\/playground\/drawing$/, 'POST', function(m, opts){
      var payload = {};
      try { payload = JSON.parse(opts.body); } catch(e){}
      return delay(400 + Math.random()*500).then(function(){
        return new Response(drawingSvg(payload.file_id||''), {status:200, headers:{'Content-Type':'image/svg+xml'}});
      });
    }]
  ];

  window.fetch = function(url, opts){
    var full = String(url);
    var qidx = full.indexOf('?');
    var path = (qidx >= 0 ? full.slice(0, qidx) : full).replace(/^\.?\/+/, '');
    var method = ((opts && opts.method) || 'GET').toUpperCase();
    for (var i=0; i<ROUTES.length; i++){
      var re = ROUTES[i][0], m2 = ROUTES[i][1], fn = ROUTES[i][2];
      if (m2 && m2 !== method) continue;
      var m = path.match(re);
      if (m) return Promise.resolve(fn(m, opts));
    }
    if (/^api\//.test(path)) return J({});
    return realFetch ? realFetch(url, opts) : Promise.reject(new Error('mock: no route '+full));
  };
})();
