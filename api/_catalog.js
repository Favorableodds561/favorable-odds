'use strict';

// Server-side price list for Instant Services and Care Plans.
// The browser only ever sends a service key: amounts are never read from the request.
// tests/api/catalog.test.js fails if this drifts from IS_SERVICES in services.html.
const CATALOG = {
  'care-essentials':      { title: 'Care Plan: Essentials',      cents: 4900,  recurring: true,  blurb: 'Monthly website care: hosting, monitoring, backups, 30 min of edits' },
  'care-growth':          { title: 'Care Plan: Growth',          cents: 9900,  recurring: true,  blurb: 'Monthly website care: Essentials plus more edits and a monthly report' },
  'care-pro':             { title: 'Care Plan: Pro',             cents: 17900, recurring: true,  blurb: 'Monthly website care: Growth plus 4 hours of edits and one automation' },
  'ai-snapshot':          { title: 'AI-Readiness Snapshot',      cents: 2700,  recurring: false, blurb: 'Fixed-scope Instant Service, 24 hr delivery' },
  'data-rescue':          { title: 'Data Rescue',                cents: 3700,  recurring: false, blurb: 'Fixed-scope Instant Service, 24 hr delivery' },
  'one-pager':            { title: 'Instant 1-Pager Website',    cents: 19700, recurring: false, blurb: 'Fixed-scope Instant Service, 48 hr delivery' },
  'ai-assistant':         { title: 'Custom AI Assistant Setup',  cents: 5700,  recurring: false, blurb: 'Fixed-scope Instant Service, 48 hr delivery' },
  'automation-blueprint': { title: 'Automation Blueprint',       cents: 3700,  recurring: false, blurb: 'Fixed-scope Instant Service, 24 hr delivery' },
  'copy-punchup':         { title: 'Page Copy Punch-Up',         cents: 4700,  recurring: false, blurb: 'Fixed-scope Instant Service, 24 hr delivery' }
};

module.exports = { CATALOG };
