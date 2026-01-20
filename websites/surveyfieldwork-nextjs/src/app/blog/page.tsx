import { Metadata } from 'next'
import { Header, Footer } from '@/components/layout'
import BlogList from './BlogList'

export const metadata: Metadata = {
  title: 'Blog | Survey Fieldwork - Market Research Insights',
  description: 'Explore our latest insights on market research, audience sampling, survey methodology, and data collection best practices.',
}

async function getBlogPosts() {
  // This will fetch from the CRM API
  // For now, return placeholder data
  return [
    {
      id: '1',
      title: 'The Future of Online Panel Research: Trends to Watch in 2024',
      slug: 'future-online-panel-research-2024',
      excerpt: 'Discover the key trends shaping the online panel research industry and how to prepare your research strategy for the coming year.',
      featuredImage: '/assets/images/blog/post1.jpg',
      category: 'Industry Trends',
      author: { name: 'Dr. Sarah Johnson', avatar: '/assets/images/team/sarah.jpg' },
      publishedAt: '2024-01-15',
      readTime: '5 min read',
    },
    {
      id: '2',
      title: 'How to Ensure Data Quality in B2B Market Research',
      slug: 'data-quality-b2b-market-research',
      excerpt: 'Learn proven strategies for maintaining high data quality standards in your B2B research projects.',
      featuredImage: '/assets/images/blog/post2.jpg',
      category: 'Best Practices',
      author: { name: 'Michael Chen', avatar: '/assets/images/team/michael.jpg' },
      publishedAt: '2024-01-10',
      readTime: '7 min read',
    },
    {
      id: '3',
      title: 'GDPR Compliance in Market Research: A Complete Guide',
      slug: 'gdpr-compliance-market-research-guide',
      excerpt: 'Everything you need to know about maintaining GDPR compliance in your market research activities.',
      featuredImage: '/assets/images/blog/post3.jpg',
      category: 'Compliance',
      author: { name: 'Emma Williams', avatar: '/assets/images/team/emma.jpg' },
      publishedAt: '2024-01-05',
      readTime: '10 min read',
    },
    {
      id: '4',
      title: 'Mobile-First Survey Design: Best Practices for Higher Response Rates',
      slug: 'mobile-first-survey-design',
      excerpt: 'Optimize your surveys for mobile devices to improve respondent experience and increase completion rates.',
      featuredImage: '/assets/images/blog/post4.jpg',
      category: 'Survey Design',
      author: { name: 'David Kumar', avatar: '/assets/images/team/david.jpg' },
      publishedAt: '2023-12-28',
      readTime: '6 min read',
    },
    {
      id: '5',
      title: 'Qualitative vs Quantitative Research: When to Use Each',
      slug: 'qualitative-vs-quantitative-research',
      excerpt: 'Understand the key differences between qualitative and quantitative research methods and when to apply each.',
      featuredImage: '/assets/images/blog/post5.jpg',
      category: 'Methodology',
      author: { name: 'Dr. Sarah Johnson', avatar: '/assets/images/team/sarah.jpg' },
      publishedAt: '2023-12-20',
      readTime: '8 min read',
    },
    {
      id: '6',
      title: 'Building a Diverse Research Panel: Strategies for Inclusive Data',
      slug: 'building-diverse-research-panel',
      excerpt: 'Learn how to build and maintain a diverse research panel that represents your target demographics.',
      featuredImage: '/assets/images/blog/post6.jpg',
      category: 'Panel Management',
      author: { name: 'Michael Chen', avatar: '/assets/images/team/michael.jpg' },
      publishedAt: '2023-12-15',
      readTime: '5 min read',
    },
  ]
}

export default async function BlogPage() {
  const posts = await getBlogPosts()

  return (
    <>
      <Header />
      <main className="pt-24">
        {/* Hero */}
        <section className="bg-gradient-to-br from-secondary-50 via-white to-primary-50/30 py-16 md:py-24">
          <div className="container-custom text-center">
            <span className="inline-block px-4 py-2 bg-primary-100 text-primary-700 text-sm font-semibold rounded-full mb-4">
              Our Blog
            </span>
            <h1 className="text-4xl md:text-5xl font-bold text-secondary-900 mb-4">
              Market Research <span className="gradient-text">Insights</span>
            </h1>
            <p className="text-lg text-secondary-600 max-w-2xl mx-auto">
              Stay updated with the latest trends, best practices, and insights in market research and data collection.
            </p>
          </div>
        </section>

        {/* Blog List */}
        <BlogList initialPosts={posts} />
      </main>
      <Footer />
    </>
  )
}
