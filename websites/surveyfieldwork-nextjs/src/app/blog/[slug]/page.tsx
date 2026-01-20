import { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Image from 'next/image'
import Link from 'next/link'
import { Header, Footer } from '@/components/layout'
import { Calendar, Clock, ArrowLeft, Share2, Linkedin, Twitter, Facebook } from 'lucide-react'
import { formatDate } from '@/lib/utils'

interface BlogPostPageProps {
  params: Promise<{ slug: string }>
}

async function getBlogPost(slug: string) {
  // This will fetch from the CRM API
  // For now, return placeholder data
  const posts: Record<string, any> = {
    'future-online-panel-research-2024': {
      id: '1',
      title: 'The Future of Online Panel Research: Trends to Watch in 2024',
      slug: 'future-online-panel-research-2024',
      content: `
        <p>The landscape of online panel research is evolving rapidly, driven by technological advancements and changing respondent expectations. As we look ahead to 2024, several key trends are emerging that will shape how we conduct market research.</p>
        
        <h2>1. AI-Powered Quality Control</h2>
        <p>Artificial intelligence is revolutionizing how we ensure data quality. Advanced algorithms can now detect fraudulent responses in real-time, analyzing patterns in response timing, consistency, and even linguistic markers to identify bad actors before they contaminate your data.</p>
        
        <h2>2. Mobile-First Research Design</h2>
        <p>With over 60% of survey responses now coming from mobile devices, designing mobile-first surveys is no longer optional. This means rethinking question formats, reducing survey length, and optimizing for touch-screen interactions.</p>
        
        <h2>3. Passive Data Collection</h2>
        <p>Traditional surveys are being supplemented with passive data collection methods. With proper consent, researchers can now gather behavioral data that provides richer insights than self-reported information alone.</p>
        
        <h2>4. Privacy-First Approaches</h2>
        <p>With regulations like GDPR and CCPA becoming more stringent, privacy-first research methodologies are essential. This includes anonymization techniques, consent management, and transparent data handling practices.</p>
        
        <h2>5. Hybrid Research Methods</h2>
        <p>The future lies in combining quantitative and qualitative methods seamlessly. Video interviews, online communities, and traditional surveys are being integrated to provide more comprehensive insights.</p>
        
        <h2>Conclusion</h2>
        <p>Staying ahead of these trends will be crucial for researchers looking to deliver high-quality insights in 2024 and beyond. At Survey Fieldwork, we're continuously innovating to ensure our clients have access to the latest research methodologies.</p>
      `,
      excerpt: 'Discover the key trends shaping the online panel research industry and how to prepare your research strategy for the coming year.',
      featuredImage: '/assets/images/blog/post1.jpg',
      category: 'Industry Trends',
      tags: ['Market Research', 'Trends', 'AI', 'Data Quality'],
      author: {
        name: 'Dr. Sarah Johnson',
        avatar: '/assets/images/team/sarah.jpg',
        bio: 'Head of Research at Survey Fieldwork with 15+ years of experience in market research.',
      },
      publishedAt: '2024-01-15',
      readTime: '5 min read',
    },
  }

  return posts[slug] || null
}

export async function generateMetadata({ params }: BlogPostPageProps): Promise<Metadata> {
  const { slug } = await params
  const post = await getBlogPost(slug)
  
  if (!post) {
    return { title: 'Post Not Found' }
  }

  return {
    title: `${post.title} | Survey Fieldwork Blog`,
    description: post.excerpt,
    openGraph: {
      title: post.title,
      description: post.excerpt,
      images: [post.featuredImage],
    },
  }
}

export default async function BlogPostPage({ params }: BlogPostPageProps) {
  const { slug } = await params
  const post = await getBlogPost(slug)

  if (!post) {
    notFound()
  }

  return (
    <>
      <Header />
      <main className="pt-24">
        {/* Hero */}
        <section className="bg-gradient-to-br from-secondary-50 via-white to-primary-50/30 py-12 md:py-16">
          <div className="container-custom">
            <Link 
              href="/blog"
              className="inline-flex items-center gap-2 text-secondary-600 hover:text-primary-600 mb-6"
            >
              <ArrowLeft size={18} />
              Back to Blog
            </Link>

            <div className="max-w-4xl">
              <span className="inline-block px-3 py-1 bg-primary-100 text-primary-700 text-sm font-medium rounded-full mb-4">
                {post.category}
              </span>
              <h1 className="text-3xl md:text-4xl lg:text-5xl font-bold text-secondary-900 mb-6">
                {post.title}
              </h1>
              
              <div className="flex flex-wrap items-center gap-6 text-secondary-600">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-full bg-secondary-200 overflow-hidden">
                    <Image
                      src={post.author.avatar}
                      alt={post.author.name}
                      width={48}
                      height={48}
                      className="w-full h-full object-cover"
                    />
                  </div>
                  <div>
                    <div className="font-medium text-secondary-900">{post.author.name}</div>
                    <div className="text-sm">{post.author.bio}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Calendar size={18} />
                  {formatDate(post.publishedAt)}
                </div>
                <div className="flex items-center gap-2">
                  <Clock size={18} />
                  {post.readTime}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Featured Image */}
        <section className="container-custom py-8">
          <div className="relative aspect-video max-w-4xl rounded-2xl overflow-hidden bg-secondary-100">
            <Image
              src={post.featuredImage}
              alt={post.title}
              fill
              className="object-cover"
              priority
            />
          </div>
        </section>

        {/* Content */}
        <section className="container-custom py-12">
          <div className="grid lg:grid-cols-4 gap-12">
            {/* Article Content */}
            <article className="lg:col-span-3">
              <div 
                className="prose prose-lg max-w-none prose-headings:text-secondary-900 prose-p:text-secondary-600 prose-a:text-primary-600"
                dangerouslySetInnerHTML={{ __html: post.content }}
              />

              {/* Tags */}
              <div className="mt-8 pt-8 border-t border-secondary-200">
                <h4 className="font-semibold text-secondary-900 mb-3">Tags</h4>
                <div className="flex flex-wrap gap-2">
                  {post.tags.map((tag: string) => (
                    <span
                      key={tag}
                      className="px-3 py-1 bg-secondary-100 text-secondary-600 text-sm rounded-full"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>

              {/* Share */}
              <div className="mt-8 pt-8 border-t border-secondary-200">
                <h4 className="font-semibold text-secondary-900 mb-3">Share this article</h4>
                <div className="flex gap-3">
                  <a
                    href={`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(`https://surveyfieldwork.com/blog/${post.slug}`)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="w-10 h-10 bg-[#0077B5] text-white rounded-full flex items-center justify-center hover:opacity-90 transition-opacity"
                  >
                    <Linkedin size={20} />
                  </a>
                  <a
                    href={`https://twitter.com/intent/tweet?url=${encodeURIComponent(`https://surveyfieldwork.com/blog/${post.slug}`)}&text=${encodeURIComponent(post.title)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="w-10 h-10 bg-[#1DA1F2] text-white rounded-full flex items-center justify-center hover:opacity-90 transition-opacity"
                  >
                    <Twitter size={20} />
                  </a>
                  <a
                    href={`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(`https://surveyfieldwork.com/blog/${post.slug}`)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="w-10 h-10 bg-[#1877F2] text-white rounded-full flex items-center justify-center hover:opacity-90 transition-opacity"
                  >
                    <Facebook size={20} />
                  </a>
                </div>
              </div>
            </article>

            {/* Sidebar */}
            <aside className="lg:col-span-1">
              <div className="sticky top-24">
                <div className="bg-secondary-50 rounded-2xl p-6 mb-6">
                  <h4 className="font-bold text-secondary-900 mb-4">Subscribe to our newsletter</h4>
                  <p className="text-sm text-secondary-600 mb-4">
                    Get the latest market research insights delivered to your inbox.
                  </p>
                  <input
                    type="email"
                    placeholder="Enter your email"
                    className="w-full px-4 py-2 rounded-lg border border-secondary-200 mb-3"
                  />
                  <button className="btn-primary w-full justify-center text-sm">
                    Subscribe
                  </button>
                </div>

                <div className="bg-gradient-to-br from-primary-500 to-accent-500 rounded-2xl p-6 text-white">
                  <h4 className="font-bold mb-2">Need research support?</h4>
                  <p className="text-sm text-white/80 mb-4">
                    Book a free consultation with our experts.
                  </p>
                  <Link
                    href="/#book"
                    className="inline-block w-full text-center px-4 py-2 bg-white text-primary-600 font-medium rounded-lg hover:bg-white/90 transition-colors"
                  >
                    Get Started
                  </Link>
                </div>
              </div>
            </aside>
          </div>
        </section>
      </main>
      <Footer />
    </>
  )
}
