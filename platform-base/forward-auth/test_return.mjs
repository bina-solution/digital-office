// test_return.mjs — ui/return.js puts a deep link's `#…` back on the sign-in form's return-to (DGO-569), and only
// there: never a second time, never onto an empty field, never when the address has no screen in it.
// Run: node platform-base/forward-auth/test_return.mjs   (no browser: the page's two objects are stood in for;
// G72 runs it with every gate pass — platform-base/*/test_*)
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const src = readFileSync(fileURLToPath(new URL("./ui/return.js", import.meta.url)), "utf8");
let failed = 0;

function run(hash, values) {
  const fields = values.map((value) => ({ value }));
  const document = { querySelectorAll: (q) => (q === 'form input[name="rd"]' ? fields : []) };
  vm.runInNewContext(src, { location: { hash }, document });
  return fields.map((f) => f.value);
}

function check(what, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
}

const home = "https://console.staging.digital-office.co.il/";
check("the screen goes back on the return-to", run("#/m/browser42.hp-laptop/view/", [home]),
      [home + "#/m/browser42.hp-laptop/view/"]);
check("a return-to that already has one keeps its own (a retry after a wrong password)",
      run("#/m/x", [home + "#/m/y"]), [home + "#/m/y"]);
check("no screen in the address: nothing changes", run("", [home]), [home]);
check("a bare `#` is no screen", run("#", [home]), [home]);
check("an empty return-to stays empty (the server's own default applies)", run("#/m/x", [""]), [""]);
check("every return-to field on the page", run("#/m/x", [home, home]), [home + "#/m/x", home + "#/m/x"]);

console.log(failed ? `test_return: ${failed} failed` : "test_return: all passed");
process.exit(failed ? 1 : 0);
