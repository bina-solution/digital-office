// Minimal per-key async queue to serialize work per user (or any key)
// Usage: runExclusive(key, async () => { /* your logic */ })
// Ensures tasks for the same key run strictly one after another, while
// different keys can run concurrently.

const tails = new Map();

/**
 * Queue a task to run exclusively for a given key.
 * - Preserves caller result/rejection
 * - Keeps the internal chain alive even if a task fails
 * @template T
 * @param {string} key
 * @param {() => Promise<T>} task
 * @returns {Promise<T>}
 */
function runExclusive(key, task) {
  // Current tail (or resolved) for the key
  const tail = tails.get(key) || Promise.resolve();

  // Run the task after the tail; this promise is returned to the caller
  const runPromise = tail.then(task);

  // Internal tail swallows errors to avoid breaking the chain
  const newTail = runPromise.catch(() => { });

  // Store the exact promise used as tail so we can compare it during cleanup
  tails.set(key, newTail);

  // Cleanup: remove key if no newer tasks have replaced this tail
  newTail.finally(() => {
    if (tails.get(key) === newTail) tails.delete(key);
  });

  return runPromise;
}

module.exports = { runExclusive };
