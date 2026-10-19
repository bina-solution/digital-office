import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Google Sheets MCP Server - agent.hacohen
// Nodes   : 23  |  Connections: 6
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// McpServerTrigger                   mcpTrigger                 [AI] [creds]
// GoogleSheetsReadData               googleSheetsTool           [creds]
// GoogleSheetsClearData              googleSheetsTool           [creds]
// GoogleSheetsAddData                googleSheetsTool           [creds]
// GoogleSheetsCreateSheet            googleSheetsTool           [creds]
// GoogleSheetsUpdateData             googleSheetsTool           [creds]
// StickyNoteOverview                 stickyNote
// StickyNoteMcpTrigger               stickyNote
// StickyNoteReadData                 stickyNote
// StickyNoteClearData                stickyNote
// StickyNoteAddData                  stickyNote
// StickyNoteCreateSheet              stickyNote
// StickyNoteUpdateData               stickyNote
// GoogleSheetsDeleteSheet            googleSheetsTool           [creds]
// StickyNoteDeleteSheet              stickyNote
// AutomationvaluesToolInput          executeWorkflowTrigger
// ReadAutomationvaluesSourceSheet    googleSheets               [creds]
// BuildAutomationvaluesResponse      code
// AutomationvaluesQuery              toolWorkflow               [ai_tool]
// RouteAutomationvaluesOperation     switch
// PrepareIncomingLookup              code
// IncomingDocumentsFilteredQuery     googleSheets               [onError→out(1)] [creds] [alwaysOutput]
// BuildIncomingDocumentsResponse     code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// AutomationvaluesToolInput
//    → RouteAutomationvaluesOperation
//      → PrepareIncomingLookup
//        → IncomingDocumentsFilteredQuery
//          → BuildIncomingDocumentsResponse
//     .out(1) → ReadAutomationvaluesSourceSheet
//        → BuildAutomationvaluesResponse
//
// AI CONNECTIONS
// McpServerTrigger.uses({ ai_tool: [AutomationvaluesQuery] })
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"AutomationValues Tool Input":{"main":[[{"node":"Route AutomationValues Operation","type":"main","index":0}]]},"Read AutomationValues Source Sheet":{"main":[[{"node":"Build AutomationValues Response","type":"main","index":0}]]},"AutomationValues Query":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"Route AutomationValues Operation":{"main":[[{"node":"Prepare Incoming Lookup","type":"main","index":0}],[{"node":"Read AutomationValues Source Sheet","type":"main","index":0}]]},"Prepare Incoming Lookup":{"main":[[{"node":"Incoming Documents Filtered Query","type":"main","index":0}]]},"Incoming Documents Filtered Query":{"main":[[{"node":"Build Incoming Documents Response","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"AppTagGwa000001a","name":"gwa-app"},{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"name":"app:google-workspace-age"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-06-29T10:06:58.177Z","createdAt":"2026-06-29T10:06:58.177Z","role":"workflow:owner","workflowId":"gSheetMcpAgent01","projectId":"Wx6WPGz1tIrghF2r","project":{"updatedAt":"2026-06-29T10:06:28.586Z","createdAt":"2026-06-29T10:02:30.215Z","id":"Wx6WPGz1tIrghF2r","name":"Shlomo Laptop <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"147f2398-75f7-4139-8132-7c477ee5cdfd"}}],
    id: 'gSheetMcpAgent01',
    name: 'Google Sheets MCP Server - agent.hacohen',
    active: true,
    isArchived: false,
    tags: ['gwa-app', 'lifecycle:test'],
    settings: { executionOrder: 'v1', callerPolicy: 'workflowsFromSameOwner', availableInMCP: false },
})
export class GoogleSheetsMcpServerAgentHacohenWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '85846eda-cf7f-49a1-a4da-b4bf36e81ae6',
        webhookId: '7660d62c-e86e-4984-9a4f-ee0a727a8002',
        name: 'MCP Server Trigger',
        /*__n8n__*/ notes: "🚀 MCP TRIGGER\n\nThis is the entry point for AI interactions with Google Sheets. The MCP (Model Context Protocol) trigger allows AI models to call any of the connected Google Sheets tools based on user requests.\n\nKey Features:\n• Enables natural language spreadsheet commands\n• Routes AI requests to appropriate Sheets operations\n• Provides context-aware data management\n• Supports complex multi-step data workflows\n• Handles dynamic sheet and document selection",
        type: '@n8n/n8n-nodes-langchain.mcpTrigger',
        version: 2,
        position: [1000, 420],
        credentials: { httpHeaderAuth: { id: '2qKUrcv37UXZbz7u', name: 'Header Auth account [env-managed]' } },
    })
    McpServerTrigger = {
        path: 'gsheet-agent',
        authentication: 'headerAuth',
    };

    @node({
        id: '8c2b82d3-f571-4af5-87ac-b26b46a2985c',
        name: 'Google Sheets - Read Data',
        /*__n8n__*/ notes: "📊 READ SPREADSHEET DATA\n\nRetrieve and analyze data from Google Sheets. Perfect for AI to read, process, and extract insights from spreadsheet content.\n\nUse Cases:\n• \"Read data from the Sales sheet\"\n• \"Get all entries from A1:E100\"\n• \"Show me the data in the Budget spreadsheet\"\n• \"Extract customer information from the CRM sheet\"\n\nAI Parameters:\n• Document_ID: Target spreadsheet ID\n• Sheet_Name: Specific sheet tab name\n• Range: Cell range to read (optional)\n\nProduction AutomationValues shortcuts:\n- Document_ID `1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U`\n- For the companies sheet, pass Sheet_Name as gid `749586510` (display name `חברות`).\n- For incoming documents, pass Sheet_Name as gid `542119184` (display name `מסמכים נכנסים`).\n- For settings, pass Sheet_Name as gid `1467881049` (display name `הגדרות`).\nIf asked for latest/last rows, read the relevant sheet once and return the last rows from the result.\n\nSafety: this generic read is range-bounded. If no Range is supplied it reads A1:Z200 only. For AutomationValues summary/count/latest-row questions, prefer the AutomationValuesQuery tool because it returns compact results and avoids sending full sheets to the agent.\n\nSafety: this generic read is range-bounded. If no Range is supplied it reads A1:Z200 only. For AutomationValues summary/count/latest-row questions, prefer AutomationValuesQuery.",
        type: 'n8n-nodes-base.googleSheetsTool',
        version: 4.6,
        position: [680, 740],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    GoogleSheetsReadData = {
        options: {
            dataLocationOnSheet: {
                values: {
                    rangeDefinition: 'specifyRangeA1',
                    range: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Range', `A1:Z200`, 'string') }}",
                },
            },
        },
        sheetName: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Sheet_Name', ``, 'string') }}",
        },
        documentId: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_ID', ``, 'string') }}",
        },
    };

    @node({
        id: 'e606582e-2fea-4052-b8a4-875a0ae8f42e',
        name: 'Google Sheets - Clear Data',
        /*__n8n__*/ notes: "🗑️ CLEAR SPREADSHEET DATA\n\nRemove data from specific ranges or entire sheets. Useful for resetting data, clearing temporary calculations, or preparing sheets for new data.\n\nUse Cases:\n• \"Clear all data from the temp sheet\"\n• \"Remove entries from A1:E100\"\n• \"Clean up the old data in column C\"\n• \"Reset the calculation area\"\n\nAI Parameters:\n• Document_ID: Target spreadsheet ID\n• Sheet_Name: Sheet to clear data from\n• Range: Specific range to clear\n\n⚠️ Use with caution - data will be permanently removed!",
        type: 'n8n-nodes-base.googleSheetsTool',
        version: 4.6,
        position: [800, 960],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    GoogleSheetsClearData = {
        operation: 'clear',
        sheetName: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Sheet_Name', ``, 'string') }}",
        },
        documentId: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_ID', ``, 'string') }}",
        },
    };

    @node({
        id: 'd73fb9da-e492-45bb-8c47-16a375ff48de',
        name: 'Google Sheets - Add Data',
        /*__n8n__*/ notes: "➕ ADD NEW DATA\n\nAppend new rows of data to existing sheets. Perfect for adding records, logging events, or inserting new entries without affecting existing data.\n\nUse Cases:\n• \"Add a new customer to the CRM sheet\"\n• \"Log today's sales data\"\n• \"Insert a new project entry\"\n• \"Record the meeting notes\"\n\nAI Parameters:\n• Document_ID: Target spreadsheet ID\n• Sheet_Name: Sheet to add data to\n• Data_To_Add: Array/object of new data\n\nFeatures:\n• Automatically finds next empty row\n• Preserves existing data\n• Supports multiple columns",
        type: 'n8n-nodes-base.googleSheetsTool',
        version: 4.6,
        position: [1240, 940],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    GoogleSheetsAddData = {
        columns: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Data_To_Add', ``, 'string') }}",
        options: {},
        operation: 'append',
        sheetName: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Sheet_Name', ``, 'string') }}",
        },
        documentId: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_ID', ``, 'string') }}",
        },
    };

    @node({
        id: '485f44aa-ae5e-4baf-9a3b-6ca43a58d59e',
        name: 'Google Sheets - Create Sheet',
        /*__n8n__*/ notes: "📋 CREATE NEW SHEET\n\nCreate new worksheet tabs within existing spreadsheets. Great for organizing data into categories or creating project-specific sheets.\n\nUse Cases:\n• \"Create a new sheet called 'Q4 Sales'\"\n• \"Add a Project Timeline sheet\"\n• \"Make a new Budget 2024 tab\"\n• \"Create a sheet for customer feedback\"\n\nAI Parameters:\n• Document_ID: Target spreadsheet ID\n• New_Sheet_Name: Name for the new sheet\n• Header_Row: Optional column headers\n\nBest Practices:\n• Use descriptive sheet names\n• Include header rows for data structure\n• Consider sheet organization strategy",
        type: 'n8n-nodes-base.googleSheetsTool',
        version: 4.6,
        position: [1560, 960],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    GoogleSheetsCreateSheet = {
        options: {},
        operation: 'create',
        documentId: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_ID', ``, 'string') }}",
        },
    };

    @node({
        id: '30dfee2a-fdf0-48e0-bb8d-08a574ced352',
        name: 'Google Sheets - Update Data',
        /*__n8n__*/ notes: "✏️ UPDATE EXISTING DATA\n\nModify specific cells or ranges with new values. Perfect for updating records, correcting data, or maintaining current information.\n\nUse Cases:\n• \"Update the status in cell C5 to 'Complete'\"\n• \"Change the price in the product list\"\n• \"Modify the project deadline\"\n• \"Update customer contact information\"\n\nAI Parameters:\n• Document_ID: Target spreadsheet ID\n• Sheet_Name: Sheet containing data to update\n• Range: Specific cells to update (e.g., A1:B2)\n• New_Values: Array of new values\n\nTip: Use precise ranges to avoid overwriting unintended data",
        type: 'n8n-nodes-base.googleSheetsTool',
        version: 4.6,
        position: [1700, 740],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    GoogleSheetsUpdateData = {
        options: {},
        operation: 'update',
        sheetName: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Sheet_Name', ``, 'string') }}",
        },
        documentId: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_ID', ``, 'string') }}",
        },
    };

    @node({
        id: 'acc210e5-0873-4da9-9e55-c59a0a413ce8',
        name: 'Sticky Note - Overview',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-180, 140],
    })
    StickyNoteOverview = {
        color: 4,
        width: 420,
        height: 544,
        content: `## 🎯 WORKFLOW OVERVIEW

**Google Sheets MCP - AI-Powered Spreadsheet Management**

This workflow provides a complete toolkit for intelligent spreadsheet management through AI interactions using the Model Context Protocol (MCP).

**Core Capabilities:**
• 📊 Read and analyze spreadsheet data
• ➕ Add new records and entries
• ✏️ Update existing information
• 🗑️ Clear data and reset ranges
• 📋 Create new worksheet tabs
• 🤖 Natural language commands

**Getting Started:**
1. Ensure Google Sheets OAuth2 is configured
2. Test each tool individually
3. Use natural language with your AI
4. Monitor workflow execution logs
5. Start with simple read operations`,
    };

    @node({
        id: 'e906915d-868e-4491-8cb2-dcc7906a604a',
        name: 'Sticky Note - MCP Trigger',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [700, 260],
    })
    StickyNoteMcpTrigger = {
        color: 7,
        width: 600,
        height: 324,
        content: `## 🚀 Google Sheets MCP - AI-Powered Spreadsheet Management
**What it does:**
This is the entry point for AI interactions with Google Sheets. The MCP trigger enables natural language spreadsheet commands.

**Key Features:**
• Enables conversational data management
• Routes AI requests to appropriate operations
• Supports dynamic sheet selection
• Handles complex multi-step workflows
• Provides context-aware responses

**Example Commands:**
"Read data from the Sales sheet"
"Add a new customer record"
"Update the project status"
"Create a new budget sheet"`,
    };

    @node({
        id: 'cf61c826-e464-4071-ad3d-011aef99e1c3',
        name: 'Sticky Note - Read Data',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [380, 700],
    })
    StickyNoteReadData = {
        width: 300,
        height: 264,
        content: `## 📊 READ DATA

**Purpose:**
Retrieve and analyze data from Google Sheets for AI processing and insights.

**Use Cases:**
• "Show me all customer data"
• "Read the sales figures from Q3"
• "Get project status from column D"
• "Extract budget information"

**AI Parameters:**
• **Document_ID:** Spreadsheet identifier
• **Sheet_Name:** Target worksheet tab
• **Range:** Cell range (optional)

**Returns:** Raw data for AI analysis`,
    };

    @node({
        id: '5f72082c-1db4-4645-830e-24b1c773e7a0',
        name: 'Sticky Note - Clear Data',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [720, 1080],
    })
    StickyNoteClearData = {
        color: 3,
        width: 300,
        height: 264,
        content: `## 🗑️ CLEAR DATA

**Purpose:**
Remove data from specific ranges or entire sheets safely and efficiently.

**Use Cases:**
• "Clear the temporary calculations"
• "Remove old data from column C"
• "Reset the input area"
• "Clean up test entries"

**AI Parameters:**
• **Document_ID:** Target spreadsheet
• **Sheet_Name:** Sheet to clear
• **Range:** Specific area to clear

**⚠️ Warning:** Data removal is permanent`,
    };

    @node({
        id: '96caf21f-d904-425a-ad34-2360dfadb512',
        name: 'Sticky Note - Add Data',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [1140, 1060],
    })
    StickyNoteAddData = {
        color: 7,
        width: 300,
        height: 264,
        content: `## ➕ ADD DATA

**Purpose:**
Append new records to existing sheets without affecting current data.

**Use Cases:**
• "Add new customer: John Doe, email@example.com"
• "Log today's sales: $1,500"
• "Insert project milestone"
• "Record meeting attendance"

**AI Parameters:**
• **Document_ID:** Target spreadsheet
• **Sheet_Name:** Destination sheet
• **Data_To_Add:** New row data

**Feature:** Auto-finds next empty row`,
    };

    @node({
        id: '619266af-fddc-4513-9d5d-dad87bec1372',
        name: 'Sticky Note - Create Sheet',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [1660, 1020],
    })
    StickyNoteCreateSheet = {
        color: 5,
        width: 300,
        height: 264,
        content: `## 📋 CREATE SHEET

**Purpose:**
Create new worksheet tabs for better data organization and project management.

**Use Cases:**
• "Create 'Q4 Budget' sheet"
• "Add new project tracking tab"
• "Make customer feedback sheet"
• "Create monthly report tab"

**AI Parameters:**
• **Document_ID:** Target spreadsheet
• **New_Sheet_Name:** Tab name
• **Header_Row:** Column headers

**Tip:** Use descriptive names`,
    };

    @node({
        id: '00e466ab-52cf-4848-b830-49a324312c93',
        name: 'Sticky Note - Update Data',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [1820, 700],
    })
    StickyNoteUpdateData = {
        color: 3,
        width: 300,
        height: 264,
        content: `## ✏️ UPDATE DATA

**Purpose:**
Modify specific cells with new values while preserving surrounding data.

**Use Cases:**
• "Update status in C5 to 'Complete'"
• "Change price in product list"
• "Modify project deadline"
• "Update contact information"

**AI Parameters:**
• **Document_ID:** Target spreadsheet
• **Sheet_Name:** Source sheet
• **Range:** Cells to update (e.g., A1:B2)
• **New_Values:** Replacement data

**Tip:** Use precise cell references`,
    };

    @node({
        id: '7a2db25c-df9b-4889-bbd7-978dc7752148',
        name: 'Google Sheets - Delete Sheet',
        /*__n8n__*/ notes: "🗑️ DELETE SHEET\n\nRemove entire worksheet tabs when they're no longer needed. Use with caution as this permanently removes all data in the sheet.\n\nUse Cases:\n• \"Delete the old temp sheet\"\n• \"Remove the expired project tab\"\n• \"Clean up test worksheets\"\n• \"Delete duplicate sheets\"\n\nAI Parameters:\n• Document_ID: Target spreadsheet ID\n• Sheet_Name: Sheet tab to delete\n\n⚠️ PERMANENT ACTION - Cannot be undone!\nAlways backup important data first.",
        type: 'n8n-nodes-base.googleSheetsTool',
        version: 4.6,
        position: [1640, 280],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    GoogleSheetsDeleteSheet = {
        operation: 'deleteSheet',
        documentId: {
            __rl: true,
            mode: 'list',
            value: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_ID', ``, 'string') }}",
        },
    };

    @node({
        id: '1e8ed3ca-c35a-4153-a094-4eed0d55609c',
        name: 'Sticky Note - Delete Sheet',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [1700, 340],
    })
    StickyNoteDeleteSheet = {
        color: 4,
        width: 300,
        height: 284,
        content: `## 🗑️ DELETE SHEET

**Purpose:**
Permanently remove entire worksheet tabs and all their contained data.

**Use Cases:**
• "Delete the old testing sheet"
• "Remove expired project tabs"
• "Clean up temporary worksheets"
• "Delete duplicate or unused sheets"

**AI Parameters:**
• **Document_ID:** Target spreadsheet
• **Sheet_Name:** Tab to remove

**⚠️ CRITICAL WARNING:**
This permanently deletes ALL data in the sheet.
Operation cannot be undone!
Always backup important data first.`,
    };

    @node({
        id: '847269ee-0540-4b04-bf2b-927ead6c326d',
        name: 'AutomationValues Tool Input',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [240, 1380],
    })
    AutomationvaluesToolInput = {
        workflowInputs: {
            values: [
                {
                    name: 'operation',
                },
                {
                    name: 'companyName',
                },
                {
                    name: 'monthsBack',
                },
                {
                    name: 'maxRows',
                },
                {
                    name: 'query',
                },
                {
                    name: 'documentName',
                },
                {
                    name: 'documentId',
                },
                {
                    name: 'rowNumber',
                },
                {
                    name: 'includeFullRow',
                },
                {
                    name: 'sourceType',
                },
                {
                    name: 'status',
                },
            ],
        },
    };

    @node({
        id: 'b4af2e7d-c072-4b4f-8233-46cd8784ed10',
        name: 'Read AutomationValues Source Sheet',
        type: 'n8n-nodes-base.googleSheets',
        version: 4.6,
        position: [500, 1380],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    ReadAutomationvaluesSourceSheet = {
        options: {},
        sheetName: {
            __rl: true,
            mode: 'list',
            value: "={{ ['countIncomingDocumentsForCompany','incomingDocuments','searchIncomingDocuments','getIncomingDocumentRow','explainIncomingDocumentStatus'].includes(String($json.operation || '').trim()) ? 542119184 : 749586510 }}",
        },
        documentId: {
            __rl: true,
            mode: 'list',
            value: '1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U',
            cachedResultName: 'Incoming Documents — solutionsbina',
            cachedResultUrl: 'https://docs.google.com/spreadsheets/d/1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U/edit',
        },
    };

    @node({
        id: 'b7fac6b3-96f7-4614-bd15-cebb22d43222',
        name: 'Build AutomationValues Response',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [760, 1380],
    })
    BuildAutomationvaluesResponse = {
        jsCode: `const rows = $input.all().map(item => item.json);
const params = $('AutomationValues Tool Input').first().json;
const operation = String(params.operation || 'searchIncomingDocuments').trim();
const rawCompany = String(params.companyName || '').trim();
const rawQuery = String(params.query || params.documentName || params.documentId || '').trim();
const rawDocumentName = String(params.documentName || '').trim();
const rawDocumentId = String(params.documentId || '').trim();
const rawRowNumber = String(params.rowNumber || '').trim();
const rawSourceType = String(params.sourceType || '').trim();
const rawStatus = String(params.status || '').trim();
const includeFullRow = ['true','1','yes','כן'].includes(String(params.includeFullRow || '').trim().toLowerCase());
const monthsBack = Math.min(Math.max(parseInt(params.monthsBack || '2', 10) || 2, 1), 24);
const maxRows = Math.min(Math.max(parseInt(params.maxRows || '10', 10) || 10, 1), 25);

function normalize(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[\\u0591-\\u05C7]/g, '')
    .replace(/[\\u200e\\u200f]/g, '')
    .trim()
    .toLowerCase();
}

function getFirst(row, names) {
  for (const name of names) {
    if (row[name] !== undefined && row[name] !== null && String(row[name]).trim() !== '') return row[name];
  }
  const keys = Object.keys(row);
  for (const wanted of names.map(normalize)) {
    const key = keys.find(k => normalize(k).includes(wanted));
    if (key && row[key] !== undefined && row[key] !== null && String(row[key]).trim() !== '') return row[key];
  }
  return '';
}

function parseDate(value) {
  if (value === undefined || value === null || value === '') return null;
  if (typeof value === 'number') {
    const excelEpoch = new Date(Date.UTC(1899, 11, 30));
    const date = new Date(excelEpoch.getTime() + value * 86400000);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const text = String(value).trim();
  let match = text.match(/^(\\d{1,2})[./-](\\d{1,2})[./-](\\d{2,4})/);
  if (match) {
    const year = Number(match[3].length === 2 ? \`20\${match[3]}\` : match[3]);
    const date = new Date(Date.UTC(year, Number(match[2]) - 1, Number(match[1])));
    return Number.isNaN(date.getTime()) ? null : date;
  }
  match = text.match(/^(\\d{4})[./-](\\d{1,2})[./-](\\d{1,2})/);
  if (match) {
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function cap(value, limit = 700) {
  if (value === undefined || value === null || value === '') return undefined;
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > limit ? \`\${text.slice(0, limit)}...[truncated \${text.length - limit} chars]\` : value;
}

const importantFields = [
  'row_number','ID','NAME','COMPANY_NAME','COMPANY_ID','SHORT_DOC_ID','TYPE','STATUS','COMPANY_DOC_ID','LINK','DOC_DATE','DOC_TOTAL_AMOUNT','PURCHASE_ID','SHIPMENT_DOC_ID','SOURCE_TYPE','SOURCE_ID','SOURCE_LINK','SIZE','HASH','TIMESTAMP','REQUIRED_ACTION','TOTAL_AMOUNT','FROM_OFFICE','API_TOOLS_ID','INVOICE_ID','EX_INVOICE_ID','EX_IS_BS','FIGURE_TYPE_COMPLETED','COMPANY_NAME_COMPLETED','API_TOOLS_ID_COMPLETED','SEARCH_IN_DRIVE_COMPLETED','DOC_DATE_COMPLETED','DOC_TOTAL_AMOUNT_COMPLETED','PURCHASE_ID_COMPLETED','SHIPMENT_ID_COMPLETED','PRIORITY_SYNC_COMPLETED','PRIORITY_SYNC_COUNT','SELECTED_COMPANY_ID','SELECTED_DOC_ID','SELECTED_DOC_AMOUNT','SELECTED_DOC_DATE','SELECTED_DOC_SHIPMENT_ID','SELECTED_DOC_ORDER_ID','SELECTION_CERTAINTY','SELECTION_SOURCE','LOCKED'
];

function compact(row) {
  const out = {};
  for (const field of importantFields) {
    if (row[field] !== undefined && row[field] !== null && String(row[field]).trim() !== '') out[field] = cap(row[field], 500);
  }
  if (!out.row_number) out.row_number = row.row_number || '';
  if (!out.NAME) out.NAME = getFirst(row, ['שם מסמך', 'שם קובץ', 'File Name', 'filename']);
  if (!out.COMPANY_NAME) out.COMPANY_NAME = getFirst(row, ['שם חברה', 'שם ספק', 'חברה', 'company', 'ספק']);
  return out;
}

function fullRow(row) {
  const out = {};
  let omittedEmpty = 0;
  for (const [key, value] of Object.entries(row)) {
    if (value === undefined || value === null || String(value).trim() === '') { omittedEmpty++; continue; }
    out[key] = cap(value, 1000);
  }
  out._meta = { omittedEmptyFields: omittedEmpty, largeValuesAreTruncated: true };
  return out;
}

function searchableText(row) {
  return normalize([
    row.row_number, row.ID, row.NAME, row.COMPANY_NAME, row.COMPANY_ID, row.SHORT_DOC_ID, row.COMPANY_DOC_ID,
    row.LINK, row.SOURCE_ID, row.HASH, row.API_TOOLS_ID, row.INVOICE_ID, row.SHIPMENT_DOC_ID, row.PURCHASE_ID,
    row.REQUIRED_ACTION
  ].filter(v => v !== undefined && v !== null).join(' '));
}

function findIncomingRows() {
  const needles = [rawQuery, rawDocumentName, rawDocumentId].map(normalize).filter(Boolean);
  const companyNeedle = normalize(rawCompany);
  const sourceNeedle = normalize(rawSourceType);
  const statusNeedle = normalize(rawStatus);
  const rowNeedle = normalize(rawRowNumber);
  const scored = [];
  for (const row of rows) {
    const text = searchableText(row);
    let score = 0;
    if (rowNeedle && normalize(row.row_number).includes(rowNeedle)) score += 100;
    for (const needle of needles) {
      if (!needle) continue;
      if (normalize(row.NAME).includes(needle)) score += 60;
      if (normalize(row.SHORT_DOC_ID).includes(needle) || normalize(row.COMPANY_DOC_ID).includes(needle)) score += 45;
      if (text.includes(needle)) score += 25;
    }
    if (companyNeedle) score += normalize(row.COMPANY_NAME).includes(companyNeedle) || text.includes(companyNeedle) ? 35 : -1000;
    if (sourceNeedle) score += normalize(row.SOURCE_TYPE).includes(sourceNeedle) ? 15 : -1000;
    if (statusNeedle) score += normalize(row.STATUS).includes(statusNeedle) ? 15 : -1000;
    if (!needles.length && !companyNeedle && !sourceNeedle && !statusNeedle && !rowNeedle) score = 1;
    if (score > 0) scored.push({ row, score });
  }
  scored.sort((a, b) => b.score - a.score || Number(b.row.row_number || 0) - Number(a.row.row_number || 0));
  return scored.slice(0, maxRows).map(({ row, score }) => ({ score, row }));
}

if (operation === 'lastCompaniesRows') {
  const selected = rows.slice(-maxRows).map(compact);
  return [{ json: { response: JSON.stringify({ operation, sheet: 'חברות', returnedRows: selected.length, rows: selected }, null, 2) } }];
}

if (['searchIncomingDocuments','getIncomingDocumentRow','explainIncomingDocumentStatus','incomingDocuments'].includes(operation)) {
  const matches = findIncomingRows();
  const responseRows = matches.map(({ row, score }) => ({ score, summary: compact(row), ...(includeFullRow || operation === 'getIncomingDocumentRow' ? { fullRow: fullRow(row) } : {}) }));
  return [{ json: { response: JSON.stringify({
    operation,
    sheet: 'מסמכים נכנסים',
    query: rawQuery || null,
    documentName: rawDocumentName || null,
    documentId: rawDocumentId || null,
    companyName: rawCompany || null,
    rowNumber: rawRowNumber || null,
    totalRowsScanned: rows.length,
    returnedRows: responseRows.length,
    guidance: responseRows.length ? 'Use summary/status/action fields to explain why a document is missing, not saved, not in ERP, or what source created it. Large full-row values are capped.' : 'No matching incoming document rows found. If needed, search Drive/Gmail next by document name/company/document id.',
    rows: responseRows
  }, null, 2) } }];
}

const companyNeedle = normalize(rawCompany);
const now = new Date();
const since = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - monthsBack, now.getUTCDate()));
const dateFields = ['DOC_DATE', 'DATE', 'תאריך קליטה', 'תאריך', 'createdAt', 'Created At', 'תאריך מסמך', 'מועד קליטה', 'TIMESTAMP'];
const companyFields = ['COMPANY_NAME', 'שם חברה', 'שם ספק', 'חברה', 'company', 'ספק'];

let dateParsed = 0;
const matches = [];
for (const row of rows) {
  const rowText = normalize(Object.values(row).join(' '));
  const companyValue = normalize(getFirst(row, companyFields));
  const companyMatches = !companyNeedle || companyValue.includes(companyNeedle) || rowText.includes(companyNeedle);
  if (!companyMatches) continue;
  const dateValue = getFirst(row, dateFields);
  const date = parseDate(dateValue);
  if (date) dateParsed++;
  if (date && date >= since && date <= now) matches.push(row);
}

const sample = matches.slice(-Math.min(maxRows, 10)).map(compact);
return [{
  json: {
    response: JSON.stringify({
      operation: 'countIncomingDocumentsForCompany',
      companyName: rawCompany || null,
      monthsBack,
      since: since.toISOString().slice(0, 10),
      totalRowsScanned: rows.length,
      rowsWithParsedDate: dateParsed,
      count: matches.length,
      sampleLastMatches: sample
    }, null, 2)
  }
}];`,
    };

    @node({
        id: '54815099-cb99-45b7-8698-44a88f0d1115',
        name: 'AutomationValues Query',
        type: '@n8n/n8n-nodes-langchain.toolWorkflow',
        version: 2.2,
        position: [1120, 1380],
    })
    AutomationvaluesQuery = {
        name: 'AutomationValuesQuery',
        workflowId: {
            __rl: true,
            mode: 'id',
            value: '={{ $workflow.id }}',
        },
        description:
            'ONLY exposed Sheets MCP tool. Compact AutomationValues/incoming-documents lookup. For incoming document name/id/company/status questions use operation searchIncomingDocuments. For full row use getIncomingDocumentRow with rowNumber or documentName/query and includeFullRow true. For ERP/not saved questions use explainIncomingDocumentStatus. Never reads raw full sheet; returns capped JSON.',
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                operation:
                    "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Operation', `searchIncomingDocuments`, 'string') }}",
                companyName: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Company_Name', ``, 'string') }}",
                monthsBack: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Months_Back', `2`, 'string') }}",
                maxRows: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Max_Rows', `5`, 'string') }}",
                query: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Query', ``, 'string') }}",
                documentName: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_Name', ``, 'string') }}",
                documentId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Document_ID_Value', ``, 'string') }}",
                rowNumber: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Row_Number', ``, 'string') }}",
                includeFullRow:
                    "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Include_Full_Row', `false`, 'string') }}",
                sourceType: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Source_Type', ``, 'string') }}",
                status: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Status', ``, 'string') }}",
            },
            schema: [
                {
                    id: 'operation',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'operation',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'companyName',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'companyName',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'monthsBack',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'monthsBack',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'maxRows',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'maxRows',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'query',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'query',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'documentName',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'documentName',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'documentId',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'documentId',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'rowNumber',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'rowNumber',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'includeFullRow',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'includeFullRow',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'sourceType',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'sourceType',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'status',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'status',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
            ],
            matchingColumns: [],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
    };

    @node({
        id: 'b68fb6ee-80e3-4d3f-8688-874d2a8b3b60',
        name: 'Route AutomationValues Operation',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [-560, 420],
    })
    RouteAutomationvaluesOperation = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'da2f1e6d-f7cf-45d3-bdf5-c7c066d583d9',
                                leftValue:
                                    "={{ ['searchIncomingDocuments','getIncomingDocumentRow','explainIncomingDocumentStatus','incomingDocuments'].includes(String($json.operation || '').trim()) }}",
                                rightValue: '',
                                operator: {
                                    type: 'boolean',
                                    operation: 'true',
                                    singleValue: true,
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'fast_incoming_documents',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: '705c39f2-6749-4ab0-8108-38235f04d90c',
        name: 'Prepare Incoming Lookup',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-320, 280],
    })
    PrepareIncomingLookup = {
        jsCode: `const params = $('AutomationValues Tool Input').first().json;
const operation = String(params.operation || 'searchIncomingDocuments').trim();
const rawQuery = String(params.query || params.documentName || params.documentId || '').trim();
const documentName = String(params.documentName || '').trim();
const documentId = String(params.documentId || '').trim();
const companyName = String(params.companyName || '').trim();
const rowNumber = String(params.rowNumber || '').trim();
const sourceType = String(params.sourceType || '').trim();
const status = String(params.status || '').trim();
const includeFullRow = ['true','1','yes','כן'].includes(String(params.includeFullRow || '').trim().toLowerCase()) || operation === 'getIncomingDocumentRow';

function stripExtension(value) {
  return String(value || '').trim().replace(/\\.(pdf|jpg|jpeg|png|xlsx|docx|htm|html)$/i, '');
}
function docNumber(value) {
  const text = stripExtension(value);
  const hyphen = text.match(/[-–—](\\d{3,})\\s*$/);
  if (hyphen) return hyphen[1];
  const any = text.match(/\\b(\\d{4,})\\b/);
  return any ? any[1] : '';
}
function looksLikeFileName(value) {
  return /\\.(pdf|jpg|jpeg|png|xlsx|docx|htm|html)$/i.test(String(value || '').trim());
}

const baseName = stripExtension(documentName || rawQuery);
const number = documentId || docNumber(documentName || rawQuery);
let filters = [];
if (rowNumber) {
  filters.push({ field: 'row_number', value: rowNumber });
} else if (number) {
  filters.push({ field: 'SHORT_DOC_ID', value: number });
} else if (companyName) {
  filters.push({ field: 'COMPANY_NAME', value: companyName });
} else if (looksLikeFileName(documentName || rawQuery)) {
  filters.push({ field: 'NAME', value: String(documentName || rawQuery).trim() });
} else if (baseName) {
  filters.push({ field: 'COMPANY_NAME', value: baseName });
}

if (companyName && filters[0]?.field !== 'COMPANY_NAME' && filters.length < 2) filters.push({ field: 'COMPANY_NAME', value: companyName });
if (sourceType && filters.length < 2) filters.push({ field: 'SOURCE_TYPE', value: sourceType });
if (status && filters.length < 2) filters.push({ field: 'STATUS', value: status });
if (!filters.length) {
  filters.push({ field: 'row_number', value: '-1' });
}
// The Google Sheets node has two filter slots with AND semantics. Duplicate a
// single real filter rather than adding a fake filter that eliminates all rows.
while (filters.length < 2) filters.push({ ...filters[0] });
return [{ json: { operation, filters, includeFullRow, query: rawQuery, documentName: documentName || (looksLikeFileName(rawQuery) ? rawQuery : baseName), documentId: number || documentId || null, companyName: companyName || null } }];`,
    };

    @node({
        id: '02b2a6dd-1070-4069-bc44-4f641aaebea0',
        name: 'Incoming Documents Filtered Query',
        type: 'n8n-nodes-base.googleSheets',
        version: 4,
        position: [-80, 280],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
        onError: 'continueErrorOutput',
        alwaysOutputData: true,
    })
    IncomingDocumentsFilteredQuery = {
        documentId: {
            __rl: true,
            value: '1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U',
            mode: 'id',
            cachedResultName: 'Incoming Documents — solutionsbina',
        },
        sheetName: {
            __rl: true,
            value: 225484521,
            mode: 'list',
            cachedResultName: 'מסמכים נכנסים',
            cachedResultUrl:
                'https://docs.google.com/spreadsheets/d/1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U/edit#gid=225484521',
        },
        filtersUI: {
            values: [
                {
                    lookupColumn: "={{ $('Prepare Incoming Lookup').first().json.filters[0].field }}",
                    lookupValue: "={{ $('Prepare Incoming Lookup').first().json.filters[0].value }}",
                },
                {
                    lookupColumn: "={{ $('Prepare Incoming Lookup').first().json.filters[1].field }}",
                    lookupValue: "={{ $('Prepare Incoming Lookup').first().json.filters[1].value }}",
                },
            ],
        },
        combineFilters: 'AND',
        options: {},
    };

    @node({
        id: '687a58c8-8807-4f6a-a1d4-71bde87bbc23',
        name: 'Build Incoming Documents Response',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [160, 280],
    })
    BuildIncomingDocumentsResponse = {
        jsCode: `const input = $input.all().map(item => item.json);
const meta = $('Prepare Incoming Lookup').first().json;
const rows = input.filter(row => Object.keys(row).some(k => row[k] !== null && row[k] !== undefined && String(row[k]).trim() !== ''));
const maxRows = Math.min(Math.max(parseInt($('AutomationValues Tool Input').first().json.maxRows || '5', 10) || 5, 1), 10);
const importantFields = ['row_number','ID','NAME','COMPANY_NAME','COMPANY_ID','SHORT_DOC_ID','TYPE','STATUS','COMPANY_DOC_ID','LINK','DOC_DATE','DOC_TOTAL_AMOUNT','PURCHASE_ID','SHIPMENT_DOC_ID','SOURCE_TYPE','SOURCE_ID','SOURCE_LINK','SIZE','HASH','TIMESTAMP','REQUIRED_ACTION','TOTAL_AMOUNT','FROM_OFFICE','API_TOOLS_ID','INVOICE_ID','EX_INVOICE_ID','AI_COMPANY_ID','AI_TYPE','AI_DOC_ID','AI_DOC_DATE','AI_DOC_AMOUNT','AI_SHIPMENT_IDS','AI_ORDER_IDS','AI_EXTRACTION_COMPLETED','SELECTED_COMPANY_ID','SELECTED_DOC_ID','SELECTED_DOC_AMOUNT','SELECTED_DOC_DATE','SELECTED_DOC_SHIPMENT_ID','SELECTED_DOC_ORDER_ID','SELECTION_CERTAINTY','SELECTION_SOURCE','SELECTION_COMPLETED','SELECTION_SCORE_DEBUG','PRIORITY_SYNC_COMPLETED','PRIORITY_SYNC_COUNT','COMPANY_NAME_COMPLETED','API_TOOLS_ID_COMPLETED','SEARCH_IN_DRIVE_COMPLETED','DOC_DATE_COMPLETED','DOC_TOTAL_AMOUNT_COMPLETED','PURCHASE_ID_COMPLETED','SHIPMENT_ID_COMPLETED','INVOICE_ID_COMPLETED','LOCKED'];
function cap(value, limit = 900) {
  if (value === undefined || value === null || value === '') return undefined;
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > limit ? \`\${text.slice(0, limit)}...[truncated \${text.length - limit} chars]\` : value;
}
function compact(row) {
  const out = {};
  for (const field of importantFields) {
    if (row[field] !== undefined && row[field] !== null && String(row[field]).trim() !== '') out[field] = cap(row[field], 700);
  }
  return out;
}
function full(row) {
  const out = {};
  let omittedEmpty = 0;
  for (const [key, value] of Object.entries(row)) {
    if (value === undefined || value === null || String(value).trim() === '') { omittedEmpty++; continue; }
    out[key] = cap(value, 1200);
  }
  out._meta = { omittedEmptyFields: omittedEmpty, largeValuesAreTruncated: true };
  return out;
}
const selected = rows.slice(0, maxRows).map(row => meta.includeFullRow ? { summary: compact(row), fullRow: full(row) } : { summary: compact(row) });
return [{ json: { response: JSON.stringify({ operation: meta.operation, sheet: 'מסמכים נכנסים', filters: meta.filters.filter(f => f.field !== 'EMPTY'), query: meta.query || null, documentName: meta.documentName || null, documentId: meta.documentId || null, companyName: meta.companyName || null, returnedRows: selected.length, rows: selected, guidance: selected.length ? (meta.includeFullRow ? 'Full row included. Answer now from this result; do not call explainIncomingDocumentStatus or repeat AutomationValuesQuery for the same row.' : 'Answer from these capped fields. If the user needs full row details, call getIncomingDocumentRow once with rowNumber.') : 'No matching incoming-document row found. Search Drive/Gmail next with the same document/company identifiers.' }, null, 2) } }];`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.AutomationvaluesToolInput.out(0).to(this.RouteAutomationvaluesOperation.in(0));
        this.ReadAutomationvaluesSourceSheet.out(0).to(this.BuildAutomationvaluesResponse.in(0));
        this.RouteAutomationvaluesOperation.out(0).to(this.PrepareIncomingLookup.in(0));
        this.RouteAutomationvaluesOperation.out(1).to(this.ReadAutomationvaluesSourceSheet.in(0));
        this.PrepareIncomingLookup.out(0).to(this.IncomingDocumentsFilteredQuery.in(0));
        this.IncomingDocumentsFilteredQuery.out(0).to(this.BuildIncomingDocumentsResponse.in(0));

        this.McpServerTrigger.uses({
            ai_tool: [this.AutomationvaluesQuery.output],
        });
    }
}
