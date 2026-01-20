/**
 * Content Service with API + Static Fallback
 * 
 * This service fetches content from the CRM API and falls back to static content
 * when the API is unavailable. All content changes are tracked for SEO monitoring.
 */

import * as staticContent from './content'
import { getWebsiteConfig, getPage, getBlogPosts, getBlogPost, type Page, type BlogPost, type BlogListItem } from './api'

// Types
export interface ContentWithSource<T> {
  data: T
  source: 'api' | 'static'
  lastFetched: string
}

/**
 * Get home page content with fallback
 */
export async function getHomeContent(): Promise<ContentWithSource<{
  hero: typeof staticContent.heroContent
  services: typeof staticContent.servicesContent
  about: typeof staticContent.aboutContent
  testimonials: typeof staticContent.testimonialsContent
  cta: typeof staticContent.ctaContent
  contact: typeof staticContent.contactContent
  seo: typeof staticContent.seoDefaults.home
}>> {
  try {
    const page = await getPage('home')
    
    if (page && page.sections.length > 0) {
      // Map API sections to content structure
      const mappedContent = mapPageSectionsToContent(page)
      return {
        data: mappedContent,
        source: 'api',
        lastFetched: new Date().toISOString()
      }
    }
  } catch (error) {
    console.error('Failed to fetch home content from API:', error)
  }
  
  // Return static content as fallback
  return {
    data: {
      hero: staticContent.heroContent,
      services: staticContent.servicesContent,
      about: staticContent.aboutContent,
      testimonials: staticContent.testimonialsContent,
      cta: staticContent.ctaContent,
      contact: staticContent.contactContent,
      seo: staticContent.seoDefaults.home,
    },
    source: 'static',
    lastFetched: new Date().toISOString()
  }
}

/**
 * Get site config with fallback
 */
export async function getSiteConfig() {
  try {
    const config = await getWebsiteConfig()
    
    if (config) {
      return {
        data: {
          ...staticContent.siteConfig,
          name: config.name || staticContent.siteConfig.name,
          analytics: {
            gtmId: config.gtmId || staticContent.siteConfig.analytics.gtmId,
            gaId: config.gaId || staticContent.siteConfig.analytics.gaId,
            linkedinPartnerId: config.linkedinPartnerId || staticContent.siteConfig.analytics.linkedinPartnerId,
          },
        },
        source: 'api' as const,
        lastFetched: new Date().toISOString()
      }
    }
  } catch (error) {
    console.error('Failed to fetch site config:', error)
  }
  
  return {
    data: staticContent.siteConfig,
    source: 'static' as const,
    lastFetched: new Date().toISOString()
  }
}

/**
 * Get navigation with fallback
 */
export async function getNavigation() {
  try {
    const config = await getWebsiteConfig()
    
    if (config && config.headerNav && config.headerNav.length > 0) {
      return {
        data: mapNavigationFromApi(config.headerNav),
        source: 'api' as const,
        lastFetched: new Date().toISOString()
      }
    }
  } catch (error) {
    console.error('Failed to fetch navigation:', error)
  }
  
  return {
    data: staticContent.navigation,
    source: 'static' as const,
    lastFetched: new Date().toISOString()
  }
}

/**
 * Get blog posts with fallback
 */
export async function getBlogPostsWithFallback(options?: {
  category?: string
  tag?: string
  page?: number
  limit?: number
}): Promise<ContentWithSource<typeof staticContent.blogPosts>> {
  try {
    const posts = await getBlogPosts(options)
    
    if (posts && posts.length > 0) {
      return {
        data: mapBlogPostsFromApi(posts),
        source: 'api',
        lastFetched: new Date().toISOString()
      }
    }
  } catch (error) {
    console.error('Failed to fetch blog posts:', error)
  }
  
  // Filter static posts if category/tag specified
  let filteredPosts = staticContent.blogPosts
  if (options?.category) {
    filteredPosts = filteredPosts.filter(p => p.category === options.category)
  }
  
  return {
    data: filteredPosts,
    source: 'static',
    lastFetched: new Date().toISOString()
  }
}

/**
 * Get single blog post with fallback
 */
export async function getBlogPostWithFallback(slug: string) {
  try {
    const post = await getBlogPost(slug)
    
    if (post) {
      return {
        data: mapSingleBlogPostFromApi(post),
        source: 'api' as const,
        lastFetched: new Date().toISOString()
      }
    }
  } catch (error) {
    console.error(`Failed to fetch blog post ${slug}:`, error)
  }
  
  // Find in static posts
  const staticPost = staticContent.blogPosts.find(p => p.slug === slug)
  
  if (staticPost) {
    return {
      data: staticPost,
      source: 'static' as const,
      lastFetched: new Date().toISOString()
    }
  }
  
  return null
}

// Helper: Map API page sections to content structure
function mapPageSectionsToContent(page: Page) {
  const sectionMap: Record<string, any> = {}
  
  for (const section of page.sections) {
    sectionMap[section.type] = section.content
  }
  
  return {
    hero: sectionMap.hero || staticContent.heroContent,
    services: sectionMap.services || staticContent.servicesContent,
    about: sectionMap.about || staticContent.aboutContent,
    testimonials: sectionMap.testimonials || staticContent.testimonialsContent,
    cta: sectionMap.cta || staticContent.ctaContent,
    contact: sectionMap.contact || staticContent.contactContent,
    seo: page.seo ? {
      title: page.seo.title || staticContent.seoDefaults.home.title,
      description: page.seo.description || staticContent.seoDefaults.home.description,
      keywords: staticContent.seoDefaults.home.keywords,
      ogImage: page.seo.ogImage || staticContent.seoDefaults.home.ogImage,
    } : staticContent.seoDefaults.home,
  }
}

// Helper: Map API navigation to local format
interface NavItem {
  label: string
  href: string
  children?: NavItem[]
}

function mapNavigationFromApi(navItems: any[]): NavItem[] {
  return navItems.map(item => ({
    label: item.label,
    href: item.link || '#',
    children: item.children ? mapNavigationFromApi(item.children) : undefined,
  }))
}

// Helper: Map API blog posts to local format
function mapBlogPostsFromApi(posts: BlogListItem[]) {
  return posts.map(post => ({
    id: post.slug,
    title: post.title,
    slug: post.slug,
    excerpt: post.excerpt || '',
    content: '',
    featuredImage: post.featured_image || '/assets/images/blog/default.jpg',
    category: post.categories[0] || 'Uncategorized',
    tags: [] as string[],
    author: {
      name: post.author_name || 'Survey Fieldwork Team',
      avatar: '/assets/images/team/default.jpg',
      bio: '',
    },
    publishedAt: post.published_at || new Date().toISOString(),
    readTime: '5 min read',
    seo: {
      title: post.title,
      description: post.excerpt || '',
      focusKeyword: '',
      keywords: [] as string[],
    }
  }))
}

// Helper: Map single API blog post
function mapSingleBlogPostFromApi(post: BlogPost) {
  return {
    id: post.slug,
    title: post.title,
    slug: post.slug,
    excerpt: post.excerpt || '',
    content: typeof post.content === 'string' ? post.content : JSON.stringify(post.content),
    featuredImage: post.featured_image || '/assets/images/blog/default.jpg',
    category: post.categories[0] || 'Uncategorized',
    tags: post.tags || [],
    author: {
      name: post.author_name || 'Survey Fieldwork Team',
      avatar: '/assets/images/team/default.jpg',
      bio: '',
    },
    publishedAt: post.published_at || new Date().toISOString(),
    readTime: '5 min read',
    seo: {
      title: post.title,
      description: post.excerpt || '',
      focusKeyword: '',
      keywords: post.tags || [],
    }
  }
}
