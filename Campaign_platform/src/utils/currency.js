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

export const formatCurrency = (amount, currencyCode = DEFAULT_CURRENCY) => {
  const locale = getCurrencyLocale(currencyCode);
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currencyCode,
    maximumFractionDigits: currencyCode === 'JPY' ? 0 : 2,
    minimumFractionDigits: currencyCode === 'JPY' ? 0 : 2,
  }).format(amount || 0);
};

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
