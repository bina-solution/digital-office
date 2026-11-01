we need a custom node for interacting with a gsheet tabel, it shalud be high performance and fully integrate and transparent config to user and enable one step updates 
heres is the js code node code that would be used to echive it with it and it sodesnt work cause we cant use gsheet n8n creds from code node 

transform this into a TabelSheet node 
// ============================================================================
// GOOGLE SHEETS UPSERT - COMPLETE UNIFIED PROCESSOR
// ============================================================================
// Handles: Single items, Batch items, Updates, Creates (Upserts)
// Entry: Webhook, Sub-workflow, or Manual trigger
// ============================================================================

// =========================== CONFIGURATION ===================================
const CONFIG = {
  // Google Sheets
  spreadsheetId: '1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo',
  sheetName: 'מסמכים נכנסים',
  sheetGid: 542119184,
  
  // Column settings
  idColumn: 'ID',
  matchingPrimary: ['COMPANY_ID', 'COMPANY_DOC_ID'],
  matchingSecondary: 'HASH',
  
  // Limits
  maxBatchSize: 500,
  maxRetries: 3,
  retryDelayMs: 1000,
  
  // Behavior
  strictMode: false,        // If true, stop on first error
  skipUnchanged: true,      // Skip cells with same value
  generateTimestamp: true,  // Auto-update TIMESTAMP field
  
  // Schema - all allowed columns
  schema: [
    'ID', 'NAME', 'COMPANY_ID', 'SHORT_DOC_ID', 'TYPE', 'STATUS',
    'COMPANY_DOC_ID', 'LINK', 'PURCHASE_ID', 'SHIPMENT_DOC_ID',
    'LINKED_BS', 'BS_LINE_DATE', 'BS_LINE_AMOUNT', 'SOURCE_TYPE',
    'SOURCE_ID', 'SOURCE_LINK', 'SIZE', 'HASH', 'TIMESTAMP',
    'COMPANY_NAME', 'REQUIRED_ACTION', 'BS_EXTRACTED_LINES',
    'TOTAL_AMOUNT', 'BS_EXTRACTION_VERIFIED', 'BS_LINE_NOTE',
    'FROM_OFFICE', 'FROM_OFFICE_CHECK', 'BS_LINK_DOCUMENTS_COMPLETED',
    'SEARCH_IN_DRIVE_COMPLETED', 'PURCHASE_ID_COMPLETED',
    'SHIPMENT_ID_COMPLETED', 'COMPANY_NAME_COMPLETED',
    'API_TOOLS_ID_COMPLETED', 'API_TOOLS_ID', 'EMPTY',
    'BS_EXTRACTED_LINES_COMPLETED', 'BS_EXTRACTION_USE_CACHE',
    'EX_INVOICE_ID', 'INVOICE_ID_COMPLETED', 'EX_IS_BS_COMPLETED',
    'EX_IS_BS', 'FIGURE_TYPE_COMPLETED', 'DOUBLE_LINE_CONTEXT',
    'FIGURE_COMPANY_COMPLETED'
  ]
};

// =========================== UTILITIES =======================================

const utils = {
  // Generate unique ID
  generateId() {
    const ts = Date.now().toString(36);
    const rand = Math.random().toString(36).substring(2, 10);
    return `${ts}${rand}`;
  },
  
  // Convert column index to letter (0 = A, 26 = AA)
  columnToLetter(index) {
    let letter = '';
    let temp = index;
    while (temp >= 0) {
      letter = String.fromCharCode((temp % 26) + 65) + letter;
      temp = Math.floor(temp / 26) - 1;
    }
    return letter;
  },
  
  // Sanitize value for Sheets API
  sanitize(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') return JSON.stringify(value);
    return value;
  },
  
  // Clean object - remove nulls/undefined
  cleanObject(obj) {
    return Object.fromEntries(
      Object.entries(obj).filter(([_, v]) => v !== null && v !== undefined)
    );
  },
  
  // Sleep helper for retries
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  },
  
  // Create composite key for matching
  compositeKey(obj, fields) {
    return fields.map(f => String(obj[f] || '').toLowerCase().trim()).join('|');
  },
  
  // Check if value is empty/unknown
  isEmpty(value) {
    return value === undefined || value === null || value === '' || 
           String(value).toLowerCase() === 'unknown';
  }
};

// =========================== HTTP CLIENT =====================================

async function sheetsRequest(endpoint, method = 'GET', body = null, retryCount = 0) {
  const baseUrl = `https://sheets.googleapis.com/v4/spreadsheets/${CONFIG.spreadsheetId}`;
  const url = `${baseUrl}${endpoint}`;
  
  const options = {
    method,
    headers: { 'Content-Type': 'application/json' },
    returnFullResponse: true
  };
  
  if (body) {
    options.body = JSON.stringify(body);
  }
  
  try {
    // Use n8n's built-in HTTP helper with OAuth
    const response = await this.helpers.httpRequestWithAuthentication.call(
      this,
      'googleSheetsOAuth2Api',
      { url, method, body, headers: { 'Content-Type': 'application/json' } }
    );
    return { success: true, data: response };
  } catch (error) {
    // Retry on 429 or 5xx
    const status = error.statusCode || error.response?.status;
    if ((status === 429 || status >= 500) && retryCount < CONFIG.maxRetries) {
      const delay = CONFIG.retryDelayMs * Math.pow(2, retryCount);
      console.log(`Retry ${retryCount + 1}/${CONFIG.maxRetries} after ${delay}ms...`);
      await utils.sleep(delay);
      return sheetsRequest.call(this, endpoint, method, body, retryCount + 1);
    }
    return { success: false, error: error.message, status };
  }
}

// =========================== PHASE 1: NORMALIZE ==============================

function normalizeInput(inputItems) {
  const requestId = utils.generateId();
  const startTime = Date.now();
  
  // Collect all items from input
  let items = [];
  
  for (const input of inputItems) {
    const data = input.json?.body || input.json;
    if (Array.isArray(data)) {
      items.push(...data);
    } else if (data && typeof data === 'object') {
      items.push(data);
    }
  }
  
  // Clean and validate each item
  const cleaned = items.map((item, idx) => {
    const clean = utils.cleanObject(item);
    
    // Add timestamp if configured
    if (CONFIG.generateTimestamp && !clean.TIMESTAMP) {
      clean.TIMESTAMP = new Date().toISOString();
    }
    
    // Generate temp ID for tracking new records
    clean._tempId = clean[CONFIG.idColumn] || `new_${idx}_${utils.generateId()}`;
    clean._isNew = !clean[CONFIG.idColumn];
    
    return clean;
  });
  
  return {
    items: cleaned,
    itemCount: cleaned.length,
    hasNewRecords: cleaned.some(i => i._isNew),
    requestId,
    timing: { normalizeMs: Date.now() - startTime }
  };
}

// =========================== PHASE 2: FETCH STATE ============================

async function fetchSheetState() {
  const startTime = Date.now();
  
  // Fetch all data from sheet
  const endpoint = `/values/${encodeURIComponent(CONFIG.sheetName)}?valueRenderOption=UNFORMATTED_VALUE`;
  const response = await sheetsRequest.call(this, endpoint);
  
  if (!response.success) {
    throw new Error(`Failed to fetch sheet data: ${response.error}`);
  }
  
  const rows = response.data.values || [];
  if (rows.length === 0) {
    throw new Error('Sheet is empty - no headers found');
  }
  
  // First row is headers
  const headers = rows[0];
  const headerMap = new Map(headers.map((h, i) => [h, i]));
  
  // Validate ID column exists
  if (!headerMap.has(CONFIG.idColumn)) {
    throw new Error(`ID column "${CONFIG.idColumn}" not found in sheet`);
  }
  
  // Build indexes for fast lookup
  const byId = new Map();
  const byCompanyKey = new Map();
  const byHash = new Map();
  
  for (let rowNum = 1; rowNum < rows.length; rowNum++) {
    const row = rows[rowNum];
    const rowObj = { _rowNumber: rowNum + 1 }; // 1-indexed for Sheets
    
    headers.forEach((header, colIdx) => {
      rowObj[header] = row[colIdx];
    });
    
    // Index by ID
    const id = rowObj[CONFIG.idColumn];
    if (id !== undefined && id !== null && id !== '') {
      byId.set(String(id), rowObj);
    }
    
    // Index by company composite key
    const companyKey = utils.compositeKey(rowObj, CONFIG.matchingPrimary);
    if (companyKey && !CONFIG.matchingPrimary.some(f => utils.isEmpty(rowObj[f]))) {
      byCompanyKey.set(companyKey, rowObj);
    }
    
    // Index by hash
    const hash = rowObj[CONFIG.matchingSecondary];
    if (hash && !utils.isEmpty(hash)) {
      byHash.set(String(hash).toLowerCase(), rowObj);
    }
  }
  
  return {
    headers,
    headerMap,
    byId,
    byCompanyKey,
    byHash,
    totalRows: rows.length - 1,
    timing: { fetchMs: Date.now() - startTime }
  };
}

// =========================== PHASE 3: COMPUTE CHANGES ========================

function computeChanges(items, state) {
  const startTime = Date.now();
  const { headers, headerMap, byId, byCompanyKey, byHash } = state;
  
  const updates = [];
  const creates = [];
  const skipped = [];
  const errors = [];
  const warnings = [];
  
  const processedIds = new Set();
  
  for (const item of items) {
    let existingRow = null;
    let matchMethod = null;
    
    // Try to find existing row
    const itemId = item[CONFIG.idColumn];
    
    if (itemId && !utils.isEmpty(itemId)) {
      // Direct ID lookup
      existingRow = byId.get(String(itemId));
      matchMethod = 'id';
      
      if (processedIds.has(String(itemId))) {
        warnings.push(`Duplicate ID "${itemId}" in batch - using latest`);
      }
      processedIds.add(String(itemId));
    } else {
      // Try company key match
      const companyKey = utils.compositeKey(item, CONFIG.matchingPrimary);
      if (!CONFIG.matchingPrimary.some(f => utils.isEmpty(item[f]))) {
        existingRow = byCompanyKey.get(companyKey);
        if (existingRow) matchMethod = 'company';
      }
      
      // Try hash match
      if (!existingRow && item[CONFIG.matchingSecondary]) {
        const hashKey = String(item[CONFIG.matchingSecondary]).toLowerCase();
        existingRow = byHash.get(hashKey);
        if (existingRow) matchMethod = 'hash';
      }
    }
    
    if (existingRow) {
      // === UPDATE existing row ===
      const rowNumber = existingRow._rowNumber;
      const changes = [];
      
      for (const [field, newValue] of Object.entries(item)) {
        // Skip internal fields
        if (field.startsWith('_')) continue;
        if (field === CONFIG.idColumn) continue;
        
        // Check column exists
        const colIndex = headerMap.get(field);
        if (colIndex === undefined) {
          if (CONFIG.strictMode) {
            errors.push(`Column "${field}" not found for row ${rowNumber}`);
            break;
          }
          warnings.push(`Column "${field}" not found - skipping`);
          continue;
        }
        
        const oldValue = utils.sanitize(existingRow[field]);
        const sanitizedNew = utils.sanitize(newValue);
        
        // Skip if unchanged
        if (CONFIG.skipUnchanged && String(oldValue) === String(sanitizedNew)) {
          continue;
        }
        
        const cellRef = `${utils.columnToLetter(colIndex)}${rowNumber}`;
        changes.push({
          column: field,
          colIndex,
          cell: cellRef,
          oldValue,
          newValue: sanitizedNew
        });
      }
      
      if (changes.length > 0) {
        updates.push({
          rowNumber,
          id: existingRow[CONFIG.idColumn] || item._tempId,
          matchMethod,
          changes
        });
      } else {
        skipped.push({
          id: existingRow[CONFIG.idColumn] || item._tempId,
          reason: 'no_changes'
        });
      }
    } else {
      // === CREATE new row ===
      const newId = utils.generateId();
      const rowValues = headers.map(header => {
        if (header === CONFIG.idColumn) return newId;
        return utils.sanitize(item[header]);
      });
      
      creates.push({
        tempId: item._tempId,
        generatedId: newId,
        values: rowValues
      });
    }
    
    if (CONFIG.strictMode && errors.length > 0) break;
  }
  
  // Calculate stats
  const stats = {
    toUpdate: updates.length,
    toCreate: creates.length,
    toSkip: skipped.length,
    cellChanges: updates.reduce((sum, u) => sum + u.changes.length, 0),
    matchedById: updates.filter(u => u.matchMethod === 'id').length,
    matchedByCompany: updates.filter(u => u.matchMethod === 'company').length,
    matchedByHash: updates.filter(u => u.matchMethod === 'hash').length,
    errors: errors.length,
    warnings: warnings.length
  };
  
  return {
    updates,
    creates,
    skipped,
    errors,
    warnings,
    stats,
    timing: { computeMs: Date.now() - startTime }
  };
}

// =========================== PHASE 4: APPLY CHANGES ==========================

async function applyChanges(changes) {
  const startTime = Date.now();
  const results = { updates: null, creates: null };
  
  // Validate batch size
  const totalOps = changes.updates.length + changes.creates.length;
  if (totalOps > CONFIG.maxBatchSize) {
    throw new Error(`Total operations (${totalOps}) exceeds limit (${CONFIG.maxBatchSize})`);
  }
  
  // === Apply Updates ===
  if (changes.updates.length > 0) {
    const batchData = [];
    
    for (const update of changes.updates) {
      for (const change of update.changes) {
        batchData.push({
          range: `${CONFIG.sheetName}!${change.cell}`,
          values: [[change.newValue]]
        });
      }
    }
    
    const updateResponse = await sheetsRequest.call(
      this,
      '/values:batchUpdate',
      'POST',
      {
        valueInputOption: 'RAW',
        data: batchData
      }
    );
    
    if (!updateResponse.success) {
      throw new Error(`Batch update failed: ${updateResponse.error}`);
    }
    
    results.updates = {
      success: true,
      cellsUpdated: batchData.length,
      response: updateResponse.data
    };
  }
  
  // === Apply Creates (Appends) ===
  if (changes.creates.length > 0) {
    const appendResponse = await sheetsRequest.call(
      this,
      `/values/${encodeURIComponent(CONFIG.sheetName)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`,
      'POST',
      {
        values: changes.creates.map(c => c.values)
      }
    );
    
    if (!appendResponse.success) {
      throw new Error(`Append failed: ${appendResponse.error}`);
    }
    
    results.creates = {
      success: true,
      rowsCreated: changes.creates.length,
      response: appendResponse.data
    };
  }
  
  return {
    results,
    timing: { applyMs: Date.now() - startTime }
  };
}

// =========================== MAIN EXECUTION ==================================

async function main() {
  const totalStartTime = Date.now();
  const timing = {};
  
  try {
    // PHASE 1: Normalize input
    console.log('Phase 1: Normalizing input...');
    const normalized = normalizeInput($input.all());
    Object.assign(timing, normalized.timing);
    
    if (normalized.itemCount === 0) {
      return [{
        json: {
          success: true,
          message: 'No items to process',
          requestId: normalized.requestId,
          summary: { updated: 0, created: 0, skipped: 0 }
        }
      }];
    }
    
    console.log(`Processing ${normalized.itemCount} item(s)...`);
    
    // PHASE 2: Fetch current state
    console.log('Phase 2: Fetching sheet state...');
    const state = await fetchSheetState.call(this);
    Object.assign(timing, state.timing);
    console.log(`Indexed ${state.totalRows} existing rows`);
    
    // PHASE 3: Compute changes
    console.log('Phase 3: Computing changes...');
    const changes = computeChanges(normalized.items, state);
    Object.assign(timing, changes.timing);
    
    // Check for errors in strict mode
    if (changes.errors.length > 0 && CONFIG.strictMode) {
      throw new Error(`Validation errors:\n${changes.errors.join('\n')}`);
    }
    
    console.log(`Updates: ${changes.stats.toUpdate}, Creates: ${changes.stats.toCreate}, Skipped: ${changes.stats.toSkip}`);
    
    // PHASE 4: Apply changes
    if (changes.stats.toUpdate > 0 || changes.stats.toCreate > 0) {
      console.log('Phase 4: Applying changes...');
      const applied = await applyChanges.call(this, changes);
      Object.assign(timing, applied.timing);
    }
    
    // Calculate total timing
    timing.totalMs = Date.now() - totalStartTime;
    
    // Build response
    const response = {
      success: true,
      requestId: normalized.requestId,
      summary: {
        processed: normalized.itemCount,
        updated: changes.stats.toUpdate,
        created: changes.stats.toCreate,
        skipped: changes.stats.toSkip,
        cellsModified: changes.stats.cellChanges
      },
      matching: {
        byId: changes.stats.matchedById,
        byCompanyKey: changes.stats.matchedByCompany,
        byHash: changes.stats.matchedByHash
      },
      details: {
        updates: changes.updates.map(u => ({
          id: u.id,
          row: u.rowNumber,
          matchedBy: u.matchMethod,
          fieldsChanged: u.changes.map(c => c.column)
        })),
        creates: changes.creates.map(c => ({
          tempId: c.tempId,
          assignedId: c.generatedId
        })),
        skipped: changes.skipped
      },
      timing,
      warnings: changes.warnings.length > 0 ? changes.warnings : undefined,
      errors: changes.errors.length > 0 ? changes.errors : undefined
    };
    
    console.log('\n=== COMPLETE ===');
    console.log(`Total time: ${timing.totalMs}ms`);
    console.log(`Updated: ${changes.stats.toUpdate}, Created: ${changes.stats.toCreate}`);
    
    return [{ json: response }];
    
  } catch (error) {
    console.error('FATAL ERROR:', error.message);
    
    return [{
      json: {
        success: false,
        error: error.message,
        errorType: error.name,
        timing: { ...timing, totalMs: Date.now() - totalStartTime }
      }
    }];
  }
}

// Execute
return main.call(this);