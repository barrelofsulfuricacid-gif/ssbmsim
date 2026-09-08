#!/usr/bin/env node
// Inventory replay admission metadata without materializing complete frame data.

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const args = process.argv.slice(2);
const settingsOnlyIndex = args.indexOf("--settings-only");
const settingsOnly = settingsOnlyIndex !== -1;
if (settingsOnly) {
  args.splice(settingsOnlyIndex, 1);
}

if (args.length !== 2 && args.length !== 3) {
  console.error(
    "usage: node ssbm_slippi_inventory.mjs [--settings-only] REPLAY_DIRECTORY SLIPPI_JS_PREFIX [OUTPUT.json]",
  );
  process.exit(2);
}

const replayDirectory = path.resolve(args[0]);
const packagePrefix = path.resolve(args[1]);
const outputPath = args[2] == null ? null : path.resolve(args[2]);
const require = createRequire(import.meta.url);
const { SlippiGame } = require(
  path.join(packagePrefix, "node_modules", "@slippi", "slippi-js", "node"),
);

const MESSAGE_SIZES = 0x35;
const PRE_FRAME_UPDATE = 0x37;
const RAW_C_Y_OFFSET = 0x42;

function preFramePayloadBytes(filePath) {
  const handle = fs.openSync(filePath, "r");
  try {
    const header = Buffer.alloc(4096);
    const length = fs.readSync(handle, header, 0, header.length, 0);
    let rawStart = 0;
    if (length > 0 && header[0] === 0x7b) {
      rawStart = 15;
    }
    if (length < rawStart + 2 || header[rawStart] !== MESSAGE_SIZES) {
      throw new Error("Slippi MESSAGE_SIZES event is missing");
    }
    const receivePayloadSize = header[rawStart + 1];
    const sizesEnd = rawStart + 1 + receivePayloadSize;
    if (
      receivePayloadSize < 1 ||
      (receivePayloadSize - 1) % 3 !== 0 ||
      sizesEnd > length
    ) {
      throw new Error("invalid Slippi MESSAGE_SIZES payload");
    }
    for (let offset = rawStart + 2; offset <= sizesEnd - 2; offset += 3) {
      if (header[offset] === PRE_FRAME_UPDATE) {
        return (header[offset + 1] << 8) | header[offset + 2];
      }
    }
    throw new Error("Slippi PRE_FRAME_UPDATE size is missing");
  } finally {
    fs.closeSync(handle);
  }
}

const files = fs
  .readdirSync(replayDirectory, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".slp"))
  .map((entry) => entry.name)
  .sort();

const rows = [];
const errors = [];
for (const file of files) {
  const replayPath = path.join(replayDirectory, file);
  try {
    const payloadBytes = preFramePayloadBytes(replayPath);
    const game = new SlippiGame(replayPath);
    const settings = game.getSettings();
    const gameEnd = settingsOnly ? null : game.getGameEnd();
    rows.push({
      file,
      size: fs.statSync(replayPath).size,
      slpVersion: settings?.slpVersion ?? null,
      stageId: settings?.stageId ?? null,
      isFrozenPS: settings?.isFrozenPS ?? null,
      itemSpawnBehavior: settings?.itemSpawnBehavior ?? null,
      players: (settings?.players ?? []).map((player) => ({
        playerIndex: player.playerIndex,
        characterId: player.characterId,
        type: player.type,
        startStocks: player.startStocks,
        controllerFix: player.controllerFix,
      })),
      preFramePayloadBytes: payloadBytes,
      exactRawAxes: payloadBytes >= RAW_C_Y_OFFSET,
      hasGameEnd: settingsOnly ? null : gameEnd != null,
    });
  } catch (error) {
    errors.push({
      file,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

const output = `${JSON.stringify({ schema: 2, rows, errors })}\n`;
if (outputPath == null) {
  process.stdout.write(output);
} else {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, output);
  const status = errors.length === 0 ? "pass" : "partial";
  console.log(
    `ssbm-slippi-inventory=${status} files=${files.length} replays=${rows.length} errors=${errors.length}`,
  );
}
