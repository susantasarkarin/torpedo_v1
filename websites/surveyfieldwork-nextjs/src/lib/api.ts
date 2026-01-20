/**
 * API Client for Survey Fieldwork Website
 * Fetches content from the CRM's public website API
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const DOMAIN = process.env.NEXT_PUBLIC_DOMAIN || 'surveyfieldwork.com'

// Types
export interface WebsiteConfig {
  name: string
  domain: string
  logo: string | null
  favicon: string | null
  colors: Record<string, string> | null
  fonts: Record<string, string> | null
  defaultSeo: {
    title?: string
    description?: string
    ogImage?: string
  } | null
  gtmId: string | null
  gaId: string | null
  linkedinPartnerId: string | null
  customHead: string | null
  customBody: string | null
  headerNav: NavItem[]
  footerNav: NavItem[]
}

export interface NavItem {
  id: string
  label: string
  link: string | null
  type: 'link' | 'anchor' | 'dropdown'
  children?: NavItem[]
}

export interface PageSection {
  id: string
  type: string
  order: number
  content: Record<string, any>
}

export interface Page {
  slug: string
  title: string
  sections: PageSection[]
  seo: {
    title?: string
    description?: string
    ogImage?: string
  } | null
}

export interface BlogPost {
  slug: string
  title: string
  excerpt: string | null
  content: Record<string, any> | null
  featured_image: string | null
  author_name: string | null
  categories: string[]
  tags: string[]
  published_at: string | null
}

export interface BlogListItem {
  slug: string
  title: string
  excerpt: string | null
  featured_image: string | null
  author_name: string | null
  categories: string[]
  published_at: string | null
}

export interface SitemapEntry {
  loc: string
  lastmod: string | null
  changefreq: string
  priority: number
}

// Fetch wrapper with error handling
async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`
  
  // Add domain as query param
  const separator = endpoint.includes('?') ? '&' : '?'
  const urlWithDomain = `${url}${separator}domain=${DOMAIN}`
  
  const response = await fetch(urlWithDomain, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    // Revalidate every 60 seconds for ISR
    next: { revalidate: 60 },
  })
  
  if (!response.ok) {
    if (response.status === 404) {
      return null as T
    }
    throw new Error(`API error: ${response.status} ${response.statusText}`)
  }
  
  return response.json()
}

// API Methods

/**
 * Get website configuration (settings, scripts, navigation)
 */
export async function getWebsiteConfig(): Promise<WebsiteConfig | null> {
  try {
    return await fetchAPI<WebsiteConfig>('/api/website/config')
  } catch (error) {
    console.error('Failed to fetch website config:', error)
    return null
  }
}

/**
 * Get a page by slug
 */
export async function getPage(slug: string): Promise<Page | null> {
  try {
    // Normalize slug
    const normalizedSlug = slug === '/' || slug === '' ? 'home' : slug.replace(/^\//, '')
    return await fetchAPI<Page>(`/api/website/page/${normalizedSlug}`)
  } catch (error) {
    console.error(`Failed to fetch page ${slug}:`, error)
    return null
  }
}

/**
 * Get list of blog posts
 */
export async function getBlogPosts(options?: {
  category?: string
  tag?: string
  page?: number
  limit?: number
}): Promise<BlogListItem[]> {
  try {
    const params = new URLSearchParams()
    if (options?.category) params.append('category', options.category)
    if (options?.tag) params.append('tag', options.tag)
    if (options?.page) params.append('page', options.page.toString())
    if (options?.limit) params.append('limit', options.limit.toString())
    
    const query = params.toString() ? `?${params.toString()}` : ''
    return await fetchAPI<BlogListItem[]>(`/api/website/blog${query}`)
  } catch (error) {
    console.error('Failed to fetch blog posts:', error)
    return []
  }
}

/**
 * Get blog post count
 */
export async function getBlogCount(options?: {
  category?: string
  tag?: string
}): Promise<number> {
  try {
    const params = new URLSearchParams()
    if (options?.category) params.append('category', options.category)
    if (options?.tag) params.append('tag', options.tag)
    
    const query = params.toString() ? `?${params.toString()}` : ''
    const result = await fetchAPI<{ count: number }>(`/api/website/blog/count${query}`)
    return result.count
  } catch (error) {
    console.error('Failed to fetch blog count:', error)
    return 0
  }
}

/**
 * Get single blog post by slug
 */
export async function getBlogPost(slug: string): Promise<BlogPost | null> {
  try {
    return await fetchAPI<BlogPost>(`/api/website/blog/${slug}`)
  } catch (error) {
    console.error(`Failed to fetch blog post ${slug}:`, error)
    return null
  }
}

/**
 * Get blog categories
 */
export async function getBlogCategories(): Promise<string[]> {
  try {
    const result = await fetchAPI<{ categories: string[] }>('/api/website/blog/categories')
    return result.categories
  } catch (error) {
    console.error('Failed to fetch categories:', error)
    return []
  }
}

/**
 * Get blog tags
 */
export async function getBlogTags(): Promise<string[]> {
  try {
    const result = await fetchAPI<{ tags: string[] }>('/api/website/blog/tags')
    return result.tags
  } catch (error) {
    console.error('Failed to fetch tags:', error)
    return []
  }
}

/**
 * Get recent blog posts
 */
export async function getRecentPosts(limit: number = 3): Promise<BlogListItem[]> {
  try {
    return await fetchAPI<BlogListItem[]>(`/api/website/recent-posts?limit=${limit}`)
  } catch (error) {
    console.error('Failed to fetch recent posts:', error)
    return []
  }
}

/**
 * Get sitemap data
 */
export async function getSitemap(): Promise<SitemapEntry[]> {
  try {
    return await fetchAPI<SitemapEntry[]>('/api/website/sitemap')
  } catch (error) {
    console.error('Failed to fetch sitemap:', error)
    return []
  }
}
