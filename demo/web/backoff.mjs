// Request hygiene for the page's one network client (the live demo service): when the service keeps failing, stop sending for a while instead of making every
// click wait for one more failure, then let exactly ONE request through to find out whether it is back. The same rules as the Python client's breaker, for one
// service. Pure logic: no network, no timers, the clock and the randomness are passed in so a test can drive them.
export class CircuitBreaker {
  constructor({ threshold = 3, cooldownMs = 15000, maxCooldownMs = 120000, now = () => Date.now(), random = Math.random } = {}) {
    Object.assign(this, { threshold, cooldownMs, maxCooldownMs, now, random });
    this.reset();
  }

  reset() {
    this.fails = 0;
    this.openUntil = 0;
    this.cooldown = this.cooldownMs;
    this.probing = false;
  }

  _open() {
    this.openUntil = this.now() + this.cooldown * (1 + 0.25 * this.random());
  }

  /** 0 means go ahead. Above 0 the circuit is open: wait that many milliseconds and do not call the service. */
  before() {
    if (this.fails < this.threshold) return 0;
    const remaining = this.openUntil - this.now();
    if (remaining > 0) return remaining;
    if (this.probing) return 1000; // a probe is in flight: everybody else waits a moment
    this.probing = true; // half-open: this caller is the one probe
    return 0;
  }

  success() {
    this.reset();
  }

  failure() {
    if (this.probing) { // the probe failed: open again, twice as long
      this.probing = false;
      this.cooldown = Math.min(this.maxCooldownMs, this.cooldown * 2);
      this._open();
      return;
    }
    this.fails += 1;
    if (this.fails >= this.threshold) this._open();
  }

  /** A probe that ended with no verdict (a gateway timeout, an unexpected error) must call this, so the circuit never waits for an answer that is not coming. */
  neutral() {
    this.probing = false;
  }

  get state() {
    if (this.fails < this.threshold) return 'closed';
    return this.openUntil - this.now() > 0 ? 'open' : 'half-open';
  }
}
