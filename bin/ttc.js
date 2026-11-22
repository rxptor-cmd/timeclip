#!/usr/bin/env node

const { spawnSync } = require("child_process");
const path = require("path");

const mainPy = path.resolve(__dirname, "..", "main.py");
const args = [mainPy, ...process.argv.slice(2)];

let res = spawnSync("python", args, { stdio: "inherit" });
if (res.error && res.error.code === "ENOENT") {
  res = spawnSync("python3", args, { stdio: "inherit" });
}

if (res.error) {
  console.error("Failed to launch Python (3.10+ required):", res.error.message);
  process.exit(1);
}

process.exit(res.status ?? 0);
