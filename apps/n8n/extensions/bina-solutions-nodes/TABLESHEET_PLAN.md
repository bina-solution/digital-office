# TableSheet Node v2 Plan

## Goal
Create a high-performance, dynamic CRUD (Create, Read, Update, Delete) node for Google Sheets that treats sheets as database tables.

## Core Features
1.  **Operations**: `Upsert` (Create/Update), `Read`, `Delete`.
2.  **Dynamic Configuration**: Fetch headers dynamically for column selection.
3.  **Performance**: Batch operations, efficient state management.

## Node Structure

### Resource: `Sheet`
### Operations:
1.  **Upsert** (Default)
2.  **Read**
3.  **Delete**

---

## Operation Details

### 1. Upsert (Create / Update)
*Logic*: Smartly determine whether to update an existing row or append a new one based on flexible matching criteria.

**Parameters:**
*   **Spreadsheet ID**: (String/RLC)
*   **Sheet Name**: (String/RLC)
*   **Data Mode**:
    *   `Auto-Map Input to Columns`: Automatically map input JSON keys to Sheet Headers.
    *   `Manual Mapping`: Explicitly define Field -> Column mapping.
*   **Matching Strategy**:
    *   *Type*: Fixed Collection (List of Match Groups).
    *   *Description*: Define priority rules for finding existing rows.
    *   *Example*:
        1.  Match by `ID` column.
        2.  Match by `Email` AND `Name` columns.
*   **Options**:
    *   `Skip Unchanged Rows`: (Boolean) - Performance optimization.
    *   `Update Columns`: (Multi-select) - Only update specific columns (default: all mapped).
    *   `Insert Missing Columns`: (Boolean) - If input has keys not in sheet, add headers? (Advanced).

### 2. Read (Get)
*Logic*: Retrieve rows based on filters.

**Parameters:**
*   **Spreadsheet ID**: (String/RLC)
*   **Sheet Name**: (String/RLC)
*   **Return**:
    *   `All Rows`
    *   `First Match`
    *   `All Matches`
*   **Filters**:
    *   *Type*: Fixed Collection.
    *   *Logic*: AND / OR groups.
    *   *Operators*: Equals, Contains, >, <, Is Empty.
*   **Output Options**:
    *   `Columns to Include`: (Multi-select) - Fetch specific columns only.
    *   `Value Render Option`: Formatted vs Unformatted.

### 3. Delete
*Logic*: Remove rows that match criteria.

**Parameters:**
*   **Spreadsheet ID**: (String/RLC)
*   **Sheet Name**: (String/RLC)
*   **Matching Strategy**: (Same as Upsert) - Identify rows to delete.
*   **Mode**:
    *   `Clear Content`: Keep row, empty cells.
    *   `Delete Row`: Remove row entirely (shifts data up).

---

## Technical Implementation Strategy

### Dynamic Parameters (`loadOptions`)
*   Use `loadOptions` to fetch sheet headers.
*   Allows users to select "ID Column" or "Match Columns" from a dropdown instead of typing "A", "B" or "HeaderName".

### Performance & Batching
*   **Read**: Fetch entire sheet data (values only) once per execution if doing complex matching across the whole dataset.
    *   *Optimization*: If filtering by a specific column that is sorted, use binary search (unlikely in sheets).
    *   *Optimization*: For simple "Read by Row Number", fetch specific range.
*   **Write**:
    *   Accumulate all `batchUpdate` and `append` requests.
    *   Execute in chunks of 500-1000 changes to respect API limits.
    *   Use `valueInputOption: USER_ENTERED` for type inference or `RAW` for speed.

### State Management (The "Smart" Part)
Instead of fetching the sheet for *every* item:
1.  **Pre-fetch**: Fetch all relevant columns (or whole sheet) at start of `execute()`.
2.  **Index**: Build in-memory Maps (Hash Maps) based on the user's "Matching Strategy".
    *   e.g., `Map<CompositeKey, RowIndex>`.
3.  **Process**: Iterate inputs against the Index.
4.  **Bulk Execute**: Send final batches to Google.

## UI/UX Example

**Upsert Config:**
*   **Match By**:
    *   [Rule 1]: Column `Email`
    *   [Rule 2]: Column `First Name` + `Last Name`
*   **If Match Found**: Update
*   **If No Match**: Create

## Next Steps
1.  Refactor `TableSheet.node.ts` to use `n8n-workflow`'s `INodeType` structure with `resource` and `operation`.
2.  Implement `loadOptions` for dynamic header retrieval.
3.  Implement the "Matching Strategy" logic.
