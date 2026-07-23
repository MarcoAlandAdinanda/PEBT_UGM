/** Create a synchronous gate for one in-flight experiment start operation. */
export function createExclusiveGate() {
  let active = false;
  return {
    get active() {
      return active;
    },
    tryEnter() {
      if (active) return false;
      active = true;
      return true;
    },
    leave() {
      active = false;
    },
  };
}
