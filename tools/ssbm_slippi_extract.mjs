#!/usr/bin/env node
// Emit the finalized pre/post-frame subset used by the offline differential
// worker. Parsing remains outside production and has no runtime dependency.

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { replayMods } from "./ssbm_replay_mods.mjs";

if (process.argv.length !== 4 && !(process.argv.length === 5 && process.argv[4] === "--endpoint-inputs")) {
  console.error(
    "usage: node ssbm_slippi_extract.mjs REPLAY.slp SLIPPI_JS_PREFIX [--endpoint-inputs]",
  );
  process.exit(2);
}

const replayPath = path.resolve(process.argv[2]);
const packagePrefix = path.resolve(process.argv[3]);
const endpointInputs = process.argv[4] === "--endpoint-inputs";
const require = createRequire(import.meta.url);
const { SlippiGame } = require(
  path.join(packagePrefix, "node_modules", "@slippi", "slippi-js", "node"),
);

const game = new SlippiGame(replayPath);
const settings = game.getSettings();
settings.nativeReplayMods = replayMods(game.getGeckoList());
const metadata = game.getMetadata();
const gameEnd = game.getGameEnd();
// getFrames() is keyed by frame number. Rollback replacements overwrite the
// same key, so this exports finalized observations rather than speculative
// duplicate rollback rows.
const sourceFrames = game.getFrames();
const frameNumbers = Object.keys(sourceFrames)
  .map(Number)
  .sort((left, right) => left - right);

const MESSAGE_SIZES = 0x35;
const PRE_FRAME_UPDATE = 0x37;
const RAW_MAIN_X_OFFSET = 0x3b;
const RAW_MAIN_Y_OFFSET = 0x40;
const RAW_C_X_OFFSET = 0x41;
const RAW_C_Y_OFFSET = 0x42;

function signedByte(value) {
  return value < 0x80 ? value : value - 0x100;
}

// slippi-js 9.1.2 exposes the historical raw-X field, but its public
// PreFrameUpdate type does not yet expose the raw Y/C-stick bytes appended by
// the maintained recorder. Walk the hash-verified file's framed event stream
// using its own MESSAGE_SIZES declaration and retain only those physical
// bytes. This is deliberately fail-closed: offsets are never inferred from a
// short payload, and a malformed/unknown command aborts extraction.
function exactRawAxesByFrame(filePath) {
  const bytes = fs.readFileSync(filePath);
  let rawStart = 0;
  let rawLength = bytes.length;
  if (bytes[0] === 0x7b) {
    if (bytes.length < 15) {
      throw new Error("truncated UBJSON Slippi header");
    }
    rawStart = 15;
    rawLength = bytes.readUInt32BE(11);
    if (rawLength <= 0 || rawStart + rawLength > bytes.length) {
      throw new Error("invalid UBJSON Slippi raw-data length");
    }
  }
  if (bytes[rawStart] !== MESSAGE_SIZES || rawStart + 2 > bytes.length) {
    throw new Error("Slippi MESSAGE_SIZES event is missing");
  }

  const receivePayloadSize = bytes[rawStart + 1];
  if (
    receivePayloadSize < 1 ||
    (receivePayloadSize - 1) % 3 !== 0 ||
    rawStart + 1 + receivePayloadSize >= bytes.length
  ) {
    throw new Error("invalid Slippi MESSAGE_SIZES payload");
  }
  const messageSizes = new Map([[MESSAGE_SIZES, receivePayloadSize]]);
  const sizesEnd = rawStart + 1 + receivePayloadSize;
  for (let offset = rawStart + 2; offset <= sizesEnd - 2; offset += 3) {
    messageSizes.set(
      bytes[offset],
      (bytes[offset + 1] << 8) | bytes[offset + 2],
    );
  }
  const preFramePayloadBytes = messageSizes.get(PRE_FRAME_UPDATE);
  if (preFramePayloadBytes === undefined) {
    throw new Error("Slippi PRE_FRAME_UPDATE size is missing");
  }

  const rows = new Map();
  const rawEnd = rawStart + rawLength;
  let position = rawStart;
  while (position < rawEnd) {
    const command = bytes[position];
    const payloadSize = messageSizes.get(command);
    if (payloadSize === undefined) {
      throw new Error(
        `unknown Slippi command 0x${command.toString(16)} at ${position}`,
      );
    }
    const eventBytes = payloadSize + 1;
    if (eventBytes <= 0 || position + eventBytes > rawEnd) {
      throw new Error(`truncated Slippi command at ${position}`);
    }
    if (command === PRE_FRAME_UPDATE) {
      if (eventBytes <= 0x6) {
        throw new Error("truncated Slippi PRE_FRAME_UPDATE identity");
      }
      const frame = bytes.readInt32BE(position + 0x1);
      const playerIndex = bytes[position + 0x5];
      const isFollower = bytes[position + 0x6] !== 0;
      const rawMainX =
        eventBytes > RAW_MAIN_X_OFFSET
          ? signedByte(bytes[position + RAW_MAIN_X_OFFSET])
          : null;
      const rawMainY =
        eventBytes > RAW_MAIN_Y_OFFSET
          ? signedByte(bytes[position + RAW_MAIN_Y_OFFSET])
          : null;
      const rawCX =
        eventBytes > RAW_C_X_OFFSET
          ? signedByte(bytes[position + RAW_C_X_OFFSET])
          : null;
      const rawCY =
        eventBytes > RAW_C_Y_OFFSET
          ? signedByte(bytes[position + RAW_C_Y_OFFSET])
          : null;
      // Later rollback replacements overwrite the same identity, mirroring
      // SlippiGame.getFrames()'s finalized-frame behavior.
      rows.set(`${frame}:${playerIndex}:${Number(isFollower)}`, {
        rawMainX,
        rawMainY,
        rawCX,
        rawCY,
      });
    }
    position += eventBytes;
  }
  if (position !== rawEnd) {
    throw new Error("Slippi raw event stream did not end on a boundary");
  }
  return {
    rows,
    provenance: {
      framing: "slp-message-sizes-v1",
      preFramePayloadBytes,
      rawMainXOffset: RAW_MAIN_X_OFFSET,
      rawMainYOffset: RAW_MAIN_Y_OFFSET,
      rawCXOffset: RAW_C_X_OFFSET,
      rawCYOffset: RAW_C_Y_OFFSET,
      exactRawMainX: preFramePayloadBytes >= RAW_MAIN_X_OFFSET,
      exactRawMainY: preFramePayloadBytes >= RAW_MAIN_Y_OFFSET,
      exactRawCX: preFramePayloadBytes >= RAW_C_X_OFFSET,
      exactRawCY: preFramePayloadBytes >= RAW_C_Y_OFFSET,
    },
  };
}

const exactRaw = exactRawAxesByFrame(replayPath);

function compactPlayer(player, frameNumber) {
  if (!player?.pre || !player?.post) {
    return null;
  }
  const { pre, post } = player;
  const raw = exactRaw.rows.get(
    `${frameNumber}:${pre.playerIndex}:${Number(Boolean(pre.isFollower))}`,
  );
  const parsedRawX = pre.rawJoystickX ?? null;
  if (
    raw?.rawMainX != null &&
    parsedRawX != null &&
    raw.rawMainX !== parsedRawX
  ) {
    throw new Error(
      `raw main X parser mismatch frame=${frameNumber} player=${pre.playerIndex}`,
    );
  }
  const speeds = post.selfInducedSpeeds ?? {};
  const result = {
    pre: {
      seed: pre.seed,
      actionStateId: pre.actionStateId,
      positionX: pre.positionX,
      positionY: pre.positionY,
      facingDirection: pre.facingDirection,
      joystickX: pre.joystickX,
      joystickY: pre.joystickY,
      cStickX: pre.cStickX,
      cStickY: pre.cStickY,
      trigger: pre.trigger,
      buttons: pre.buttons,
      physicalButtons: pre.physicalButtons,
      physicalLTrigger: pre.physicalLTrigger,
      physicalRTrigger: pre.physicalRTrigger,
      rawJoystickX: raw?.rawMainX ?? parsedRawX,
      rawJoystickY: raw?.rawMainY ?? null,
      rawCStickX: raw?.rawCX ?? null,
      rawCStickY: raw?.rawCY ?? null,
      percent: pre.percent,
    },
    post: {
      actionStateId: post.actionStateId,
      positionX: post.positionX,
      positionY: post.positionY,
      facingDirection: post.facingDirection,
      percent: post.percent,
      shieldSize: post.shieldSize,
      lastAttackLanded: post.lastAttackLanded,
      currentComboCount: post.currentComboCount,
      lastHitBy: post.lastHitBy,
      stocksRemaining: post.stocksRemaining,
      actionStateCounter: post.actionStateCounter,
      isAirborne: post.isAirborne,
      lastGroundId: post.lastGroundId,
      jumpsRemaining: post.jumpsRemaining,
      lCancelStatus: post.lCancelStatus,
      selfAirX: speeds.airX ?? null,
      selfGroundX: speeds.groundX ?? null,
      selfY: speeds.y ?? null,
      selfAttackX: speeds.attackX ?? null,
      selfAttackY: speeds.attackY ?? null,
      hitlagRemaining: post.hitlagRemaining ?? null,
      animationIndex: post.animationIndex ?? null,
    },
  };
  if (endpointInputs) {
    // Retain the complete physical input contract for every finalized frame.
    // State observations are needed only at the endpoint in candidate mode.
    const inputKeys = ["physicalButtons", "joystickX", "joystickY", "cStickX",
      "cStickY", "physicalLTrigger", "physicalRTrigger", "rawJoystickX",
      "rawJoystickY", "rawCStickX", "rawCStickY"];
    result.pre = Object.fromEntries(inputKeys.map((key) => [key, result.pre[key]]));
    if (frameNumber !== frameNumbers.at(-1)) delete result.post;
  }
  return result;
}

const frames = frameNumbers.map((frameNumber) => {
  const frame = sourceFrames[frameNumber];
  return {
    frame: frameNumber,
    startSeed: frame.start?.seed ?? null,
    players: frame.players.map((value) => compactPlayer(value, frameNumber)),
    followers: Array.from({ length: 4 }, (_, playerIndex) =>
      compactPlayer(frame.followers?.[playerIndex], frameNumber),
    ),
  };
});

process.stdout.write(
  JSON.stringify({
    schema: 2,
    settings,
    metadata,
    gameEnd,
    inputProvenance: exactRaw.provenance,
    frames,
  }),
);
