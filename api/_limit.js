'use strict';

// Small in-memory guards for the public read-only endpoints, so repeated or scripted requests cannot turn into
// a stream of Stripe API calls (which share the account's rate limit with real checkouts). State lives per warm
// function instance; that is enough to cap the Stripe calls each instance can make.

function createCache(ttlMs, maxEntries) {
  const map = new Map();
  return {
    get(key, now) {
      const hit = map.get(key);
      if (!hit) return undefined;
      if (now - hit.at > ttlMs) { map.delete(key); return undefined; }
      return hit.value;
    },
    set(key, value, now) {
      if (map.size >= maxEntries) map.delete(map.keys().next().value);   // drop the oldest
      map.set(key, { at: now, value });
    },
    clear() { map.clear(); }
  };
}

// Fixed-window counter: at most `max` calls per `windowMs`.
function createLimiter(max, windowMs) {
  let windowStart = 0;
  let count = 0;
  return {
    allow(now) {
      if (now - windowStart >= windowMs) { windowStart = now; count = 0; }
      if (count >= max) return false;
      count++;
      return true;
    },
    reset() { windowStart = 0; count = 0; }
  };
}

module.exports = { createCache, createLimiter };
