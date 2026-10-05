"use strict";
// Pure display helper: loads only the marked block of web/local-reader/app.js, no browser and no network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "local-reader", "app.js"), "utf8");
const block = source.slice(source.indexOf("/* quantity:start */"), source.indexOf("/* quantity:end */"));
assert.ok(block.includes("function normalizeQuantity"), "marked block not found");
const context = vm.createContext({});
vm.runInContext(block, context);
const normalize = value => JSON.parse(JSON.stringify(context.normalizeQuantity(value)));

const standard = (input, text, unit = "") => {
  const result = normalize(input);
  assert.equal(result.ok, true, JSON.stringify(input) + " should normalize");
  assert.equal(result.text, text, JSON.stringify(input));
  assert.equal(result.unit, unit, JSON.stringify(input));
  assert.equal(result.printed, String(input).trim(), "printed text is kept as given");
};
const notGuessed = input => {
  const result = normalize(input);
  assert.equal(result.ok, false, JSON.stringify(input) + " must not be guessed");
  assert.equal(result.printed, String(input).trim());
};

standard(2, "2.00");
standard("002.00 EA", "2.00", "EA");
standard("3 EA", "3.00", "EA");
standard("3EA", "3.00", "EA");
standard("1,5", "1.50");
standard("12.50", "12.50");
standard("-3", "-3.00");
standard("2.5000", "2.50");
// Ambiguous or not a number: shown exactly as printed, flagged by the caller.
for (const input of ["1,000", "1.000,50", "2 x 4", "2-3", "N/A", "two", "2.555", "1,234,567"]) notGuessed(input);
// Nothing printed is not an error and not a number.
for (const input of ["", "   ", null, undefined]) {
  const result = normalize(input);
  assert.equal(result.ok, false);
  assert.equal(result.empty, true);
}
// Display wrapper: standard text for numbers, printed text plus a check flag otherwise.
assert.deepEqual(JSON.parse(JSON.stringify(context.quantityDisplay("002.00", "EA"))), {text: "2.00 EA", check: false});
assert.deepEqual(JSON.parse(JSON.stringify(context.quantityDisplay("3 EA", null))), {text: "3.00 EA", check: false});
assert.deepEqual(JSON.parse(JSON.stringify(context.quantityDisplay("1,000", "EA"))), {text: "1,000 EA", check: true});
assert.deepEqual(JSON.parse(JSON.stringify(context.quantityDisplay("N/A", null))), {text: "N/A", check: true});
assert.deepEqual(JSON.parse(JSON.stringify(context.quantityDisplay("", null))), {text: "", check: false});
process.stdout.write("quantity standardization passed\n");
