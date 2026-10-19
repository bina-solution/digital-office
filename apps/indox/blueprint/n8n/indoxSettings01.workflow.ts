import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Settings
// Nodes   : 69  |  Connections: 64
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// InvoiceIdQuery                     set
// ShippingIdQuery                    set
// CentralizedInvoiceIdQuery          set
// Companies                          code
// Settings                           code
// SettingsLoaderStart                manualTrigger
// SettingsOutput                     code
// IfLoadQueries                      if
// IfLoadCompanies                    if
// IfLoadSettings                     if
// PurchaseOrderIdQuery               set
// CompanyIdQuery                     set
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// Start                              noOp
// HandleCompanyRequest               code
// HandleQueryRequest                 code
// HandleSettingRequest               code
// CompanyResponse                    respondToWebhook
// QueryResponse                      respondToWebhook
// SettingResponse                    respondToWebhook
// CompanyWebhook                     webhook                    [creds]
// QueryWebhook                       webhook
// Kvstorage                          redis                      [creds]
// IfFoundCache                       if
// Kvstorage1                         redis                      [creds]
// SettingsData                       noOp
// Code                               code
// ExecutionData                      executionData
// CompanyResponse1                   respondToWebhook
// Kvstorage2                         redis                      [creds]
// IfFoundCache1                      if
// Kvstorage3                         redis                      [creds]
// SettingsData1                      noOp
// Code1                              code
// SettingsWebhook                    webhook                    [creds]
// HandleSettingsRequest              code
// LoadCompaniesForApi                executeWorkflow            [retry]
// LoadSettingsForApi1                executeWorkflow            [retry]
// CompanyNameByIdentifier            code
// CompaniesByMail                    code
// AllCompaniesIdentifiers            code
// CompanyResponse2                   respondToWebhook
// Kvstorage4                         redis                      [creds]
// IfFoundCache2                      if
// Kvstorage5                         redis                      [creds]
// SettingsData2                      noOp
// Code2                              code
// HandleSettingsRequest1             code
// LoadSettingsForApi                 executeWorkflow            [retry]
// QueriesWebhook                     webhook                    [creds]
// CompanyResponse3                   respondToWebhook
// HttpRequest                        httpRequest                [retry]
// HttpRequest1                       httpRequest                [retry]
// HttpRequest2                       httpRequest                [retry]
// CodeInJavascript                   code
// AllSettingWebhook                  webhook                    [creds]
// TgetSettingsReq                    code
// CallIndoxSettings                  executeWorkflow
// TgetCompaniesReq                   code
// CallIndoxCompanies                 executeWorkflow            [alwaysOutput]
// KwConfig                           postgres                   [creds]
// TgetTagRulesReq                    code
// CallTagRules                       executeWorkflow
// BuildGmailLabels                   code
// InvalidateCacheWebhook             webhook                    [creds]
// ClearCache1                        redis                      [creds]
// ClearCache2                        redis                      [creds]
// ClearCache3                        redis                      [creds]
// InvalidateCacheResponse            respondToWebhook
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// SettingsLoaderStart
//    → Start
//      → TgetTagRulesReq
//        → CallTagRules
//          → BuildGmailLabels
//            → IfLoadSettings
//              → TgetSettingsReq
//                → CallIndoxSettings
//                  → Settings
//                    → IfLoadCompanies
//                      → TgetCompaniesReq
//                        → CallIndoxCompanies
//                          → Companies
//                            → IfLoadQueries
//                              → InvoiceIdQuery
//                                → ShippingIdQuery
//                                  → CentralizedInvoiceIdQuery
//                                    → PurchaseOrderIdQuery
//                                      → CompanyIdQuery
//                                        → KwConfig
//                                          → SettingsOutput
//                             .out(1) → SettingsOutput (↩ loop)
//                     .out(1) → IfLoadQueries (↩ loop)
//             .out(1) → IfLoadCompanies (↩ loop)
// WhenExecutedByAnotherWorkflow
//    → Start (↩ loop)
// HandleQueryRequest
//    → QueryResponse
// HandleSettingRequest
//    → SettingResponse
// CompanyWebhook
//    → Kvstorage
//      → IfFoundCache
//        → Code
//          → SettingsData
//            → HandleCompanyRequest
//              → CompanyResponse
//       .out(1) → LoadCompaniesForApi
//          → Kvstorage1
//          → SettingsData (↩ loop)
// SettingsWebhook
//    → Kvstorage2
//      → IfFoundCache1
//        → Code1
//          → SettingsData1
//            → HandleSettingsRequest
//              → CompanyResponse1
//       .out(1) → LoadSettingsForApi1
//          → Kvstorage3
//          → SettingsData1 (↩ loop)
// CompanyNameByIdentifier
//    → CompaniesByMail
//      → AllCompaniesIdentifiers
// QueriesWebhook
//    → Kvstorage4
//      → IfFoundCache2
//        → Code2
//          → SettingsData2
//            → HandleSettingsRequest1
//              → CompanyResponse2
//       .out(1) → LoadSettingsForApi
//          → Kvstorage5
//          → SettingsData2 (↩ loop)
// AllSettingWebhook
//    → HttpRequest
//      → HttpRequest1
//        → HttpRequest2
//          → CodeInJavascript
//            → CompanyResponse3
// InvalidateCacheWebhook
//    → ClearCache1
//      → ClearCache2
//        → ClearCache3
//          → InvalidateCacheResponse
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Invoice Id Query":{"main":[[{"node":"Shipping Id Query","type":"main","index":0}]]},"Shipping Id Query":{"main":[[{"node":"Centralized Invoice Id Query","type":"main","index":0}]]},"Centralized Invoice Id Query":{"main":[[{"node":"Purchase Order Id Query","type":"main","index":0}]]},"Companies":{"main":[[{"node":"If Load Queries","type":"main","index":0}]]},"Settings":{"main":[[{"node":"If Load Companies","type":"main","index":0}]]},"Settings Loader Start":{"main":[[{"node":"Start","type":"main","index":0}]]},"If Load Queries":{"main":[[{"node":"Invoice Id Query","type":"main","index":0}],[{"node":"Settings Output","type":"main","index":0}]]},"If Load Companies":{"main":[[{"node":"TGET Companies Req","type":"main","index":0}],[{"node":"If Load Queries","type":"main","index":0}]]},"If Load Settings":{"main":[[{"node":"TGET Settings Req","type":"main","index":0}],[{"node":"If Load Companies","type":"main","index":0}]]},"Purchase Order Id Query":{"main":[[{"node":"Company Id Query","type":"main","index":0}]]},"Company Id Query":{"main":[[{"node":"KW Config","type":"main","index":0}]]},"Settings Output":{"main":[[]]},"When Executed by Another Workflow":{"main":[[{"node":"Start","type":"main","index":0}]]},"Start":{"main":[[{"node":"If Load Settings","type":"main","index":0}]]},"Handle Company Request":{"main":[[{"node":"Company Response","type":"main","index":0}]]},"Handle Query Request":{"main":[[{"node":"Query Response","type":"main","index":0}]]},"Handle Setting Request":{"main":[[{"node":"Setting Response","type":"main","index":0}]]},"Company Webhook":{"main":[[{"node":"KVStorage","type":"main","index":0}]]},"KVStorage":{"main":[[{"node":"If Found Cache","type":"main","index":0}]]},"If Found Cache":{"main":[[{"node":"Code","type":"main","index":0}],[{"node":"Load Companies For API","type":"main","index":0}]]},"Settings Data":{"main":[[{"node":"Handle Company Request","type":"main","index":0}]]},"Code":{"main":[[{"node":"Settings Data","type":"main","index":0}]]},"KVStorage2":{"main":[[{"node":"If Found Cache1","type":"main","index":0}]]},"If Found Cache1":{"main":[[{"node":"Code1","type":"main","index":0}],[{"node":"Load Settings For API1","type":"main","index":0}]]},"Settings Data1":{"main":[[{"node":"Handle Settings Request","type":"main","index":0}]]},"Code1":{"main":[[{"node":"Settings Data1","type":"main","index":0}]]},"Settings Webhook":{"main":[[{"node":"KVStorage2","type":"main","index":0}]]},"Handle Settings Request":{"main":[[{"node":"Company Response1","type":"main","index":0}]]},"Load Companies For API":{"main":[[{"node":"KVStorage1","type":"main","index":0},{"node":"Settings Data","type":"main","index":0}]]},"Load Settings For API1":{"main":[[{"node":"KVStorage3","type":"main","index":0},{"node":"Settings Data1","type":"main","index":0}]]},"Company Name By Identifier":{"main":[[{"node":"Companies By Mail","type":"main","index":0}]]},"Companies By Mail":{"main":[[{"node":"All Companies Identifiers","type":"main","index":0}]]},"KVStorage4":{"main":[[{"node":"If Found Cache2","type":"main","index":0}]]},"If Found Cache2":{"main":[[{"node":"Code2","type":"main","index":0}],[{"node":"Load Settings For API","type":"main","index":0}]]},"Settings Data2":{"main":[[{"node":"Handle Settings Request1","type":"main","index":0}]]},"Code2":{"main":[[{"node":"Settings Data2","type":"main","index":0}]]},"Handle Settings Request1":{"main":[[{"node":"Company Response2","type":"main","index":0}]]},"Load Settings For API":{"main":[[{"node":"KVStorage5","type":"main","index":0},{"node":"Settings Data2","type":"main","index":0}]]},"Queries Webhook":{"main":[[{"node":"KVStorage4","type":"main","index":0}]]},"Code in JavaScript":{"main":[[{"node":"Company Response3","type":"main","index":0}]]},"All Setting Webhook":{"main":[[{"node":"Code in JavaScript","type":"main","index":0}]]},"TGET Settings Req":{"main":[[{"node":"Call INDOX Settings","type":"main","index":0}]]},"Call INDOX Settings":{"main":[[{"node":"Settings","type":"main","index":0}]]},"TGET Companies Req":{"main":[[{"node":"Call INDOX Companies","type":"main","index":0}]]},"Call INDOX Companies":{"main":[[{"node":"Companies","type":"main","index":0}]]},"KW Config":{"main":[[{"node":"Settings Output","type":"main","index":0}]]},"Invalidate Cache Webhook":{"main":[[{"node":"Clear Cache 1","type":"main","index":0}]]},"Clear Cache 1":{"main":[[{"node":"Clear Cache 2","type":"main","index":0}]]},"Clear Cache 2":{"main":[[{"node":"Clear Cache 3","type":"main","index":0}]]},"Clear Cache 3":{"main":[[{"node":"Invalidate Cache Response","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"2962bdf4-baed-49a5-8f16-6afedb299830","name":"settings"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"815271f8-5a75-42df-aec8-4998e7ecce4e","name":"main"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {"Settings Loader Start":[{"json":{}}],"Company Webhook":[{"json":{"headers":{"host":"n8n:5678","user-agent":"axios/1.8.3","accept":"application/json,text/html,application/xhtml+xml,application/xml,text/*;q=0.9, image/*;q=0.8, */*;q=0.7","accept-encoding":"gzip, compress, deflate, br","x-forwarded-for":"172.18.0.1","x-forwarded-host":"n8n:5678","x-forwarded-port":"443","x-forwarded-proto":"https","x-forwarded-server":"60882555e47e","x-real-ip":"172.18.0.1"},"params":{},"query":{"all":true,"TRIGGERED_FROM":"INCOMING_DOCUMENT"},"body":{},"webhookUrl":"http://n8n-webhook:5678/webhook/company","executionMode":"production"}}],"Settings Webhook":[{"json":{"headers":{"host":"n8n:5678","user-agent":"axios/1.8.3","accept":"application/json,text/html,application/xhtml+xml,application/xml,text/*;q=0.9, image/*;q=0.8, */*;q=0.7","accept-encoding":"gzip, compress, deflate, br","x-forwarded-for":"172.18.0.1","x-forwarded-host":"n8n:5678","x-forwarded-port":"443","x-forwarded-proto":"https","x-forwarded-server":"60882555e47e","x-real-ip":"172.18.0.1"},"params":{},"query":{"key":"gmail_docs_download_ignored_mails","TRIGGERED_FROM":"PINNED_TEST"},"body":{},"webhookUrl":"http://n8n-webhook:5678/webhook/company","executionMode":"production"}}],"Queries Webhook":[{"json":{"headers":{"host":"n8n:5678","user-agent":"axios/1.8.3","accept":"application/json,text/html,application/xhtml+xml,application/xml,text/*;q=0.9, image/*;q=0.8, */*;q=0.7","accept-encoding":"gzip, compress, deflate, br","x-forwarded-for":"172.18.0.1","x-forwarded-host":"n8n:5678","x-forwarded-port":"443","x-forwarded-proto":"https","x-forwarded-server":"60882555e47e","x-real-ip":"172.18.0.1"},"params":{},"query":{"TRIGGERED_FROM":"PINNED_TEST"},"body":{},"webhookUrl":"http://n8n-webhook:5678/webhook/company","executionMode":"production"}}],"All Setting Webhook":[{"json":{"headers":{"host":"n8n:5678","user-agent":"axios/1.8.3","accept":"application/json,text/html,application/xhtml+xml,application/xml,text/*;q=0.9, image/*;q=0.8, */*;q=0.7","accept-encoding":"gzip, compress, deflate, br","x-forwarded-for":"172.18.0.1","x-forwarded-host":"n8n:5678","x-forwarded-port":"443","x-forwarded-proto":"https","x-forwarded-server":"60882555e47e","x-real-ip":"172.18.0.1"},"params":{},"query":{"TRIGGERED_FROM":"PINNED_TEST"},"body":{},"webhookUrl":"http://n8n-webhook:5678/webhook/company","executionMode":"production"}}],"When Executed by Another Workflow":[{"json":{"load_settings":false,"load_companies":null,"load_queries":false,"TRIGGERED_FROM":"Figure Document COMPANY_ID: 4268533"},"pairedItem":{"item":0}}]},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T00:59:54.840Z","createdAt":"2026-07-31T00:59:54.840Z","role":"workflow:owner","workflowId":"indoxSettings01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxSettings01',
    name: 'Settings',
    active: true,
    isArchived: false,
    tags: ['indox-app', 'role:api', 'settings', 'sm-refactor-v2.1', 'indox', 'main', 'sm-refactore-v2.1', 'app:indox'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        executionTimeout: 1200,
        binaryMode: 'separate',
    },
})
export class SettingsWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '2e003373-9c22-4787-9c4f-bac00f5bffd7',
        name: 'Invoice Id Query',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [2544, 1368],
    })
    InvoiceIdQuery = {
        mode: 'raw',
        jsonOutput: `{
  "invoice_id_query": {
    "action": "find after",
    "action_value": [
        "חשבונית מס זיכוי מס':",
            "חשבונית מס זיכוי",

      "חשבונית מס מרוכזת מספר:",
            "חשבונית מס מרכזת",
      "חשבונית מס/קבלה מס':",
        "חשבונית מס מספר:",
        "חשבונית מס/קבלה",
      "חשבונית מס / קבלה",
        "חשבונית מס מספר",
        "חשבונית מס מס':",
        "חשבונית מס\\"",
        "חשבונית מס -",
        "חשבונית מס :",
        "חשבונית זיכוי",
        "חשבונית מס'",
        "חשבונית מס"
    ], 
    "value_validations": [
        { "validation_type":"has_number" },
        { "validation_type": "length_greater_than", "validation_value": 3 },
        { "validation_type": "length_less_than", "validation_value": 20 }
    ],
    "is_rtl": true
  }
}
`,
        options: {},
    };

    @node({
        id: '90546e5e-e458-4422-bb93-be1762b7f190',
        name: 'Shipping Id Query',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [2768, 1368],
    })
    ShippingIdQuery = {
        mode: 'raw',
        jsonOutput: `{
  "shipping_id_query": {
    "action": "find after",
    "action_value": [
        "תעודת משלוח מספר",
        "משלוח מספר",
        "תעודת משלוח מס':",
        "תעודת משלוח מס'",
        "משלוח מספר    ",
         "משלוח מס' :    ",
       "תעודת משלוח מס'",
        "תעודת משלוח                ",
        "תעודת משלוח מס",
        "תעודת משלוח",
        "מספר משלוח",
        "משלוח מס'"

    ],
    "value_validations": [
        {
            "validation_type": "has_number"
        },
        {
            "validation_type": "length_greater_than",
            "validation_value": 3
        },
        { "validation_type": "length_less_than", "validation_value": 20 }
    ],
    "is_rtl": true
  }
}

`,
        options: {},
    };

    @node({
        id: '37872530-0480-4127-8c70-5d6b95e03648',
        name: 'Centralized Invoice Id Query',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [2992, 1368],
    })
    CentralizedInvoiceIdQuery = {
        mode: 'raw',
        jsonOutput: `{
  "centralized_invoice_id_query": {
    "action": "find after",
    "action_value": [
        "חשבונית מס מרכזת"
    ],
    "value_validations": [
        {
            "validation_type": "has_number"
        },
        {
            "validation_type": "length_greater_than",
            "validation_value": 3
        },
        { "validation_type": "length_less_than", "validation_value": 20 }
    ],
    "is_rtl": true
  }
}

`,
        options: {},
    };

    @node({
        id: 'd59a84a0-d5ef-4824-9217-f18c20774b23',
        name: 'Companies',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2096, 1368],
    })
    Companies = {
        jsCode: `const COMPANY_NAME_FIELD = "שם חברה";
const IDENTIFIER_FIELDS = ["מזהה 1", "מזהה 2", "שם ספק מפריוריטי"];
const IDENTIFIER_BLACKLIST = ["פריוריטי"];
const EMAIL_FIELDS = ["מייל 1", "מייל 2"];
const BS_PROMPT_FIELD = "הוראות לAI לחילוץ דוח גיול";  // ← חדש

const companies = {};
  const trusted_suppliers = [];
  const _ns = s => { s = String(s||'').toUpperCase(); return s.includes('DRIVE') ? 'DRIVE' : (s.includes('GMAIL') ? 'GMAIL' : s.trim()); };
const company_name_by_identifier = {};
const company_name_by_mail = {};
const company_id_by_mails = {};
const company_first_identifier_by_identifier = {};
const all_companies_identifiers = [];
const company_prompt_bs_by_id = {};  // ← חדש

$('Call INDOX Companies').all().forEach(item => {
  const json = item.json;
  const name = json[COMPANY_NAME_FIELD];

  const identifiers = [];
  for (const field of IDENTIFIER_FIELDS) {
    const id = json[field];
    if (id != null && id !== "") {
      const strId = String(id);
      if (IDENTIFIER_BLACKLIST.some(bl => strId.includes(bl))) continue;
      identifiers.push(strId);
      company_name_by_identifier[strId] = name;
      all_companies_identifiers.push(strId);
    }
  }


  const primaryId = identifiers[0];
  if (primaryId) {
    for (const id of identifiers) {
      company_first_identifier_by_identifier[id] = primaryId;
    }

    // ← חדש: שמור prompt רק אם יש ערך בשדה
    const bsPrompt = json[BS_PROMPT_FIELD];
    if (bsPrompt != null && bsPrompt !== "") {
      company_prompt_bs_by_id[primaryId] = String(bsPrompt).trim();
    }
  }

  const mails = [];
  for (const field of EMAIL_FIELDS) {
    const mail = json[field];
    if (mail != null && mail !== "") {
      const normalizedMail = String(mail).trim().toLowerCase();
      mails.push(normalizedMail);
      company_name_by_mail[normalizedMail] = name;
      if (primaryId) {
        company_id_by_mails[normalizedMail] = primaryId;
      }
    }
  }

  if (parseInt(json['SELECTION_CERTAINTY'],10) === 100) {
    let _sts=[]; try{ const _p=JSON.parse(json['TRUSTED_SOURCE_TYPES']||'[]'); _sts=Array.isArray(_p)?_p:(_p?[_p]:[]); }catch(e){ _sts=String(json['TRUSTED_SOURCE_TYPES']||'').split(/[,;]/).map(s=>s.trim()).filter(Boolean); }
    for (const _idf of identifiers) for (const _st of _sts) trusted_suppliers.push({ companyId: String(_idf).replace(/\\D/g,'').slice(-6).padStart(6,'0'), sourceType: _ns(_st) });
  }
  companies[name] = { identifiers, mails };
});

return [{
  companies,
  company_name_by_identifier,
  company_name_by_mail,
  company_id_by_mails,
  company_first_identifier_by_identifier,
  all_companies_identifiers,
  company_prompt_bs_by_id,
  trusted_suppliers
}];`,
    };

    @node({
        id: '2a5de9e3-c585-4552-88ee-5e4fa26f8c3c',
        name: 'Settings',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [976, 1368],
    })
    Settings = {
        jsCode: `function getGoogleDriveId(url = "") {
    if (url === null || url === undefined) return null;
    const s = String(url).trim();
    if (!s) return null;
    let m = s.match(/\\/folders\\/([a-zA-Z0-9-_]+)/);
    if (m) return m[1];
    m = s.match(/[?&]id=([a-zA-Z0-9-_]+)/);
    if (m) return m[1];
    if (/^[a-zA-Z0-9-_]{10,}$/.test(s)) return s; // already a bare id
    return null;
}

function getSeparatedItems(itemsStr) {
  let items = [];
  if (itemsStr.includes(",")) {
    items = itemsStr.split(",");
  } else {
    items = [itemsStr];
  }
  return items.map(item => item.trim());
}

let settings = {}
let settings_items = $('Call INDOX Settings').all().map(it => { const j=it.json; return ('הגדרה' in j) ? it : {json:{'הגדרה': j.key, 'ערך': j.value}}; });
let settings_jsons = settings_items.map(setting_item => setting_item.json)

settings_jsons.forEach( setting => {
  if (setting["הגדרה"] === "DocumentsToProcessFolder") {
    settings["docs_source_folder_id"] = getGoogleDriveId(setting["ערך"]);
  }
  else if (setting["הגדרה"] === "ProcessedDocumentsFolder") {
    settings["docs_dest_folder_id"] = getGoogleDriveId(setting["ערך"]);
  }
  else if (setting["הגדרה"] === "ProcessedDocumentsFailsFolder") {
    settings["docs_fails_dest_folder_id"] = getGoogleDriveId(setting["ערך"]);
  }
  else if (setting["הגדרה"] === "GmailDownloadedDocumentsFolder") {
    settings["gmail_docs_dest_folder_id"] = getGoogleDriveId(setting["ערך"]);
  }
  else if (setting["הגדרה"] === "GmailDownloadedBalanceDocsFolder") {
    settings["gmail_balance_docs_dest_folder_id"] = getGoogleDriveId(setting["ערך"]);
  }
  else if (setting["הגדרה"] === "GmailDocsDownloadIgnoredMails") {
    settings["gmail_docs_download_ignored_mails"] = getSeparatedItems(setting["ערך"]);
  }
  else if (setting["הגדרה"] === "WhatsappAdmins") {
    settings["whatsapp_admins"] = getSeparatedItems(setting["ערך"]);
  }
  else if (setting["הגדרה"] === "OldDocumentMonthsBack") {
    settings["old_document_months_back"] = Number(setting["ערך"]) || 24;
  }
});

// ---- settings-driven gdrive SYNC PAIRS (auto-discover, up to 10) ----
const SETTINGS_MAP = {};
settings_jsons.forEach(s => { if (s && s["הגדרה"] != null) SETTINGS_MAP[String(s["הגדרה"]).trim()] = s["ערך"]; });
function pickId(key){ return key in SETTINGS_MAP ? getGoogleDriveId(SETTINGS_MAP[key]) : null; }

const MAX_PAIRS = 10;
function buildPairs(prefix, defDest, defFails){
  const pairs = [];
  for (let i = 1; i <= MAX_PAIRS; i++){
    const src = pickId(prefix + "SourceFolder" + i);
    if (!src) continue;
    pairs.push({
      index: i,
      docs_source_folder_id: src,
      docs_dest_folder_id: pickId(prefix + "DestFolder" + i) || defDest || null,
      docs_fails_dest_folder_id: pickId(prefix + "FailsFolder" + i) || defFails || null,
    });
  }
  return pairs;
}

// bs pairs FIRST (dest/fails fall back to the gdoc processed/fails dest if a BS-specific one isn't set)
const bs_pairs = buildPairs("BalanceSheet", settings.docs_dest_folder_id, settings.docs_fails_dest_folder_id);
const bsSources = new Set(bs_pairs.map(p => p.docs_source_folder_id));
settings.bs_sync_pairs = bs_pairs;

// gdoc pairs (+ legacy single-sync as pair index 0 so nothing is lost)
let gdoc_pairs = buildPairs("GeneralDocs", settings.docs_dest_folder_id, settings.docs_fails_dest_folder_id);
if (settings.docs_source_folder_id
    && !gdoc_pairs.some(p => p.docs_source_folder_id === settings.docs_source_folder_id)
    && !bsSources.has(settings.docs_source_folder_id)) {
  gdoc_pairs.unshift({
    index: 0,
    docs_source_folder_id: settings.docs_source_folder_id,
    docs_dest_folder_id: settings.docs_dest_folder_id || null,
    docs_fails_dest_folder_id: settings.docs_fails_dest_folder_id || null,
  });
}
// never let the gdoc runner scan a folder that is a BS sync source (BS has its own dedicated path)
gdoc_pairs = gdoc_pairs.filter(p => !bsSources.has(p.docs_source_folder_id));
settings.gdoc_sync_pairs = gdoc_pairs;

// back-compat scalars some nodes may still read
settings.docs_source_folder_id_1 = (gdoc_pairs[0]||{}).docs_source_folder_id || null;
settings.docs_source_folder_id_2 = (gdoc_pairs[1]||{}).docs_source_folder_id || null;
settings.docs_source_folder_id_3 = (gdoc_pairs[2]||{}).docs_source_folder_id || null;

return [settings]
`,
    };

    @node({
        id: '6ebb3ce3-7b31-4326-86f2-94ecff702ce5',
        name: 'Settings Loader Start',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-592, 1440],
    })
    SettingsLoaderStart = {};

    @node({
        id: '261c719e-5d77-4751-bcf0-909eafa0143a',
        name: 'Settings Output',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3440, 1440],
    })
    SettingsOutput = {
        jsCode: `let settings = {}

if ($('Settings').isExecuted) {
  let settings_table = $('Settings').first().json;
  settings = {...settings, ...settings_table}
}

if($('Companies').isExecuted){
  let companies_data = $('Companies').first().json;
  settings = {
    ...settings, ...companies_data,
  }
}

if($('Invoice Id Query').isExecuted){
  let invoice_query = $('Invoice Id Query').first().json;
  let shipment_query = $('Shipping Id Query').first().json;
  let centrelized_invoice_query = $('Centralized Invoice Id Query').first().json;
  let purchase_order_id = $('Purchase Order Id Query').first().json;
  let company_id_q = $('Company Id Query').first().json;
  
  settings = {
    ...settings, 
    ...invoice_query, ...shipment_query, 
    ...centrelized_invoice_query,
    ...purchase_order_id,
    ...company_id_q
  }
}

if($('KW Config').isExecuted){
  const _kw=$('KW Config').first().json.cfg||{};
  settings = { ...settings, ..._kw };
  if (_kw.q_company_id && typeof _kw.q_company_id === 'object' && _kw.q_company_id.action) {
    settings.company_id_query = _kw.q_company_id;
  }
}

// settings.gmail (tag_rules → {labels, rows}) is GONE (2026-09-03, owner Decision N1): the label
// rules have one store, the mail app's organizer settings; every reader fetches it over HTTP.
// (A guard on the removed 'Build Gmail Labels' node stood here for 3 minutes live and threw
// "Referenced node doesn't exist" on every settings load — a dead reference is not a no-op.)

return {json: settings}`,
    };

    @node({
        id: '02785a09-1f64-4ab0-90af-30202b7ae591',
        name: 'If Load Queries',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [2320, 1440],
    })
    IfLoadQueries = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '67a955cc-92d9-4b89-a8d2-f3f9723ad129',
                    leftValue: "={{ $('Start').first().json.load_queries }}",
                    rightValue: false,
                    operator: {
                        type: 'boolean',
                        operation: 'notEquals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '1ed2c9ac-4502-404e-91f3-e553db3f7f12',
        name: 'If Load Companies',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1200, 1440],
    })
    IfLoadCompanies = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '0fef179a-c5aa-459c-865e-8e808d457fa9',
                    leftValue: "={{ $('Start').first().json.load_companies }}",
                    rightValue: false,
                    operator: {
                        type: 'boolean',
                        operation: 'notEquals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '8558c6bc-1929-49c6-9f17-42ab1f6ff73a',
        name: 'If Load Settings',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [80, 1440],
    })
    IfLoadSettings = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '88566445-56f8-4e66-a0c5-3683700d77e0',
                    leftValue: "={{ $('Start').first().json.load_settings }}",
                    rightValue: false,
                    operator: {
                        type: 'boolean',
                        operation: 'notEquals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'b0129eb6-32ac-456b-8af9-28781a7d0512',
        name: 'Purchase Order Id Query',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3216, 1368],
    })
    PurchaseOrderIdQuery = {
        mode: 'raw',
        jsonOutput: `{
  "purchase_order_id_query": {
    "action": "find after",
    "action_value": [
        "הזמנת רכש"
    ],
    "value_validations": [
        {
            "validation_type": "has_number"
        },
        {
            "validation_type": "length_greater_than",
            "validation_value": 3
        },
        { "validation_type": "length_less_than", "validation_value": 20 }
    ],
    "is_rtl": true
  }
}

`,
        options: {},
    };

    @node({
        id: 'c4a2b8f1-9d3e-4f7a-b6c5-8e1d2f3a4b5c',
        name: 'Company Id Query',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3440, 1368],
    })
    CompanyIdQuery = {
        mode: 'raw',
        jsonOutput: `{
  "company_id_query": {
    "action": "find after",
    "action_value": [
        "עוסק מורשה",
        "ח.פ",
        "ע.מ",
        "מספר תיק במע\\"מ",
        "ח\\"פ"
    ],
    "value_validations": [
        {
            "validation_type": "has_number"
        },
        {
            "validation_type": "length_greater_than",
            "validation_value": 1
        },
        {
            "validation_type": "length_less_than",
            "validation_value": 20
        }
    ],
    "is_rtl": true
  }
}
`,
        options: {},
    };

    @node({
        id: '3f70cd63-37ec-4db2-aeb4-6f694e52ef08',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-592, 1248],
    })
    WhenExecutedByAnotherWorkflow = {
        workflowInputs: {
            values: [
                {
                    name: 'load_settings',
                    type: 'boolean',
                },
                {
                    name: 'load_companies',
                    type: 'boolean',
                },
                {
                    name: 'load_queries',
                    type: 'boolean',
                },
                {
                    name: 'TRIGGERED_FROM',
                },
                {
                    name: '__instance',
                },
            ],
        },
    };

    @node({
        id: 'f057853b-b882-45fa-9856-0bbcb8e89826',
        name: 'Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-368, 1344],
    })
    Start = {};

    @node({
        id: 'd8c8e2c8-a3dd-419d-90a6-8669bce64a9a',
        name: 'Handle Company Request',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [528, -1568],
    })
    HandleCompanyRequest = {
        jsCode: `// Handle company lookup requests
const queryParams = $('Company Webhook').first().json.query;
const settings = $('Settings Data').first().json;

let result = {};

// Check what parameter was provided
if (queryParams.name) {
  // Look up by company name
  const companyName = queryParams.name;
  if (settings.companies[companyName]) {
    result = {
      name: companyName,
      ...settings.companies[companyName]
    };
  } else {
    result = { error: 'Company not found', name: companyName };
  }
} 
else if (queryParams.id || queryParams.identifier) {
  // Look up by identifier
  const identifier = queryParams.id || queryParams.identifier;
  const companyName = settings.company_name_by_identifier[identifier];
  
  if (companyName && settings.companies[companyName]) {
    result = {
      name: companyName,
      identifier: identifier,
      ...settings.companies[companyName]
    };
  } else {
    result = { error: 'Company not found', identifier: identifier };
  }
} 
else if (queryParams.email || queryParams.mail) {
  // Look up by email
  const email = (queryParams.email || queryParams.mail).toLowerCase().trim();
  const companyName = settings.company_name_by_mail[email];
  
  if (companyName && settings.companies[companyName]) {
    result = {
      name: companyName,
      email: email,
      ...settings.companies[companyName]
    };
  } else {
    result = { error: 'Company not found', email: email };
  }
} 
else if (!!queryParams.all) {
  result = settings
}
else {
  // No parameters provided, return all companies
  result = {
    companies: settings.companies,
    total_count: Object.keys(settings.companies).length
  };
}

return [{ json: result }];`,
    };

    @node({
        id: '590c3f2d-e667-4849-b142-1f92246b94ff',
        name: 'Handle Query Request',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-592, -512],
    })
    HandleQueryRequest = {
        jsCode: `// Handle query lookup requests
const queryParams = $('Query Webhook').first().json.query;
const settings = $('Load Settings').first().json;

let result = {};

// Available queries
const availableQueries = {
  'invoice_id': settings.invoice_id_query,
  'shipping_id': settings.shipping_id_query, 
  'centralized_invoice_id': settings.centralized_invoice_id_query,
  'purchase_order_id': settings.purchase_order_id_query,
  'company_id': settings.company_id_query
};

if (queryParams.key) {
  const queryKey = queryParams.key;
  if (availableQueries[queryKey]) {
    result = {
      key: queryKey,
      query: availableQueries[queryKey]
    };
  } else {
    result = { 
      error: 'Query not found', 
      key: queryKey,
      available_queries: Object.keys(availableQueries)
    };
  }
} else {
  // No key provided, return all queries
  result = {
    queries: availableQueries,
    available_keys: Object.keys(availableQueries)
  };
}

return [{ json: result }];`,
    };

    @node({
        id: '226989f6-2378-4fc4-a592-fc08945c42e3',
        name: 'Handle Setting Request',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-592, 576],
    })
    HandleSettingRequest = {
        jsCode: `// Handle setting lookup requests
const queryParams = $('Setting Webhook').first().json.query;
const settings = $('Load Settings').first().json;

let result = {};

// Available settings
const availableSettings = {
  'docs_source_folder_id': settings.docs_source_folder_id,
  'docs_dest_folder_id': settings.docs_dest_folder_id,
  'docs_fails_dest_folder_id': settings.docs_fails_dest_folder_id,
  'gmail_docs_dest_folder_id': settings.gmail_docs_dest_folder_id,
  'gmail_balance_docs_dest_folder_id': settings.gmail_balance_docs_dest_folder_id,
  'all_companies_identifiers': settings.all_companies_identifiers
};

if (queryParams.key) {
  const settingKey = queryParams.key;
  if (availableSettings.hasOwnProperty(settingKey)) {
    result = {
      key: settingKey,
      value: availableSettings[settingKey]
    };
  } else {
    result = { 
      error: 'Setting not found', 
      key: settingKey,
      available_settings: Object.keys(availableSettings)
    };
  }
} else {
  // No key provided, return all settings
  result = {
    settings: availableSettings,
    available_keys: Object.keys(availableSettings)
  };
}

return [{ json: result }];`,
    };

    @node({
        id: '7523e103-a219-483d-b429-27e24b1b3ef7',
        name: 'Company Response',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [752, -1568],
    })
    CompanyResponse = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '564aa941-40c9-4792-a87e-7475f871e873',
        name: 'Query Response',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [-368, -512],
    })
    QueryResponse = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '2fc08566-7f6b-4466-bbbc-696f9671cac4',
        name: 'Setting Response',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [-368, 576],
    })
    SettingResponse = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '304f247c-7293-44fc-bf8a-ad66ae7728f3',
        webhookId: 'company-webhook',
        name: 'Company Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-592, -1520],
        credentials: { httpBasicAuth: { id: 'm44SrEHRVzHZlXiw', name: 'Settings Auth [env-managed]' } },
    })
    CompanyWebhook = {
        path: 'company',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: '2fad5380-6e4f-42fa-8e24-0827996371ec',
        webhookId: 'query-webhook',
        name: 'Query Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-592, -736],
    })
    QueryWebhook = {
        path: 'query',
        options: {},
    };

    @node({
        id: '843d9add-93e5-4b57-b854-d5e61d32a80d',
        name: 'KVStorage',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [-368, -1520],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    Kvstorage = {
        operation: 'get',
        propertyName: 'cached',
        key: 'indox.settings.companies',
        options: {},
    };

    @node({
        id: 'fc939e2e-4e37-4016-922e-a6ce455dd1ec',
        name: 'If Found Cache',
        /*__n8n__*/ notes: "Reads the Redis GET above (property `cached`, a JSON string).",
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-144, -1520],
    })
    IfFoundCache = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: '30391b3a-9b77-4a8a-9004-56c86cb2328a',
                    leftValue: '={{ $json.cached }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '2e000c82-4a09-46c1-97fa-67a956f6517a',
        name: 'KVStorage1',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [304, -1376],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    Kvstorage1 = {
        operation: 'set',
        key: 'indox.settings.companies',
        value: '={{ JSON.stringify($json) }}',
        keyType: 'string',
        expire: true,
        ttl: 1200,
    };

    @node({
        id: '802470fa-b683-468a-9449-8a72dd171d20',
        name: 'Settings Data',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [304, -1568],
    })
    SettingsData = {};

    @node({
        id: '2fa7fe71-36de-4c55-ac45-595f478b39c5',
        name: 'Code',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [80, -1568],
    })
    Code = {
        mode: 'runOnceForEachItem',
        jsCode: `// Cache hit: the Redis GET above put a JSON STRING in \`cached\` (kvStorage used to hand
// back a live object under val[0]). Parse it defensively — a malformed/partial value
// must read as a MISS, never as an empty settings object, which would silently blank
// every setting the caller depends on.
const raw = $json.cached;
let parsed = null;
try { parsed = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (e) { parsed = null; }
if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || !Object.keys(parsed).length) {
  throw new Error('settings cache value at this key was unusable (' + typeof raw + 
                  ') — refusing to serve an empty settings object');
}
return { ...parsed };`,
    };

    @node({
        id: '29981279-a9ac-491e-90aa-da81487884f0',
        name: 'Execution Data',
        type: 'n8n-nodes-base.executionData',
        version: 1.1,
        position: [-144, 1248],
    })
    ExecutionData = {
        dataToSave: {
            values: [
                {
                    key: 'TRIGGERED_FROM',
                    value: '={{ $json.TRIGGERED_FROM || "UNKNOWN" }}',
                },
            ],
        },
    };

    @node({
        id: 'f2e57dd3-ac5d-4cb5-a595-737b8c7f2b67',
        name: 'Company Response1',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [752, -1152],
    })
    CompanyResponse1 = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '20119911-0dc3-4316-9a18-2124ae235e96',
        name: 'KVStorage2',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [-368, -1104],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    Kvstorage2 = {
        operation: 'get',
        propertyName: 'cached',
        key: 'indox.settings.keyval',
        options: {},
    };

    @node({
        id: '583ed6fd-6b17-46bf-863d-cc2d4f173906',
        name: 'If Found Cache1',
        /*__n8n__*/ notes: "Reads the Redis GET above (property `cached`, a JSON string).",
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-144, -1104],
    })
    IfFoundCache1 = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: '30391b3a-9b77-4a8a-9004-56c86cb2328a',
                    leftValue: '={{ $json.cached }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '5fe4582b-105b-429b-aea8-482e71a32cf8',
        name: 'KVStorage3',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [304, -960],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    Kvstorage3 = {
        operation: 'set',
        key: 'indox.settings.keyval',
        value: '={{ JSON.stringify($json) }}',
        keyType: 'string',
        expire: true,
        ttl: 1200,
    };

    @node({
        id: 'd7370cae-8f02-4ae8-a375-54d1d42bc725',
        name: 'Settings Data1',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [304, -1152],
    })
    SettingsData1 = {};

    @node({
        id: 'a951e75c-20ff-4ab1-8c6a-4689362b5a97',
        name: 'Code1',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [80, -1152],
    })
    Code1 = {
        mode: 'runOnceForEachItem',
        jsCode: `// Cache hit: the Redis GET above put a JSON STRING in \`cached\` (kvStorage used to hand
// back a live object under val[0]). Parse it defensively — a malformed/partial value
// must read as a MISS, never as an empty settings object, which would silently blank
// every setting the caller depends on.
const raw = $json.cached;
let parsed = null;
try { parsed = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (e) { parsed = null; }
if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || !Object.keys(parsed).length) {
  throw new Error('settings cache value at this key was unusable (' + typeof raw + 
                  ') — refusing to serve an empty settings object');
}
return { ...parsed };`,
    };

    @node({
        id: 'd7077cf6-c7a3-4579-8f2c-e037e8140058',
        webhookId: 'company-webhook',
        name: 'Settings Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-592, -1104],
        credentials: { httpBasicAuth: { id: 'm44SrEHRVzHZlXiw', name: 'Settings Auth [env-managed]' } },
    })
    SettingsWebhook = {
        path: 'setting',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'b136eb81-4bb4-478f-87b6-7f0f0ffc9f7d',
        name: 'Handle Settings Request',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [528, -1152],
    })
    HandleSettingsRequest = {
        jsCode: `// Handle company lookup requests
const queryParams = $('Settings Webhook').first().json.query;
const settings = $('Settings Data1').first().json;

let result = {};

// Check what parameter was provided
if (queryParams.key) {
  // Look up by company name
  if (settings[queryParams.key]) {
    result = {
      key: queryParams.key,
      val: settings[queryParams.key]
    };
  } else {
    result = { error: 'Settings key not found', key: queryParams.key };
  }
} else {
    result = { ...settings};
  }


return [{ json: result }];`,
    };

    @node({
        id: 'fa97ed00-9f39-4962-b300-e6756bf507d5',
        name: 'Load Companies For API',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [80, -1376],
        retryOnFail: true,
        waitBetweenTries: 5000,
    })
    LoadCompaniesForApi = {
        workflowId: {
            __rl: true,
            value: 'indoxSettings01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxSettings01',
            cachedResultName: 'Settings',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                load_settings: false,
                load_companies: true,
                load_queries: false,
                TRIGGERED_FROM: 'COMPANIES_API',
                __instance:
                    "={{ $json.__instance || (() => { try { const t = ($('When Executed by Another Workflow').first().json || {}); if (t.__instance) return String(t.__instance); } catch (e) {} for (const w of ['Company Webhook','Settings Webhook','Queries Webhook','All Setting Webhook']) { try { const q = (($(w).first().json || {}).query || {}); if (q.__instance) return String(q.__instance); } catch (e) {} } return ''; })() }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'load_settings',
                    displayName: 'load_settings',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_companies',
                    displayName: 'load_companies',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_queries',
                    displayName: 'load_queries',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                    removed: false,
                },
                {
                    id: 'TRIGGERED_FROM',
                    displayName: 'TRIGGERED_FROM',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: '9e562483-9a90-4e82-a862-5b496f97a99d',
        name: 'Load Settings For API1',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [80, -960],
        retryOnFail: true,
        waitBetweenTries: 5000,
    })
    LoadSettingsForApi1 = {
        workflowId: {
            __rl: true,
            value: 'indoxSettings01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxSettings01',
            cachedResultName: 'Settings',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                load_settings: true,
                load_companies: false,
                load_queries: false,
                TRIGGERED_FROM: 'COMPANIES_API',
                __instance:
                    "={{ $json.__instance || (() => { try { const t = ($('When Executed by Another Workflow').first().json || {}); if (t.__instance) return String(t.__instance); } catch (e) {} for (const w of ['Company Webhook','Settings Webhook','Queries Webhook','All Setting Webhook']) { try { const q = (($(w).first().json || {}).query || {}); if (q.__instance) return String(q.__instance); } catch (e) {} } return ''; })() }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'load_settings',
                    displayName: 'load_settings',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_companies',
                    displayName: 'load_companies',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_queries',
                    displayName: 'load_queries',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                    removed: false,
                },
                {
                    id: 'TRIGGERED_FROM',
                    displayName: 'TRIGGERED_FROM',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: 'ad6d4930-afa3-4d0d-bf80-cb20eb01d45f',
        name: 'Company Name By Identifier',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-592, 1024],
    })
    CompanyNameByIdentifier = {
        jsCode: `// Map companies to companies_by_identifiers {identifier: name}
let companies_item = $('Companies').first();
let companies_json = companies_item.json.companies;

let company_name_by_identifier = {}
Object.entries(companies_json).forEach(([name, data]) => {
  console.log(name)
  console.log(data)
  data.identifiers?.forEach(idf => company_name_by_identifier[idf] = name)
});

return [{"company_name_by_identifier":  company_name_by_identifier}];`,
    };

    @node({
        id: 'd7ae4b9a-92ec-44e2-bb87-87e126b527fd',
        name: 'Companies By Mail',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-368, 1024],
    })
    CompaniesByMail = {
        jsCode: `// Map companies to companies_by_mails {mail: name}
let companies_item = $('Companies').first();
let companies_json = companies_item.json.companies;

let company_name_by_mails = {}
let company_id_by_mails = {}

Object.entries(companies_json).forEach(([name, data]) => {
  console.log(name)
  console.log(data)
  data.mails?.forEach(idf => company_name_by_mails[idf] = name)
  data.mails?.forEach(idf => company_id_by_mails[idf] = data.identifiers?.[0])
});


return [{"company_name_by_mail":  company_name_by_mails, "company_id_by_mails": company_id_by_mails}];`,
    };

    @node({
        id: '23d3950d-b373-4770-91b4-62836ebc1648',
        name: 'All Companies Identifiers',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-144, 1024],
    })
    AllCompaniesIdentifiers = {
        jsCode: `// Returns list of all identifiers
// Map companies to companies_by_identifiers {identifier: name}
let companies_item = $('Companies').first();
let companies_json = companies_item.json.companies;

let allIdentifiers = [].concat(...Object.values(companies_json).map(data => data.identifiers || []));


return [{"all_companies_identifiers": allIdentifiers}];`,
    };

    @node({
        id: '4308849e-c531-4277-9f9a-f1f7907037d8',
        name: 'Company Response2',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [752, -288],
    })
    CompanyResponse2 = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '4083f6c0-a912-4c02-b6f4-117bcf62f0b0',
        name: 'KVStorage4',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [-368, -240],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    Kvstorage4 = {
        operation: 'get',
        propertyName: 'cached',
        key: 'indox.settings.queries',
        options: {},
    };

    @node({
        id: '052f520b-a2e7-409d-a518-73dac73f000a',
        name: 'If Found Cache2',
        /*__n8n__*/ notes: "Reads the Redis GET above (property `cached`, a JSON string).",
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-144, -240],
    })
    IfFoundCache2 = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: '30391b3a-9b77-4a8a-9004-56c86cb2328a',
                    leftValue: '={{ $json.cached }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '9976e671-a610-4b33-a4d4-3ece3a131e11',
        name: 'KVStorage5',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [304, -96],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    Kvstorage5 = {
        operation: 'set',
        key: 'indox.settings.queries',
        value: '={{ JSON.stringify($json) }}',
        keyType: 'string',
        expire: true,
        ttl: 1200,
    };

    @node({
        id: 'b2500545-f592-4956-a782-c451b950caee',
        name: 'Settings Data2',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [304, -288],
    })
    SettingsData2 = {};

    @node({
        id: '26150694-06a0-4f9d-88ce-0157184ce6d6',
        name: 'Code2',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [80, -288],
    })
    Code2 = {
        mode: 'runOnceForEachItem',
        jsCode: `// Cache hit: the Redis GET above put a JSON STRING in \`cached\` (kvStorage used to hand
// back a live object under val[0]). Parse it defensively — a malformed/partial value
// must read as a MISS, never as an empty settings object, which would silently blank
// every setting the caller depends on.
const raw = $json.cached;
let parsed = null;
try { parsed = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (e) { parsed = null; }
if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || !Object.keys(parsed).length) {
  throw new Error('settings cache value at this key was unusable (' + typeof raw + 
                  ') — refusing to serve an empty settings object');
}
return { ...parsed };`,
    };

    @node({
        id: '200b4399-5ca2-4371-a8ef-517a5c8c8f5e',
        name: 'Handle Settings Request1',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [528, -288],
    })
    HandleSettingsRequest1 = {
        jsCode: `// Handle company lookup requests
const queryParams = $('Queries Webhook').first().json.query;
const settings = $('Settings Data2').first().json;

let result = {};


result = { ...settings};


return [{ json: result }];`,
    };

    @node({
        id: '3e7f4b81-6fed-4fa7-8377-b3883c6b3959',
        name: 'Load Settings For API',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [80, -96],
        retryOnFail: true,
        waitBetweenTries: 5000,
    })
    LoadSettingsForApi = {
        workflowId: {
            __rl: true,
            value: 'indoxSettings01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxSettings01',
            cachedResultName: 'Settings',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                load_settings: false,
                load_companies: false,
                load_queries: true,
                TRIGGERED_FROM: 'COMPANIES_API',
                __instance:
                    "={{ $json.__instance || (() => { try { const t = ($('When Executed by Another Workflow').first().json || {}); if (t.__instance) return String(t.__instance); } catch (e) {} for (const w of ['Company Webhook','Settings Webhook','Queries Webhook','All Setting Webhook']) { try { const q = (($(w).first().json || {}).query || {}); if (q.__instance) return String(q.__instance); } catch (e) {} } return ''; })() }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'load_settings',
                    displayName: 'load_settings',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_companies',
                    displayName: 'load_companies',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_queries',
                    displayName: 'load_queries',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                    removed: false,
                },
                {
                    id: 'TRIGGERED_FROM',
                    displayName: 'TRIGGERED_FROM',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: '6fbf3087-f7f5-451a-ab59-e666523cfd29',
        webhookId: 'company-webhook',
        name: 'Queries Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-592, -240],
        credentials: { httpBasicAuth: { id: 'm44SrEHRVzHZlXiw', name: 'Settings Auth [env-managed]' } },
    })
    QueriesWebhook = {
        path: 'queries',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'fdd1e360-d7e8-4f8e-9392-e7645f97b996',
        name: 'Company Response3',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [528, 800],
    })
    CompanyResponse3 = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };




    @node({
        id: '761f74c1-e56a-4912-91ff-c68b6a803c8d',
        name: 'Code in JavaScript',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [304, 800],
    })
    CodeInJavascript = {
        jsCode: `// Loop over input items and add a new field called 'myNewField' to the JSON of each one
for (const item of $input.all()) {
  item.json.myNewField = 1;
}

return $input.all();`,
    };

    @node({
        id: '87637649-37f4-4db0-966a-3a67cafa1b63',
        webhookId: 'company-webhook',
        name: 'All Setting Webhook',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-592, 800],
        credentials: { httpBasicAuth: { id: 'm44SrEHRVzHZlXiw', name: 'Settings Auth [env-managed]' } },
    })
    AllSettingWebhook = {
        path: 'all_settings',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'tgsr',
        name: 'TGET Settings Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [528, 1272],
    })
    TgetSettingsReq = {
        jsCode: `// INSTANCE (indox phase 6.5). This platform loader reads INDOX's config tables on behalf of
// every app, which makes it the highest-traffic reader of them — and the one place a missing
// predicate would leak the widest. Pinned to the first instance because the label engine has
// not yet moved to the mail app (indox-final-plan §5), so this workflow has no work item to
// derive a instance from. When it moves, this is the line to change.
//
// THAT PREMISE EXPIRED (2026-08-28). This workflow's trigger now DECLARES __instance and callers
// supply it -- syncV3Unit0001's 'Prep Settings' among them -- so it does have a work item to
// derive from. Until now these three TABLE_GET builders sent only \`instance\` (the row
// DISCRIMINATOR, a COMPONENT name) and never \`__instance\` (the SCHEMA), so every settings,
// companies and tag_rules read resolved against public regardless of who asked: a levi unit ran
// on hacohen's config while reporting itself as levi. Measured 2026-08-28: 9 of the 15-in-17
// indoxApi01 calls arriving with no __instance were these three.
const INSTANCE='incoming-documents-main';
let SCHEMA='';
// [webhook tenancy 2026-08-31] The exec-trigger read covers only the sub-workflow entry; on the
// FOUR webhook entries it throws, SCHEMA stayed '' and indoxApi01 refused -- /webhook/company
// answered 500 to every v1 processor (measured: SyncProcBS 'Find Company', exec 3760905).
// The tenant rides the webhook query (?__instance=): each entry is tried in turn.
try{ SCHEMA=String(($('When Executed by Another Workflow').first().json||{}).__instance||''); }catch(e){ SCHEMA=''; }
if(!SCHEMA){ for(const w of ['Company Webhook','Settings Webhook','Queries Webhook','All Setting Webhook']){ try{ const q=(($(w).first().json||{}).query||{}); if(q.__instance){ SCHEMA=String(q.__instance); break; } }catch(e){} } }
return [{json:{INLINE_ACTION:'TABLE_GET',table:'settings', instance:INSTANCE, __instance:SCHEMA}}];`,
    };

    @node({
        id: 'cis',
        name: 'Call INDOX Settings',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [752, 1272],
    })
    CallIndoxSettings = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'tgcr',
        name: 'TGET Companies Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1648, 1272],
    })
    TgetCompaniesReq = {
        jsCode: `// INSTANCE (indox phase 6.5). This platform loader reads INDOX's config tables on behalf of
// every app, which makes it the highest-traffic reader of them — and the one place a missing
// predicate would leak the widest. Pinned to the first instance because the label engine has
// not yet moved to the mail app (indox-final-plan §5), so this workflow has no work item to
// derive a instance from. When it moves, this is the line to change.
// Premise expired 2026-08-28 — see 'Tget Settings Req' for the measurement. __instance is the
// SCHEMA and must come from the caller; INSTANCE is only the row discriminator.
const INSTANCE='incoming-documents-main';
let SCHEMA='';
// [webhook tenancy 2026-08-31] The exec-trigger read covers only the sub-workflow entry; on the
// FOUR webhook entries it throws, SCHEMA stayed '' and indoxApi01 refused -- /webhook/company
// answered 500 to every v1 processor (measured: SyncProcBS 'Find Company', exec 3760905).
// The tenant rides the webhook query (?__instance=): each entry is tried in turn.
try{ SCHEMA=String(($('When Executed by Another Workflow').first().json||{}).__instance||''); }catch(e){ SCHEMA=''; }
if(!SCHEMA){ for(const w of ['Company Webhook','Settings Webhook','Queries Webhook','All Setting Webhook']){ try{ const q=(($(w).first().json||{}).query||{}); if(q.__instance){ SCHEMA=String(q.__instance); break; } }catch(e){} } }
return [{json:{INLINE_ACTION:'TABLE_GET',table:'companies', instance:INSTANCE, __instance:SCHEMA}}];`,
    };

    @node({
        id: 'cic',
        name: 'Call INDOX Companies',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1872, 1272],
        alwaysOutputData: true,
    })
    CallIndoxCompanies = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'a10c7100-0000-4000-8000-kwcfg0000001',
        name: 'KW Config',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1100, 1800],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    KwConfig = {
        operation: 'executeQuery',
        query: `=-- Raw settings rows, q_v3_* included, as before. The extraction QUERIES are
-- read from extraction_queries by the ONE consumer that needs them
-- (indoxV2FigureCompanyId01 :: Load Company Query), not shipped to every
-- Settings caller: binding q_v3_company into this payload made it 187 KB and
-- started timing Settings out under host load.
--
-- resolver_gen_company is the identity of the COMPANY resolver: a digest of
-- q_v3_company fully bound, so it moves when the query shape changes OR when
-- the companies table changes, and not otherwise. It is PER-QUERY, not global
-- (public.extraction_queries returns a different generation for each of the 14
-- keys) -- hence the _company suffix: do NOT read it as covering the others.
-- It reaches docBaseDecide the same way max_actions_per_doc does: 'Settings
-- Output' spreads this cfg object, so it lands as a top-level settings key.
select coalesce(jsonb_object_agg(key, val), '{}'::jsonb) as cfg from (
  select key, value::jsonb as val from {{ (() => { let i = String($json.__instance || ''); if (!i) { try { i = String(($('When Executed by Another Workflow').first().json || {}).__instance || ''); } catch (e) { i = ''; } } if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxSettings01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
   where (key in ('invoice_kws','shipment_kws','bs_kws','order_kws','invoice_strong',
                  'shipment_strong','date_labels','amount_labels','activePrioritySync',
                  'max_actions_per_doc','indox_execution_mode')
          or key like 'q\\_%')
  union all
  select 'resolver_gen_company', to_jsonb(resolver_gen)
    from {{ (() => { let i = String($json.__instance || ''); if (!i) { try { i = String(($('When Executed by Another Workflow').first().json || {}).__instance || ''); } catch (e) { i = ''; } } if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxSettings01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.extraction_queries
   where key = 'q_v3_company'
) t`,
        options: {},
    };




    @node({
        id: '3efc7937-ee1f-4ab9-b5e5-c3ac7404816e',
        webhookId: 'settings-invalidate-cache-webhook',
        name: 'Invalidate Cache Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [368, 2000],
        credentials: { httpBasicAuth: { id: 'm44SrEHRVzHZlXiw', name: 'Settings Auth [env-managed]' } },
    })
    InvalidateCacheWebhook = {
        path: 'settings/invalidate-cache',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: '8498a045-5bb1-4303-bbe7-67d259a8c2e9',
        name: 'Clear Cache 1',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [-592, 2000],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    ClearCache1 = {
        operation: 'delete',
        key: 'indox.settings.companies',
    };

    @node({
        id: 'fce8cc25-f435-41f8-87fd-ab8706f5b08f',
        name: 'Clear Cache 2',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [-352, 2000],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    ClearCache2 = {
        operation: 'delete',
        key: 'indox.settings.keyval',
    };

    @node({
        id: '9d73e98c-b618-47ad-b60f-12c332d71ee6',
        name: 'Clear Cache 3',
        /*__n8n__*/ notes: "Redis-backed (Layer A, 2026-08-06). Was n8n-nodes-kv-storage, whose map is per-PROCESS: with EXECUTIONS_MODE=queue and 3 execution processes each kept its own copy and the invalidate webhook could only clear one of them. Node name kept from the KVStorage era so the graph wiring is untouched.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [-112, 2000],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    ClearCache3 = {
        operation: 'delete',
        key: 'indox.settings.queries',
    };

    @node({
        id: 'ac1b6a33-f314-44a2-91d9-e68b93b4ea3e',
        name: 'Invalidate Cache Response',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [128, 2000],
    })
    InvalidateCacheResponse = {
        respondWith: 'json',
        responseBody: '={{ { ok: true, cleared: ["companies_settings", "key_val_settings", "key_val_queries"] } }}',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.InvoiceIdQuery.out(0).to(this.ShippingIdQuery.in(0));
        this.ShippingIdQuery.out(0).to(this.CentralizedInvoiceIdQuery.in(0));
        this.CentralizedInvoiceIdQuery.out(0).to(this.PurchaseOrderIdQuery.in(0));
        this.Companies.out(0).to(this.IfLoadQueries.in(0));
        this.Settings.out(0).to(this.IfLoadCompanies.in(0));
        this.SettingsLoaderStart.out(0).to(this.Start.in(0));
        this.IfLoadQueries.out(0).to(this.InvoiceIdQuery.in(0));
        this.IfLoadQueries.out(1).to(this.SettingsOutput.in(0));
        this.IfLoadCompanies.out(0).to(this.TgetCompaniesReq.in(0));
        this.IfLoadCompanies.out(1).to(this.IfLoadQueries.in(0));
        this.IfLoadSettings.out(0).to(this.TgetSettingsReq.in(0));
        this.IfLoadSettings.out(1).to(this.IfLoadCompanies.in(0));
        this.PurchaseOrderIdQuery.out(0).to(this.CompanyIdQuery.in(0));
        this.CompanyIdQuery.out(0).to(this.KwConfig.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.Start.in(0));
        this.Start.out(0).to(this.IfLoadSettings.in(0));
        this.HandleCompanyRequest.out(0).to(this.CompanyResponse.in(0));
        this.HandleQueryRequest.out(0).to(this.QueryResponse.in(0));
        this.HandleSettingRequest.out(0).to(this.SettingResponse.in(0));
        this.CompanyWebhook.out(0).to(this.Kvstorage.in(0));
        this.Kvstorage.out(0).to(this.IfFoundCache.in(0));
        this.IfFoundCache.out(0).to(this.Code.in(0));
        this.IfFoundCache.out(1).to(this.LoadCompaniesForApi.in(0));
        this.SettingsData.out(0).to(this.HandleCompanyRequest.in(0));
        this.Code.out(0).to(this.SettingsData.in(0));
        this.Kvstorage2.out(0).to(this.IfFoundCache1.in(0));
        this.IfFoundCache1.out(0).to(this.Code1.in(0));
        this.IfFoundCache1.out(1).to(this.LoadSettingsForApi1.in(0));
        this.SettingsData1.out(0).to(this.HandleSettingsRequest.in(0));
        this.Code1.out(0).to(this.SettingsData1.in(0));
        this.SettingsWebhook.out(0).to(this.Kvstorage2.in(0));
        this.HandleSettingsRequest.out(0).to(this.CompanyResponse1.in(0));
        this.LoadCompaniesForApi.out(0).to(this.Kvstorage1.in(0));
        this.LoadCompaniesForApi.out(0).to(this.SettingsData.in(0));
        this.LoadSettingsForApi1.out(0).to(this.Kvstorage3.in(0));
        this.LoadSettingsForApi1.out(0).to(this.SettingsData1.in(0));
        this.CompanyNameByIdentifier.out(0).to(this.CompaniesByMail.in(0));
        this.CompaniesByMail.out(0).to(this.AllCompaniesIdentifiers.in(0));
        this.Kvstorage4.out(0).to(this.IfFoundCache2.in(0));
        this.IfFoundCache2.out(0).to(this.Code2.in(0));
        this.IfFoundCache2.out(1).to(this.LoadSettingsForApi.in(0));
        this.SettingsData2.out(0).to(this.HandleSettingsRequest1.in(0));
        this.Code2.out(0).to(this.SettingsData2.in(0));
        this.HandleSettingsRequest1.out(0).to(this.CompanyResponse2.in(0));
        this.LoadSettingsForApi.out(0).to(this.Kvstorage5.in(0));
        this.LoadSettingsForApi.out(0).to(this.SettingsData2.in(0));
        this.QueriesWebhook.out(0).to(this.Kvstorage4.in(0));
        this.HttpRequest.out(0).to(this.HTTPRequest2.in(0));
        this.HttpRequest1.out(0).to(this.CodeInJavascript.in(0));
        this.CodeInJavascript.out(0).to(this.CompanyResponse3.in(0));
        this.TgetSettingsReq.out(0).to(this.CallIndoxSettings.in(0));
        this.CallIndoxSettings.out(0).to(this.Settings.in(0));
        this.TgetCompaniesReq.out(0).to(this.CallIndoxCompanies.in(0));
        this.CallIndoxCompanies.out(0).to(this.Companies.in(0));
        this.KwConfig.out(0).to(this.SettingsOutput.in(0));
        this.InvalidateCacheWebhook.out(0).to(this.ClearCache1.in(0));
        this.ClearCache1.out(0).to(this.ClearCache2.in(0));
        this.ClearCache2.out(0).to(this.ClearCache3.in(0));
        this.ClearCache3.out(0).to(this.InvalidateCacheResponse.in(0));
    }
}
