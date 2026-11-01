"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TableSheet = void 0;
const n8n_workflow_1 = require("n8n-workflow");
class TableSheet {
    constructor() {
        this.description = {
            displayName: 'Table Sheet',
            name: 'tableSheet',
            icon: 'fa:table',
            group: ['transform'],
            version: 1,
            description: 'Interact with Google Sheets as a database table',
            defaults: {
                name: 'Table Sheet',
            },
            inputs: ['main'],
            outputs: ['main'],
            credentials: [
                {
                    name: 'googleSheetsOAuth2Api',
                    required: true,
                },
            ],
            properties: [
                {
                    displayName: 'Operation',
                    name: 'operation',
                    type: 'options',
                    noDataExpression: true,
                    options: [
                        {
                            name: 'Upsert (Create or Update)',
                            value: 'upsert',
                            description: 'Create new rows or update existing ones based on matching logic',
                        },
                        {
                            name: 'Read (Get Rows)',
                            value: 'read',
                            description: 'Retrieve rows with filtering',
                        },
                        {
                            name: 'Delete',
                            value: 'delete',
                            description: 'Delete rows that match criteria',
                        },
                    ],
                    default: 'upsert',
                },
                {
                    displayName: 'Document',
                    name: 'spreadsheetId',
                    type: 'options',
                    typeOptions: {
                        loadOptionsMethod: 'getSpreadsheets',
                    },
                    default: '',
                    required: true,
                    description: 'The ID of the Google Spreadsheet. Choose from the list, or specify an ID using an expression.',
                },
                {
                    displayName: 'Sheet',
                    name: 'sheetName',
                    type: 'options',
                    typeOptions: {
                        loadOptionsMethod: 'getSheets',
                        loadOptionsDependsOn: ['spreadsheetId'],
                    },
                    default: '',
                    required: true,
                    description: 'The name of the sheet to access',
                },
                // ----------------------------------
                // UPSERT & DELETE CONFIGURATION
                // ----------------------------------
                {
                    displayName: 'Matching Strategy',
                    name: 'matchingStrategy',
                    type: 'options',
                    displayOptions: {
                        show: {
                            operation: ['upsert', 'delete'],
                        },
                    },
                    options: [
                        {
                            name: 'Auto (ID Column)',
                            value: 'auto',
                            description: 'Match by a single ID column',
                        },
                        {
                            name: 'Custom Columns',
                            value: 'custom',
                            description: 'Match by specific column combinations',
                        },
                    ],
                    default: 'auto',
                    description: 'How to identify existing rows',
                },
                {
                    displayName: 'ID Column',
                    name: 'idColumn',
                    type: 'options',
                    typeOptions: {
                        loadOptionsMethod: 'getColumns',
                        loadOptionsDependsOn: ['sheetName'],
                    },
                    default: 'ID',
                    displayOptions: {
                        show: {
                            operation: ['upsert', 'delete'],
                            matchingStrategy: ['auto'],
                        },
                    },
                    description: 'The column name that contains unique IDs',
                },
                {
                    displayName: 'Match Groups',
                    name: 'matchGroups',
                    type: 'fixedCollection',
                    displayOptions: {
                        show: {
                            operation: ['upsert', 'delete'],
                            matchingStrategy: ['custom'],
                        },
                    },
                    typeOptions: {
                        multipleValues: true,
                    },
                    placeholder: 'Add Match Group',
                    default: {},
                    options: [
                        {
                            displayName: 'Group',
                            name: 'group',
                            values: [
                                {
                                    displayName: 'Columns',
                                    name: 'columns',
                                    type: 'multiOptions',
                                    typeOptions: {
                                        loadOptionsMethod: 'getColumns',
                                        loadOptionsDependsOn: ['sheetName'],
                                    },
                                    default: [],
                                    description: 'Columns to match on',
                                },
                            ],
                        },
                    ],
                    description: 'Rows will be matched if they satisfy ANY of these groups (OR logic). Within a group, ALL columns must match (AND logic).',
                },
                {
                    displayName: 'Data Mode',
                    name: 'dataMode',
                    type: 'options',
                    displayOptions: {
                        show: {
                            operation: ['upsert'],
                        },
                    },
                    options: [
                        {
                            name: 'Auto-Map Input',
                            value: 'autoMap',
                            description: 'Map input JSON keys to Sheet Headers automatically',
                        },
                        // {
                        // 	name: 'Manual Mapping',
                        // 	value: 'manual',
                        // },
                    ],
                    default: 'autoMap',
                },
                {
                    displayName: 'Options',
                    name: 'options',
                    type: 'collection',
                    placeholder: 'Add Option',
                    default: {},
                    displayOptions: {
                        show: {
                            operation: ['upsert'],
                        },
                    },
                    options: [
                        {
                            displayName: 'Skip Unchanged',
                            name: 'skipUnchanged',
                            type: 'boolean',
                            default: true,
                            description: 'Do not update rows if values are identical',
                        },
                        {
                            displayName: 'Generate Timestamp',
                            name: 'generateTimestamp',
                            type: 'boolean',
                            default: true,
                            description: 'Update "TIMESTAMP" column if it exists',
                        },
                    ],
                },
                // ----------------------------------
                // READ CONFIGURATION
                // ----------------------------------
                {
                    displayName: 'Return',
                    name: 'readReturn',
                    type: 'options',
                    displayOptions: {
                        show: {
                            operation: ['read'],
                        },
                    },
                    options: [
                        {
                            name: 'All Rows',
                            value: 'all',
                        },
                        {
                            name: 'By Filter',
                            value: 'filter',
                        },
                    ],
                    default: 'all',
                },
                {
                    displayName: 'Filters',
                    name: 'readFilters',
                    type: 'fixedCollection',
                    displayOptions: {
                        show: {
                            operation: ['read'],
                            readReturn: ['filter'],
                        },
                    },
                    typeOptions: {
                        multipleValues: true,
                    },
                    placeholder: 'Add Filter',
                    default: {},
                    options: [
                        {
                            displayName: 'Filter',
                            name: 'filter',
                            values: [
                                {
                                    displayName: 'Column',
                                    name: 'column',
                                    type: 'options',
                                    typeOptions: {
                                        loadOptionsMethod: 'getColumns',
                                        loadOptionsDependsOn: ['sheetName'],
                                    },
                                    default: '',
                                    description: 'Column name to filter by',
                                },
                                {
                                    displayName: 'Operator',
                                    name: 'operator',
                                    type: 'options',
                                    options: [
                                        { name: 'Equal', value: 'equal' },
                                        { name: 'Contains', value: 'contains' },
                                        // { name: 'Not Equal', value: 'notEqual' },
                                    ],
                                    default: 'equal',
                                },
                                {
                                    displayName: 'Value',
                                    name: 'value',
                                    type: 'string',
                                    default: '',
                                },
                            ],
                        },
                    ],
                },
            ],
        };
        this.methods = {
            loadOptions: {
                async getSpreadsheets() {
                    const returnData = [];
                    try {
                        const response = await this.helpers.httpRequestWithAuthentication.call(this, 'googleSheetsOAuth2Api', {
                            url: 'https://www.googleapis.com/drive/v3/files',
                            method: 'GET',
                            qs: {
                                q: "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                                fields: 'files(id, name)',
                                pageSize: 100,
                                orderBy: 'modifiedByMeTime desc,name_natural',
                                includeItemsFromAllDrives: true,
                                supportsAllDrives: true,
                            },
                        });
                        if (response.files) {
                            for (const file of response.files) {
                                returnData.push({
                                    name: file.name,
                                    value: file.id,
                                });
                            }
                        }
                    }
                    catch (error) {
                        // Fail silently for loadOptions, or log to console if needed
                    }
                    return returnData;
                },
                async getSheets() {
                    const spreadsheetId = this.getNodeParameter('spreadsheetId');
                    const returnData = [];
                    const response = await this.helpers.httpRequestWithAuthentication.call(this, 'googleSheetsOAuth2Api', {
                        url: `https://sheets.googleapis.com/v4/spreadsheets/${spreadsheetId}`,
                        method: 'GET',
                        json: true,
                    });
                    if (response.sheets) {
                        for (const sheet of response.sheets) {
                            returnData.push({
                                name: sheet.properties.title,
                                value: sheet.properties.title,
                            });
                        }
                    }
                    return returnData;
                },
                async getColumns() {
                    const spreadsheetId = this.getNodeParameter('spreadsheetId');
                    const sheetName = this.getNodeParameter('sheetName');
                    const returnData = [];
                    if (!spreadsheetId || !sheetName)
                        return [];
                    const response = await this.helpers.httpRequestWithAuthentication.call(this, 'googleSheetsOAuth2Api', {
                        url: `https://sheets.googleapis.com/v4/spreadsheets/${spreadsheetId}/values/${encodeURIComponent(sheetName)}!1:1`,
                        method: 'GET',
                        json: true,
                    });
                    if (response.values && response.values.length > 0) {
                        for (const header of response.values[0]) {
                            returnData.push({
                                name: header,
                                value: header,
                            });
                        }
                    }
                    return returnData;
                },
            },
        };
    }
    async execute() {
        const items = this.getInputData();
        const operation = this.getNodeParameter('operation', 0);
        const spreadsheetId = this.getNodeParameter('spreadsheetId', 0);
        const sheetName = this.getNodeParameter('sheetName', 0);
        // Common Config
        const CONFIG = {
            spreadsheetId,
            sheetName,
            maxBatchSize: 500,
            maxRetries: 3,
            retryDelayMs: 1000,
        };
        // =========================== UTILITIES =======================================
        const utils = {
            generateId() {
                const ts = Date.now().toString(36);
                const rand = Math.random().toString(36).substring(2, 10);
                return `${ts}${rand}`;
            },
            columnToLetter(index) {
                let letter = '';
                let temp = index;
                while (temp >= 0) {
                    letter = String.fromCharCode((temp % 26) + 65) + letter;
                    temp = Math.floor(temp / 26) - 1;
                }
                return letter;
            },
            sanitize(value) {
                if (value === null || value === undefined)
                    return '';
                if (typeof value === 'object')
                    return JSON.stringify(value);
                return value;
            },
            cleanObject(obj) {
                return Object.fromEntries(Object.entries(obj).filter(([_, v]) => v !== null && v !== undefined));
            },
            sleep(ms) {
                return new Promise(resolve => setTimeout(resolve, ms));
            },
            compositeKey(obj, fields) {
                return fields.map(f => String(obj[f] || '').toLowerCase().trim()).join('|');
            },
            isEmpty(value) {
                return value === undefined || value === null || value === '' ||
                    String(value).toLowerCase() === 'unknown';
            }
        };
        // =========================== HTTP CLIENT =====================================
        const executeFunctions = this;
        async function sheetsRequest(endpoint, method = 'GET', body = null, retryCount = 0) {
            var _a;
            const baseUrl = `https://sheets.googleapis.com/v4/spreadsheets/${CONFIG.spreadsheetId}`;
            const url = `${baseUrl}${endpoint}`;
            const options = {
                method,
                headers: { 'Content-Type': 'application/json' },
                url,
                json: true,
            };
            if (body) {
                options.body = body;
            }
            try {
                const response = await executeFunctions.helpers.requestWithAuthentication.call(executeFunctions, 'googleSheetsOAuth2Api', options);
                return { success: true, data: response };
            }
            catch (error) {
                const status = error.statusCode || ((_a = error.response) === null || _a === void 0 ? void 0 : _a.status);
                if ((status === 429 || status >= 500) && retryCount < CONFIG.maxRetries) {
                    const delay = CONFIG.retryDelayMs * Math.pow(2, retryCount);
                    await utils.sleep(delay);
                    return sheetsRequest(endpoint, method, body, retryCount + 1);
                }
                return { success: false, error: error.message, status };
            }
        }
        // =========================== FETCH STATE =====================================
        async function fetchSheetState() {
            const endpoint = `/values/${encodeURIComponent(CONFIG.sheetName)}?valueRenderOption=UNFORMATTED_VALUE`;
            const response = await sheetsRequest(endpoint);
            if (!response.success) {
                throw new n8n_workflow_1.NodeOperationError(executeFunctions.getNode(), `Failed to fetch sheet data: ${response.error}`);
            }
            const rows = response.data.values || [];
            if (rows.length === 0) {
                return { headers: [], headerMap: new Map(), rows: [], totalRows: 0 };
            }
            const headers = rows[0];
            const headerMap = new Map(headers.map((h, i) => [h, i]));
            // Convert rows to objects
            const rowObjects = [];
            for (let rowNum = 1; rowNum < rows.length; rowNum++) {
                const row = rows[rowNum];
                const rowObj = { _rowNumber: rowNum + 1 };
                headers.forEach((header, colIdx) => {
                    rowObj[header] = row[colIdx];
                });
                rowObjects.push(rowObj);
            }
            return {
                headers,
                headerMap,
                rows: rowObjects,
                totalRows: rows.length - 1,
            };
        }
        // =========================== EXECUTION LOGIC =================================
        if (operation === 'read') {
            const state = await fetchSheetState();
            const readReturn = this.getNodeParameter('readReturn', 0);
            let resultRows = state.rows;
            if (readReturn === 'filter') {
                const filters = this.getNodeParameter('readFilters', 0);
                const filterList = filters.filter || [];
                if (filterList.length > 0) {
                    resultRows = resultRows.filter((row) => {
                        // AND logic for all filters
                        return filterList.every((f) => {
                            const val = String(row[f.column] || '').toLowerCase();
                            const filterVal = String(f.value).toLowerCase();
                            if (f.operator === 'equal')
                                return val === filterVal;
                            if (f.operator === 'contains')
                                return val.includes(filterVal);
                            return false;
                        });
                    });
                }
            }
            return [this.helpers.returnJsonArray(resultRows)];
        }
        if (operation === 'upsert') {
            const matchingStrategy = this.getNodeParameter('matchingStrategy', 0);
            const options = this.getNodeParameter('options', 0);
            const skipUnchanged = options.skipUnchanged !== false;
            const generateTimestamp = options.generateTimestamp !== false;
            // Prepare Match Rules
            let matchRules = [];
            if (matchingStrategy === 'auto') {
                const idCol = this.getNodeParameter('idColumn', 0);
                matchRules = [[idCol]];
            }
            else {
                const groups = this.getNodeParameter('matchGroups', 0);
                if (groups.group) {
                    matchRules = groups.group.map((g) => Array.isArray(g.columns) ? g.columns : g.columns.split(',').map((s) => s.trim()));
                }
            }
            // Fetch State
            const state = await fetchSheetState();
            const { headers, headerMap, rows } = state;
            // Build Indexes
            // We build a Map for each match rule
            const indexes = matchRules.map(columns => {
                const map = new Map();
                rows.forEach((row) => {
                    const key = utils.compositeKey(row, columns);
                    if (key)
                        map.set(key, row);
                });
                return { columns, map };
            });
            const updates = [];
            const creates = [];
            // Process Items
            for (let i = 0; i < items.length; i++) {
                const item = items[i].json;
                let existingRow = null;
                // Try matching
                for (const idx of indexes) {
                    const key = utils.compositeKey(item, idx.columns);
                    if (key && idx.map.has(key)) {
                        existingRow = idx.map.get(key);
                        break;
                    }
                }
                if (existingRow) {
                    // Update
                    const rowNumber = existingRow._rowNumber;
                    const changes = [];
                    for (const [field, newValue] of Object.entries(item)) {
                        if (!headerMap.has(field))
                            continue; // Skip unknown columns
                        const colIndex = headerMap.get(field);
                        const oldValue = utils.sanitize(existingRow[field]);
                        const sanitizedNew = utils.sanitize(newValue);
                        if (skipUnchanged && String(oldValue) === String(sanitizedNew))
                            continue;
                        const cellRef = `${utils.columnToLetter(colIndex)}${rowNumber}`;
                        changes.push({
                            cell: cellRef,
                            newValue: sanitizedNew
                        });
                    }
                    if (generateTimestamp && headerMap.has('TIMESTAMP')) {
                        // Always update timestamp if row changed
                        if (changes.length > 0) {
                            const colIndex = headerMap.get('TIMESTAMP');
                            const cellRef = `${utils.columnToLetter(colIndex)}${rowNumber}`;
                            changes.push({ cell: cellRef, newValue: new Date().toISOString() });
                        }
                    }
                    if (changes.length > 0) {
                        updates.push({ changes });
                    }
                }
                else {
                    // Create
                    const rowValues = headers.map((header) => {
                        if (header === 'TIMESTAMP' && generateTimestamp)
                            return new Date().toISOString();
                        // If ID column is missing in input, generate one? 
                        // Only if strategy is 'auto' and column is idColumn
                        if (matchingStrategy === 'auto') {
                            const idCol = this.getNodeParameter('idColumn', 0);
                            if (header === idCol && !item[header])
                                return utils.generateId();
                        }
                        return utils.sanitize(item[header]);
                    });
                    creates.push({ values: rowValues });
                }
            }
            // Apply Changes
            const results = { updates: 0, creates: 0 };
            if (updates.length > 0) {
                const batchData = [];
                for (const u of updates) {
                    for (const c of u.changes) {
                        batchData.push({
                            range: `${CONFIG.sheetName}!${c.cell}`,
                            values: [[c.newValue]]
                        });
                    }
                }
                // Chunking would go here for > 500 updates
                await sheetsRequest('/values:batchUpdate', 'POST', {
                    valueInputOption: 'RAW',
                    data: batchData
                });
                results.updates = updates.length;
            }
            if (creates.length > 0) {
                await sheetsRequest(`/values/${encodeURIComponent(CONFIG.sheetName)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`, 'POST', { values: creates.map(c => c.values) });
                results.creates = creates.length;
            }
            return [this.helpers.returnJsonArray([{ success: true, ...results }])];
        }
        if (operation === 'delete') {
            const matchingStrategy = this.getNodeParameter('matchingStrategy', 0);
            let matchRules = [];
            if (matchingStrategy === 'auto') {
                const idCol = this.getNodeParameter('idColumn', 0);
                matchRules = [[idCol]];
            }
            else {
                const groups = this.getNodeParameter('matchGroups', 0);
                if (groups.group) {
                    matchRules = groups.group.map((g) => Array.isArray(g.columns) ? g.columns : g.columns.split(',').map((s) => s.trim()));
                }
            }
            const state = await fetchSheetState();
            const { rows } = state;
            const indexes = matchRules.map(columns => {
                const map = new Map();
                rows.forEach((row) => {
                    const key = utils.compositeKey(row, columns);
                    if (key)
                        map.set(key, row);
                });
                return { columns, map };
            });
            const rowsToDelete = new Set();
            for (let i = 0; i < items.length; i++) {
                const item = items[i].json;
                for (const idx of indexes) {
                    const key = utils.compositeKey(item, idx.columns);
                    if (key && idx.map.has(key)) {
                        const row = idx.map.get(key);
                        rowsToDelete.add(row._rowNumber);
                        break;
                    }
                }
            }
            if (rowsToDelete.size > 0) {
                // Fetch Sheet GID
                const metaResponse = await sheetsRequest('');
                if (!metaResponse.success) {
                    throw new n8n_workflow_1.NodeOperationError(executeFunctions.getNode(), `Failed to fetch spreadsheet metadata: ${metaResponse.error}`);
                }
                const sheetMeta = metaResponse.data.sheets.find((s) => s.properties.title === CONFIG.sheetName);
                if (!sheetMeta) {
                    throw new n8n_workflow_1.NodeOperationError(executeFunctions.getNode(), `Sheet "${CONFIG.sheetName}" not found`);
                }
                const sheetId = sheetMeta.properties.sheetId;
                // Sort descending
                const sortedRows = Array.from(rowsToDelete).sort((a, b) => b - a);
                const requests = sortedRows.map(rowNum => ({
                    deleteDimension: {
                        range: {
                            sheetId,
                            dimension: 'ROWS',
                            startIndex: rowNum - 1,
                            endIndex: rowNum
                        }
                    }
                }));
                await sheetsRequest(':batchUpdate', 'POST', { requests });
                return [this.helpers.returnJsonArray([{ success: true, deletedRows: sortedRows.length }])];
            }
            return [this.helpers.returnJsonArray([{ success: true, deletedRows: 0 }])];
        }
        return [this.helpers.returnJsonArray([])];
    }
}
exports.TableSheet = TableSheet;
