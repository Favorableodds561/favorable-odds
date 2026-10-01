'use strict';

// Server-side shop catalog and pricing. The browser sends product ids, sizes and quantities only.
// tests/api/shop.test.js fails if this drifts from CONFIG / PRODUCTS / SIZES in shop.html.
const TEE_CENTS = 3500;                      // every tee
const PROMO = { qty: 2, cents: 6000 };       // any 2 tees for $60 (3 tees = one pair + one single)
const SHIPPING_CENTS = 500;                  // flat US shipping per order. Change here and in shop.html CONFIG.shippingFlat.
const MAX_LINES = 20;
const MAX_QTY_PER_LINE = 10;
const MAX_TOTAL_QTY = 30;

const SIZES = ['S', 'M', 'L', 'XL', '2XL', '3XL'];

const PRODUCTS = {
  success:        { title: 'Success Collection Tee',      collection: 'Success Collection',      image: 'fo_pills_shirt_main.jpg' },
  koi:            { title: 'Koi Collection Tee',          collection: 'Koi Collection',          image: 'fo_koi_shirt_main.jpg' },
  galaxy:         { title: 'Galaxy Collection Tee',       collection: 'Galaxy Collection',       image: 'fo_galaxy_shirt_main.jpg' },
  prescription:   { title: 'Prescription for Success Tee', collection: 'Prescription Collection', image: 'fo_prescription_main.jpg' },
  'beauty-fades': { title: 'Beauty Fade$ Tee',            collection: 'Fortune Collection',      image: 'fo_beauty_fades_shirt.jpg' },
  fortuna:        { title: 'Fortuna Parātīs Favet Tee',   collection: 'Fortuna Collection',      image: 'fo_fortuna_shirt_back.jpg' }
};

// Validates and merges cart lines. Returns { lines, totalQty } or { error }.
function normalizeItems(items) {
  if (!Array.isArray(items) || items.length === 0 || items.length > MAX_LINES) return { error: 'invalid_items' };
  const merged = new Map();
  for (const it of items) {
    if (!it || typeof it !== 'object') return { error: 'invalid_items' };
    const { id, size, qty } = it;
    if (typeof id !== 'string' || !Object.prototype.hasOwnProperty.call(PRODUCTS, id)) return { error: 'unknown_product' };
    if (typeof size !== 'string' || !SIZES.includes(size)) return { error: 'invalid_size' };
    if (!Number.isInteger(qty) || qty < 1 || qty > MAX_QTY_PER_LINE) return { error: 'invalid_quantity' };
    const key = id + '|' + size;
    merged.set(key, { id, size, qty: (merged.has(key) ? merged.get(key).qty : 0) + qty });
  }
  const lines = [...merged.values()];
  if (lines.some(function (l) { return l.qty > MAX_QTY_PER_LINE; })) return { error: 'invalid_quantity' };
  const totalQty = lines.reduce(function (n, l) { return n + l.qty; }, 0);
  if (totalQty > MAX_TOTAL_QTY) return { error: 'invalid_quantity' };
  return { lines, totalQty };
}

// Price breakdown in cents: the bundle deal discounts each full pair from 2 x $35 to $60.
function price(totalQty) {
  const subtotal = totalQty * TEE_CENTS;
  const bundles = Math.floor(totalQty / PROMO.qty);
  const discount = Math.min(subtotal, bundles * (PROMO.qty * TEE_CENTS - PROMO.cents));
  return { subtotal, bundles, discount, shipping: SHIPPING_CENTS, total: subtotal - discount + SHIPPING_CENTS };
}

module.exports = { TEE_CENTS, PROMO, SHIPPING_CENTS, SIZES, PRODUCTS, normalizeItems, price };
