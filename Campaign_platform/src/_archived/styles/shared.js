/**
 * Shared Styles - Consistent styling patterns across all pages
 * 
 * These are the base styles extracted from existing pages to ensure
 * consistency. They can be used as base styles and extended as needed.
 */

// =============================================================================
// COLOR PALETTE
// =============================================================================

export const colors = {
  // Primary
  primary: '#0d6efd',
  primaryHover: '#0b5ed7',
  primaryLight: '#e8f0fe',
  
  // Secondary
  secondary: '#6c757d',
  secondaryHover: '#5c636a',
  
  // Status colors
  success: '#198754',
  successLight: '#d1e7dd',
  warning: '#ffc107',
  warningLight: '#fff3cd',
  danger: '#dc3545',
  dangerLight: '#f8d7da',
  info: '#0dcaf0',
  infoLight: '#cff4fc',
  
  // Neutrals
  white: '#ffffff',
  gray50: '#f9fafb',
  gray100: '#f3f4f6',
  gray200: '#e5e7eb',
  gray300: '#d1d5db',
  gray400: '#9ca3af',
  gray500: '#6b7280',
  gray600: '#4b5563',
  gray700: '#374151',
  gray800: '#1f2937',
  gray900: '#111827',
  
  // Background
  background: '#f9fafb',
  surface: '#ffffff',
  border: '#e5e7eb',
}

// =============================================================================
// TYPOGRAPHY
// =============================================================================

export const typography = {
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  
  // Font sizes
  xs: '0.75rem',    // 12px
  sm: '0.875rem',   // 14px
  base: '1rem',     // 16px
  lg: '1.125rem',   // 18px
  xl: '1.25rem',    // 20px
  '2xl': '1.5rem',  // 24px
  '3xl': '1.875rem', // 30px
  
  // Font weights
  normal: 400,
  medium: 500,
  semibold: 600,
  bold: 700,
}

// =============================================================================
// SPACING
// =============================================================================

export const spacing = {
  xs: '0.25rem',    // 4px
  sm: '0.5rem',     // 8px
  md: '1rem',       // 16px
  lg: '1.5rem',     // 24px
  xl: '2rem',       // 32px
  '2xl': '3rem',    // 48px
}

// =============================================================================
// PAGE LAYOUT STYLES
// =============================================================================

export const pageStyles = {
  // Main container
  container: {
    padding: spacing.lg,
    maxWidth: '100%',
    backgroundColor: colors.background,
    minHeight: '100%',
  },
  
  // Header section
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.lg,
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  
  // Page title
  title: {
    fontSize: typography['2xl'],
    fontWeight: typography.bold,
    color: colors.gray900,
    margin: 0,
  },
  
  // Page subtitle
  subtitle: {
    fontSize: typography.sm,
    color: colors.gray500,
    margin: `${spacing.xs} 0 0 0`,
  },
  
  // Error alert
  errorAlert: {
    backgroundColor: colors.dangerLight,
    color: colors.danger,
    padding: spacing.md,
    borderRadius: '0.5rem',
    marginBottom: spacing.md,
  },
  
  // Success alert
  successAlert: {
    backgroundColor: colors.successLight,
    color: colors.success,
    padding: spacing.md,
    borderRadius: '0.5rem',
    marginBottom: spacing.md,
  },
}

// =============================================================================
// SEARCH & FILTER STYLES
// =============================================================================

export const searchStyles = {
  searchSection: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
    flexWrap: 'wrap',
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: '0.5rem',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  
  searchInput: {
    padding: `${spacing.sm} ${spacing.md}`,
    fontSize: typography.sm,
    border: `1px solid ${colors.border}`,
    borderRadius: '0.375rem',
    minWidth: '250px',
    outline: 'none',
    transition: 'border-color 0.15s ease-in-out',
  },
  
  select: {
    padding: `${spacing.sm} ${spacing.md}`,
    fontSize: typography.sm,
    border: `1px solid ${colors.border}`,
    borderRadius: '0.375rem',
    outline: 'none',
    backgroundColor: colors.white,
    cursor: 'pointer',
    minWidth: '120px',
  },
  
  stats: {
    display: 'flex',
    gap: spacing.md,
    fontSize: typography.sm,
    color: colors.gray500,
    marginLeft: 'auto',
    flexWrap: 'wrap',
  },
}

// =============================================================================
// BUTTON STYLES
// =============================================================================

export const buttonStyles = {
  // Base button
  base: {
    padding: `${spacing.sm} ${spacing.md}`,
    fontSize: typography.sm,
    fontWeight: typography.medium,
    borderRadius: '0.375rem',
    border: 'none',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    transition: 'all 0.15s ease-in-out',
    textDecoration: 'none',
  },
  
  // Primary button
  primary: {
    backgroundColor: colors.primary,
    color: colors.white,
  },
  
  // Secondary button
  secondary: {
    backgroundColor: colors.gray100,
    color: colors.gray700,
    border: `1px solid ${colors.border}`,
  },
  
  // Danger button
  danger: {
    backgroundColor: colors.danger,
    color: colors.white,
  },
  
  // Success button
  success: {
    backgroundColor: colors.success,
    color: colors.white,
  },
  
  // Ghost button
  ghost: {
    backgroundColor: 'transparent',
    color: colors.gray600,
  },
  
  // Link button
  link: {
    backgroundColor: 'transparent',
    color: colors.primary,
    padding: 0,
  },
  
  // Small button
  small: {
    padding: `${spacing.xs} ${spacing.sm}`,
    fontSize: typography.xs,
  },
  
  // Large button
  large: {
    padding: `${spacing.md} ${spacing.lg}`,
    fontSize: typography.base,
  },
  
  // Icon only button
  icon: {
    padding: spacing.sm,
    width: '2rem',
    height: '2rem',
  },
  
  // Disabled state
  disabled: {
    opacity: 0.6,
    cursor: 'not-allowed',
    pointerEvents: 'none',
  },
}

// Helper to combine button styles
export const getButtonStyle = (variant = 'primary', size = 'default', disabled = false) => ({
  ...buttonStyles.base,
  ...(buttonStyles[variant] || buttonStyles.primary),
  ...(size === 'small' && buttonStyles.small),
  ...(size === 'large' && buttonStyles.large),
  ...(size === 'icon' && buttonStyles.icon),
  ...(disabled && buttonStyles.disabled),
})

// =============================================================================
// TABLE STYLES
// =============================================================================

export const tableStyles = {
  container: {
    backgroundColor: colors.surface,
    borderRadius: '0.5rem',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
    overflow: 'hidden',
  },
  
  wrapper: {
    overflowX: 'auto',
  },
  
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: typography.sm,
  },
  
  thead: {
    backgroundColor: colors.gray50,
    borderBottom: `1px solid ${colors.border}`,
  },
  
  th: {
    padding: spacing.md,
    textAlign: 'left',
    fontWeight: typography.semibold,
    color: colors.gray700,
    fontSize: typography.xs,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    whiteSpace: 'nowrap',
  },
  
  tbody: {},
  
  tr: {
    borderBottom: `1px solid ${colors.gray100}`,
    transition: 'background-color 0.15s ease',
  },
  
  trHover: {
    backgroundColor: colors.gray50,
  },
  
  trSelected: {
    backgroundColor: colors.primaryLight,
  },
  
  td: {
    padding: spacing.md,
    color: colors.gray700,
    verticalAlign: 'middle',
  },
  
  emptyState: {
    textAlign: 'center',
    padding: spacing['2xl'],
    color: colors.gray400,
  },
  
  actions: {
    display: 'flex',
    gap: spacing.xs,
    justifyContent: 'flex-end',
  },
}

// =============================================================================
// CARD STYLES
// =============================================================================

export const cardStyles = {
  card: {
    backgroundColor: colors.surface,
    borderRadius: '0.5rem',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
    padding: spacing.lg,
  },
  
  cardHeader: {
    marginBottom: spacing.md,
    paddingBottom: spacing.md,
    borderBottom: `1px solid ${colors.border}`,
  },
  
  cardTitle: {
    fontSize: typography.lg,
    fontWeight: typography.semibold,
    color: colors.gray900,
    margin: 0,
  },
  
  cardContent: {},
  
  cardFooter: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTop: `1px solid ${colors.border}`,
    display: 'flex',
    justifyContent: 'flex-end',
    gap: spacing.sm,
  },
}

// =============================================================================
// STAT CARD STYLES
// =============================================================================

export const statCardStyles = {
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  
  card: {
    backgroundColor: colors.surface,
    borderRadius: '0.5rem',
    padding: spacing.lg,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  
  label: {
    fontSize: typography.sm,
    color: colors.gray500,
    marginBottom: spacing.xs,
  },
  
  value: {
    fontSize: typography['2xl'],
    fontWeight: typography.bold,
    color: colors.gray900,
  },
  
  change: {
    fontSize: typography.xs,
    marginTop: spacing.xs,
  },
  
  changePositive: {
    color: colors.success,
  },
  
  changeNegative: {
    color: colors.danger,
  },
}

// =============================================================================
// FORM STYLES
// =============================================================================

export const formStyles = {
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing.md,
  },
  
  formGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing.xs,
  },
  
  formRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
    gap: spacing.md,
  },
  
  label: {
    fontSize: typography.sm,
    fontWeight: typography.medium,
    color: colors.gray700,
  },
  
  input: {
    padding: `${spacing.sm} ${spacing.md}`,
    fontSize: typography.sm,
    border: `1px solid ${colors.border}`,
    borderRadius: '0.375rem',
    outline: 'none',
    transition: 'border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out',
    width: '100%',
    boxSizing: 'border-box',
  },
  
  inputFocus: {
    borderColor: colors.primary,
    boxShadow: `0 0 0 3px ${colors.primaryLight}`,
  },
  
  inputError: {
    borderColor: colors.danger,
  },
  
  select: {
    padding: `${spacing.sm} ${spacing.md}`,
    fontSize: typography.sm,
    border: `1px solid ${colors.border}`,
    borderRadius: '0.375rem',
    outline: 'none',
    backgroundColor: colors.white,
    width: '100%',
    boxSizing: 'border-box',
  },
  
  textarea: {
    padding: `${spacing.sm} ${spacing.md}`,
    fontSize: typography.sm,
    border: `1px solid ${colors.border}`,
    borderRadius: '0.375rem',
    outline: 'none',
    minHeight: '100px',
    resize: 'vertical',
    fontFamily: 'inherit',
    width: '100%',
    boxSizing: 'border-box',
  },
  
  checkbox: {
    width: '1rem',
    height: '1rem',
    cursor: 'pointer',
  },
  
  errorText: {
    fontSize: typography.xs,
    color: colors.danger,
  },
  
  helpText: {
    fontSize: typography.xs,
    color: colors.gray500,
  },
}

// =============================================================================
// MODAL STYLES
// =============================================================================

export const modalStyles = {
  overlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    padding: spacing.md,
  },
  
  content: {
    backgroundColor: colors.surface,
    borderRadius: '0.5rem',
    boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
    maxWidth: '600px',
    width: '100%',
    maxHeight: '90vh',
    display: 'flex',
    flexDirection: 'column',
  },
  
  contentLarge: {
    maxWidth: '900px',
  },
  
  contentSmall: {
    maxWidth: '400px',
  },
  
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.lg,
    borderBottom: `1px solid ${colors.border}`,
  },
  
  title: {
    fontSize: typography.lg,
    fontWeight: typography.semibold,
    color: colors.gray900,
    margin: 0,
  },
  
  closeBtn: {
    background: 'none',
    border: 'none',
    fontSize: typography.xl,
    color: colors.gray400,
    cursor: 'pointer',
    padding: spacing.xs,
    lineHeight: 1,
  },
  
  body: {
    padding: spacing.lg,
    overflowY: 'auto',
    flex: 1,
  },
  
  footer: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    padding: spacing.lg,
    borderTop: `1px solid ${colors.border}`,
  },
}

// =============================================================================
// PAGINATION STYLES
// =============================================================================

export const paginationStyles = {
  container: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    gap: spacing.md,
    marginTop: spacing.lg,
    padding: spacing.md,
  },
  
  button: {
    padding: `${spacing.sm} ${spacing.md}`,
    fontSize: typography.sm,
    border: `1px solid ${colors.border}`,
    borderRadius: '0.375rem',
    backgroundColor: colors.surface,
    color: colors.gray700,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  
  buttonActive: {
    backgroundColor: colors.primary,
    color: colors.white,
    borderColor: colors.primary,
  },
  
  pageInfo: {
    fontSize: typography.sm,
    color: colors.gray500,
  },
}

// =============================================================================
// STATUS BADGE STYLES
// =============================================================================

export const badgeStyles = {
  base: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: spacing.xs,
    padding: `${spacing.xs} ${spacing.sm}`,
    fontSize: typography.xs,
    fontWeight: typography.medium,
    borderRadius: '9999px',
    textTransform: 'capitalize',
  },
  
  // Status variants
  active: {
    backgroundColor: colors.successLight,
    color: colors.success,
  },
  inactive: {
    backgroundColor: colors.gray200,
    color: colors.gray600,
  },
  pending: {
    backgroundColor: colors.warningLight,
    color: '#b45309',
  },
  success: {
    backgroundColor: colors.successLight,
    color: colors.success,
  },
  error: {
    backgroundColor: colors.dangerLight,
    color: colors.danger,
  },
  warning: {
    backgroundColor: colors.warningLight,
    color: '#b45309',
  },
  info: {
    backgroundColor: colors.infoLight,
    color: '#0891b2',
  },
  default: {
    backgroundColor: colors.gray200,
    color: colors.gray600,
  },
  
  // Invoice/Order status
  draft: {
    backgroundColor: colors.gray200,
    color: colors.gray600,
  },
  sent: {
    backgroundColor: colors.infoLight,
    color: '#0891b2',
  },
  paid: {
    backgroundColor: colors.successLight,
    color: colors.success,
  },
  overdue: {
    backgroundColor: colors.dangerLight,
    color: colors.danger,
  },
}

// Helper to get badge style
export const getBadgeStyle = (status) => ({
  ...badgeStyles.base,
  ...(badgeStyles[status?.toLowerCase()] || badgeStyles.default),
})

// =============================================================================
// LOADING STYLES
// =============================================================================

export const loadingStyles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing['2xl'],
    color: colors.gray400,
  },
  
  spinner: {
    width: '32px',
    height: '32px',
    border: `3px solid ${colors.gray200}`,
    borderTopColor: colors.primary,
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
    marginBottom: spacing.md,
  },
  
  text: {
    fontSize: typography.sm,
    color: colors.gray500,
  },
}

// =============================================================================
// COMBINED PAGE STYLES (for backward compatibility)
// =============================================================================

export const createPageStyles = (customStyles = {}) => ({
  ...pageStyles,
  ...searchStyles,
  ...tableStyles,
  ...formStyles,
  ...modalStyles,
  ...paginationStyles,
  
  // Button shortcuts
  btnPrimary: { ...buttonStyles.base, ...buttonStyles.primary },
  btnSecondary: { ...buttonStyles.base, ...buttonStyles.secondary },
  btnDanger: { ...buttonStyles.base, ...buttonStyles.danger },
  btnSuccess: { ...buttonStyles.base, ...buttonStyles.success },
  btnGhost: { ...buttonStyles.base, ...buttonStyles.ghost },
  btnSmall: buttonStyles.small,
  btnLarge: buttonStyles.large,
  btnIcon: buttonStyles.icon,
  
  // Card shortcuts
  ...cardStyles,
  
  // Additional common styles
  recordsPerPageSelect: searchStyles.select,
  statusSelect: searchStyles.select,
  paginationContainer: paginationStyles.container,
  paginationBtn: paginationStyles.button,
  paginationBtnDisabled: paginationStyles.buttonDisabled,
  pageInfo: paginationStyles.pageInfo,
  modal: modalStyles.overlay,
  modalContent: modalStyles.content,
  modalHeader: modalStyles.header,
  modalTitle: modalStyles.title,
  modalBody: modalStyles.body,
  closeBtn: modalStyles.closeBtn,
  
  // Custom overrides
  ...customStyles,
})

// Default export
export default {
  colors,
  typography,
  spacing,
  pageStyles,
  searchStyles,
  buttonStyles,
  tableStyles,
  cardStyles,
  statCardStyles,
  formStyles,
  modalStyles,
  paginationStyles,
  badgeStyles,
  loadingStyles,
  createPageStyles,
  getButtonStyle,
  getBadgeStyle,
}
