import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Load the real TS/TSX modules with explicit service/hook doubles, without Next or network. */
export function testModuleLoader(overrides = {}, globals = {}) {
  const modules = new Map();
  function load(relative) {
    const filename = path.resolve(root, relative);
    if (modules.has(filename)) return modules.get(filename).exports;
    const loaded = { exports: {} };
    modules.set(filename, loaded);
    const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const context = {
      module: loaded, exports: loaded.exports,
      require(name) {
        if (Object.hasOwn(overrides, name)) return overrides[name];
        if (name === "next/cache") return { unstable_cache: fn => fn };
        if (name.startsWith("@/") || name.startsWith(".")) {
          const base = name.startsWith("@/") ? path.join(root, name.slice(2)) : path.resolve(path.dirname(filename), name);
          const resolved = [base, base + ".ts", base + ".tsx"].find(p => fs.existsSync(p) && fs.statSync(p).isFile());
          if (resolved) return load(resolved);
        }
        return require(name);
      },
      process: { env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:9999" } },
      fetch: (...args) => globalThis.fetch(...args),
      URLSearchParams, AbortSignal, Error, Response, Date,
      setTimeout, clearTimeout, setInterval, clearInterval,
      ...globals,
    };
    vm.compileFunction(source, Object.keys(context), { filename })(...Object.values(context));
    return loaded.exports;
  }
  return load;
}
