import assert from "node:assert/strict";
import test from "node:test";

import { createExclusiveGate } from "../web/start_gate.mjs";

test("rapid double-start enters the request path only once", async () => {
  const gate = createExclusiveGate();
  let postCount = 0;
  let runnerOpen = false;
  let closeCount = 0;
  let releaseRequest;
  const pendingRequest = new Promise((resolve) => {
    releaseRequest = resolve;
  });

  async function start() {
    if (!gate.tryEnter()) return false;
    runnerOpen = true;
    try {
      postCount += 1;
      await pendingRequest;
      return true;
    } catch (error) {
      runnerOpen = false;
      closeCount += 1;
      throw error;
    } finally {
      gate.leave();
    }
  }

  const firstStart = start();
  const secondStart = await start();

  assert.equal(secondStart, false);
  assert.equal(postCount, 1);
  assert.equal(runnerOpen, true);
  assert.equal(closeCount, 0);
  assert.equal(gate.active, true);

  releaseRequest();
  assert.equal(await firstStart, true);
  assert.equal(gate.active, false);
});
