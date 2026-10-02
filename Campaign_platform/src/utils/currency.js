// Currency configuration for multi-currency support
export const CURRENCIES = [
  { code: 'INR', symbol: '₹', name: 'Indian Rupee', locale: 'en-IN' },
  { code: 'USD', symbol: '$', name: 'US Dollar', locale: 'en-US' },
  { code: 'EUR', symbol: '€', name: 'Euro', locale: 'de-DE' },
  { code: 'GBP', symbol: '£', name: 'British Pound', locale: 'en-GB' },
  { code: 'AED', symbol: 'د.إ', name: 'UAE Dirham', locale: 'ar-AE' },
  { code: 'SGD', symbol: 'S$', name: 'Singapore Dollar', locale: 'en-SG' },
  { code: 'AUD', symbol: 'A$', name: 'Australian Dollar', locale: 'en-AU' },
  { code: 'CAD', symbol: 'C$', name: 'Canadian Dollar', locale: 'en-CA' },
  { code: 'JPY', symbol: '¥', name: 'Japanese Yen', locale: 'ja-JP' },
  { code: 'CNY', symbol: '¥', name: 'Chinese Yuan', locale: 'zh-CN' },
];

export const DEFAULT_CURRENCY = 'INR';

export const getCurrencySymbol = (code) => {
  const currency = CURRENCIES.find(c => c.code === code);
  return currency ? currency.symbol : code;
};

export const getCurrencyLocale = (code) => {
  const currency = CURRENCIES.find(c => c.code === code);
  return currency ? currency.locale : 'en-US';
};

/**
 * The one way the admin app shows money (2026-10-02; 18 pages each had their
 * own helper -- some US grouping, some Indian, 0 or 2 decimals, symbols glued
 * on by hand). Each currency's own grouping (₹1,18,000 / $1,000), decimals
 * only when the amount has them ($3.25, ₹1,18,000), "—" for no value.
 */
export const formatMoney = (value, currencyCode = DEFAULT_CURRENCY, { decimals } = {}) => {
  if (value === null || value === undefined || value === '') return '—';
  const amount = Number(value);
  if (Number.isNaN(amount)) return '—';
  const code = (currencyCode || DEFAULT_CURRENCY).toUpperCase();
  const digits = decimals ?? (code === 'JPY' || Number.isInteger(amount) ? 0 : 2);
  try {
    return new Intl.NumberFormat(getCurrencyLocale(code), {
      style: 'currency', currency: code, minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(amount);
  } catch {
    return `${code} ${amount.toLocaleString(undefined, { maximumFractionDigits: digits })}`;
  }
};

export const formatCurrency = (amount, currencyCode = DEFAULT_CURRENCY) => formatMoney(amount || 0, currencyCode);

export const formatCurrencyCompact = (amount, currencyCode = DEFAULT_CURRENCY) => {
  const symbol = getCurrencySymbol(currencyCode);
  if (amount >= 10000000) {
    return `${symbol}${(amount / 10000000).toFixed(2)}Cr`;
  } else if (amount >= 100000) {
    return `${symbol}${(amount / 100000).toFixed(2)}L`;
  } else if (amount >= 1000) {
    return `${symbol}${(amount / 1000).toFixed(1)}K`;
  }
  return formatCurrency(amount, currencyCode);
};
