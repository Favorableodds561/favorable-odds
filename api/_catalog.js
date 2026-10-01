'use strict';

// Server-side price list for Instant Services, Care Plans and Bookkeeping plans.
// The browser only ever sends a service key: amounts are never read from the request.
// tests/api/catalog.test.js fails if this drifts from IS_SERVICES in services.html / bookkeeping.html.
const CATALOG = {
  'care-essentials':      { title: 'Care Plan: Essentials',      cents: 4900,  recurring: true,  group: 'services',   blurb: 'Monthly website care: hosting, monitoring, backups, 30 min of edits' },
  'care-growth':          { title: 'Care Plan: Growth',          cents: 9900,  recurring: true,  group: 'services',   blurb: 'Monthly website care: Essentials plus more edits and a monthly report' },
  'care-pro':             { title: 'Care Plan: Pro',             cents: 17900, recurring: true,  group: 'services',   blurb: 'Monthly website care: Growth plus 4 hours of edits and one automation' },
  'ai-snapshot':          { title: 'AI-Readiness Snapshot',      cents: 2700,  recurring: false, group: 'services',   blurb: 'Fixed-scope Instant Service, 24 hr delivery' },
  'data-rescue':          { title: 'Data Rescue',                cents: 3700,  recurring: false, group: 'services',   blurb: 'Fixed-scope Instant Service, 24 hr delivery' },
  'one-pager':            { title: 'Instant 1-Pager Website',    cents: 19700, recurring: false, group: 'services',   blurb: 'Fixed-scope Instant Service, 48 hr delivery' },
  'ai-assistant':         { title: 'Custom AI Assistant Setup',  cents: 5700,  recurring: false, group: 'services',   blurb: 'Fixed-scope Instant Service, 48 hr delivery' },
  'automation-blueprint': { title: 'Automation Blueprint',       cents: 3700,  recurring: false, group: 'services',   blurb: 'Fixed-scope Instant Service, 24 hr delivery' },
  'copy-punchup':         { title: 'Page Copy Punch-Up',         cents: 4700,  recurring: false, group: 'services',   blurb: 'Fixed-scope Instant Service, 24 hr delivery' },
  // bookkeeping.html. "Catch-Up Cleanup" (from $150) is quoted after a review, so it is not sold online.
  'books-starter':  { title: 'Bookkeeping: Starter',  cents: 19900, recurring: true,  group: 'bookkeeping', blurb: 'Monthly bookkeeping: up to 50 transactions, reconciliation, monthly reports' },
  'books-standard': { title: 'Bookkeeping: Standard', cents: 34900, recurring: true,  group: 'bookkeeping', blurb: 'Monthly bookkeeping: up to 150 transactions, bill tracking, monthly review call' },
  'books-newllc':   { title: 'New LLC Starter',       cents: 49700, recurring: false, group: 'bookkeeping', blurb: 'One-time setup: bookkeeping system, connected accounts, 1-page website' }
};

module.exports = { CATALOG };
