/**
 * Static Content with CRM Override Support
 * 
 * This file contains the default content that matches the original WordPress site.
 * Content can be overridden from the CRM Marketing module.
 * All content is SEO-monitored by AI.
 */

// Site-wide configuration
export const siteConfig = {
  name: 'Survey Fieldwork',
  tagline: 'Where Data Meets Strategy',
  description: 'Partner with us to gain a competitive edge, seize opportunities, and drive success in your industry. Experience the power of market research and unlock your business\'s full potential today.',
  domain: 'surveyfieldwork.com',
  company: 'Cogentix Research Pvt Ltd',
  email: 'info@surveyfieldwork.com',
  phone: '+91 98765 43210',
  address: 'Kolkata, West Bengal, India',
  social: {
    linkedin: 'https://www.linkedin.com/company/surveyfieldwork/',
    twitter: 'https://twitter.com/surveyfieldwork',
    facebook: 'https://facebook.com/surveyfieldwork',
    instagram: 'https://instagram.com/surveyfieldwork',
  },
  analytics: {
    gtmId: 'GTM-K5BX7PV2',
    gaId: 'G-HFZMW72Z32',
    linkedinPartnerId: '7281020',
  },
}

// Navigation items
export const navigation = [
  { label: 'Home', href: '/' },
  { label: 'About Us', href: '/#about' },
  { 
    label: 'Solutions', 
    href: '#',
    children: [
      { 
        label: 'Online Sampling',
        children: [
          { label: 'Audience Sampling', href: '/#audience-sampling' },
          { label: 'Enterprise Solutions', href: '/#enterprise-solutions' },
          { label: 'Security Measures', href: '/#security-measures' },
        ]
      },
      { label: 'Survey Programming & Hosting', href: '/#survey' },
      { label: 'Qualitative Fieldwork', href: '/#fieldwork' },
      { label: 'Market Research & Insights', href: '/#market-research' },
    ]
  },
  { label: 'Blogs', href: '/blog' },
  { label: 'Join Panel', href: 'https://panel.surveyfieldwork.com' },
  { label: 'Book Free Consultation', href: '/#book' },
]

// Hero section content
export const heroContent = {
  badges: ['Trusted', 'Experienced', 'Professional'],
  headline: 'Where Data Meets Strategy',
  subheadline: 'Partner with us to gain a competitive edge, seize opportunities, and drive success in your industry. Experience the power of market research and unlock your business\'s full potential today.',
  primaryCta: { label: 'Book Free Consultation', href: '/#book' },
  secondaryCta: { label: 'Learn More', href: '/#about' },
  stats: [
    { value: '50+', label: 'Countries' },
    { value: '1M+', label: 'Respondents' },
    { value: '500+', label: 'Projects' },
  ],
  seo: {
    focusKeyword: 'market research services',
    keywords: ['market research', 'data collection', 'survey fieldwork', 'audience sampling'],
  }
}

// Services section content
export const servicesContent = {
  sectionTitle: 'Our Solutions',
  headline: 'Comprehensive Research Services',
  description: 'From audience sampling to market insights, we provide end-to-end research solutions tailored to your business needs.',
  services: [
    {
      id: 'audience-sampling',
      icon: 'Users',
      title: 'Audience Sampling',
      description: 'Access diverse, targeted respondent panels across B2B and B2C segments worldwide. Quality-assured data collection for your research needs.',
      features: ['Global Panel Access', 'Quality Screening', 'Niche Targeting'],
      color: 'primary',
      seo: {
        focusKeyword: 'audience sampling',
        keywords: ['respondent panel', 'B2B sampling', 'B2C research', 'targeted audience'],
      }
    },
    {
      id: 'enterprise-solutions',
      icon: 'Building2',
      title: 'Enterprise Solutions',
      description: 'Custom research solutions designed for large organizations with complex data collection requirements and multi-market studies.',
      features: ['Custom Panels', 'Multi-Market Studies', 'Dedicated Support'],
      color: 'accent',
      seo: {
        focusKeyword: 'enterprise market research',
        keywords: ['corporate research', 'multi-market studies', 'custom panels'],
      }
    },
    {
      id: 'security-measures',
      icon: 'Shield',
      title: 'Security Measures',
      description: 'Industry-leading security protocols to ensure data integrity, respondent verification, and fraud prevention in all surveys.',
      features: ['Fraud Detection', 'Data Encryption', 'GDPR Compliant'],
      color: 'primary',
      seo: {
        focusKeyword: 'survey data security',
        keywords: ['fraud detection', 'GDPR compliance', 'data encryption', 'respondent verification'],
      }
    },
    {
      id: 'survey-programming',
      icon: 'MonitorPlay',
      title: 'Survey Programming & Hosting',
      description: 'Expert survey design and programming services with secure hosting infrastructure for seamless data collection.',
      features: ['Custom Programming', 'Multi-device Support', 'Real-time Tracking'],
      color: 'accent',
      seo: {
        focusKeyword: 'survey programming',
        keywords: ['survey design', 'questionnaire programming', 'survey hosting'],
      }
    },
    {
      id: 'qualitative-fieldwork',
      icon: 'MessageCircle',
      title: 'Qualitative Fieldwork',
      description: 'In-depth qualitative research including focus groups, IDIs, online communities, and ethnographic studies.',
      features: ['Focus Groups', 'In-Depth Interviews', 'Online Communities'],
      color: 'primary',
      seo: {
        focusKeyword: 'qualitative research',
        keywords: ['focus groups', 'in-depth interviews', 'ethnographic studies', 'online communities'],
      }
    },
    {
      id: 'market-research',
      icon: 'TrendingUp',
      title: 'Market Research & Insights',
      description: 'Comprehensive market analysis and strategic insights to drive business decisions and identify growth opportunities.',
      features: ['Market Analysis', 'Consumer Insights', 'Trend Forecasting'],
      color: 'accent',
      seo: {
        focusKeyword: 'market research insights',
        keywords: ['market analysis', 'consumer insights', 'trend forecasting', 'competitive analysis'],
      }
    },
  ],
  seo: {
    focusKeyword: 'market research services',
    keywords: ['research solutions', 'data collection services', 'survey services'],
  }
}

// About section content
export const aboutContent = {
  badge: 'About Us',
  title: 'Your Trusted Partner in',
  titleHighlight: 'Market Research',
  description: {
    primary: 'Survey Fieldwork, a division of Cogentix Research Pvt Ltd, is a leading provider of data collection and market research services. With over 15 years of industry experience, we\'ve helped hundreds of businesses make data-driven decisions.',
    secondary: 'Our global panel of over 1 million respondents spans 50+ countries, enabling us to deliver quality insights across diverse markets and demographics. We combine cutting-edge technology with rigorous quality controls to ensure every data point is accurate and actionable.',
  },
  features: [
    'ISO 27001 Certified Data Security',
    'GDPR & CCPA Compliant Processes',
    'ESOMAR Member Organization',
    'Real-time Quality Monitoring',
    'Multi-language Support',
    '24/7 Technical Assistance',
  ],
  highlights: [
    { icon: 'Globe', value: '50+', label: 'Countries Covered' },
    { icon: 'Users', value: '1M+', label: 'Panel Members' },
    { icon: 'Award', value: '15+', label: 'Years Experience' },
  ],
  cta: {
    primary: { text: 'Get Started', href: '/#book' },
    secondary: { text: 'Meet Our Team', href: '/#team' },
  },
  image: '/assets/images/about-team.jpg',
  seo: {
    focusKeyword: 'market research company',
    keywords: ['research company India', 'data collection company', 'ESOMAR member', 'ISO 27001 certified'],
  }
}

// Testimonials content
export const testimonialsContent = {
  badge: 'Testimonials',
  title: 'What Our',
  titleHighlight: 'Clients Say',
  description: 'Don\'t just take our word for it. Here\'s what industry leaders have to say about working with Survey Fieldwork.',
  testimonials: [
    {
      id: '1',
      name: 'Sarah Johnson',
      role: 'Head of Research',
      company: 'Global Insights Inc.',
      image: '/assets/images/testimonials/sarah.jpg',
      content: 'Survey Fieldwork has been our go-to partner for panel research. Their quality controls and fast turnaround times have consistently exceeded our expectations.',
      rating: 5,
    },
    {
      id: '2',
      name: 'Michael Chen',
      role: 'Market Research Director',
      company: 'TechCorp Solutions',
      image: '/assets/images/testimonials/michael.jpg',
      content: 'The team at Survey Fieldwork truly understands B2B research. Their ability to reach niche audiences has been invaluable for our product development.',
      rating: 5,
    },
    {
      id: '3',
      name: 'Emma Williams',
      role: 'VP of Consumer Insights',
      company: 'RetailMax',
      image: '/assets/images/testimonials/emma.jpg',
      content: 'Working with Survey Fieldwork has transformed how we collect consumer data. Their security measures and GDPR compliance give us complete peace of mind.',
      rating: 5,
    },
    {
      id: '4',
      name: 'David Kumar',
      role: 'Research Manager',
      company: 'HealthFirst Research',
      image: '/assets/images/testimonials/david.jpg',
      content: 'The qualitative fieldwork services are exceptional. Their moderators are skilled at extracting deep insights that drive our strategic decisions.',
      rating: 5,
    },
  ],
  clients: [
    { name: 'Client 1', logo: '/assets/images/clients/client1.png' },
    { name: 'Client 2', logo: '/assets/images/clients/client2.png' },
    { name: 'Client 3', logo: '/assets/images/clients/client3.png' },
    { name: 'Client 4', logo: '/assets/images/clients/client4.png' },
    { name: 'Client 5', logo: '/assets/images/clients/client5.png' },
    { name: 'Client 6', logo: '/assets/images/clients/client6.png' },
  ],
}

// Contact section content
export const contactContent = {
  badge: 'Contact Us',
  title: 'Book Your Free',
  titleHighlight: 'Consultation',
  description: 'Ready to unlock the power of data-driven insights? Get in touch with our team to discuss your research needs and how we can help you achieve your goals.',
  whyChooseUs: {
    title: 'Why Choose Us?',
    items: [
      'Free initial consultation',
      'Custom solutions for every budget',
      'Fast turnaround times',
      'Dedicated project manager',
    ],
  },
  contactInfo: [
    { icon: 'Mail', title: 'Email Us', details: 'info@surveyfieldwork.com', href: 'mailto:info@surveyfieldwork.com' },
    { icon: 'Phone', title: 'Call Us', details: '+91 98765 43210', href: 'tel:+919876543210' },
    { icon: 'MapPin', title: 'Visit Us', details: 'Kolkata, West Bengal, India', href: '#' },
    { icon: 'Clock', title: 'Working Hours', details: 'Mon - Fri: 9AM - 6PM IST', href: '#' },
  ],
  form: {
    title: 'Get In Touch',
    services: [
      { value: 'audience-sampling', label: 'Audience Sampling' },
      { value: 'enterprise', label: 'Enterprise Solutions' },
      { value: 'survey', label: 'Survey Programming & Hosting' },
      { value: 'qualitative', label: 'Qualitative Fieldwork' },
      { value: 'market-research', label: 'Market Research & Insights' },
      { value: 'other', label: 'Other' },
    ],
    submitButton: 'Send Message',
  },
}

// CTA section content
export const ctaContent = {
  badge: 'Ready to Get Started?',
  title: 'Transform Your Research with',
  titleHighlight: 'Data-Driven Insights',
  description: 'Join hundreds of businesses that trust Survey Fieldwork for their market research needs. Let\'s unlock your business\'s full potential together.',
  primaryCta: { text: 'Book Free Consultation', href: '/#book' },
  secondaryCta: { text: 'Join Our Panel', href: 'https://panel.surveyfieldwork.com' },
  stats: [
    { value: '50+', label: 'Countries' },
    { value: '1M+', label: 'Panel Members' },
    { value: '500+', label: 'Projects' },
    { value: '98%', label: 'Satisfaction' },
  ],
}

// Footer content
export const footerContent = {
  description: 'Survey Fieldwork is a trusted partner for businesses seeking top-notch data collection and market research services. We specialize in audience sampling, survey programming, and qualitative fieldwork.',
  links: {
    solutions: [
      { label: 'Audience Sampling', href: '/#audience-sampling' },
      { label: 'Enterprise Solutions', href: '/#enterprise-solutions' },
      { label: 'Security Measures', href: '/#security-measures' },
      { label: 'Survey Programming', href: '/#survey' },
      { label: 'Qualitative Fieldwork', href: '/#fieldwork' },
      { label: 'Market Research', href: '/#market-research' },
    ],
    company: [
      { label: 'About Us', href: '/#about' },
      { label: 'Our Team', href: '/#team' },
      { label: 'Careers', href: '/careers' },
      { label: 'Blog', href: '/blog' },
      { label: 'Contact', href: '/#contact' },
    ],
    legal: [
      { label: 'Privacy Policy', href: '/privacy-policy' },
      { label: 'Terms of Service', href: '/terms' },
      { label: 'Cookie Policy', href: '/cookies' },
      { label: 'GDPR Compliance', href: '/gdpr' },
    ],
  },
}

// SEO defaults for all pages
export const seoDefaults = {
  home: {
    title: 'Survey Fieldwork | Market Research & Data Collection Services',
    description: 'Survey Fieldwork offers comprehensive market research services including audience sampling, survey programming, qualitative fieldwork, and enterprise solutions. Trusted by 500+ clients worldwide.',
    keywords: ['market research', 'survey fieldwork', 'audience sampling', 'data collection', 'qualitative research', 'B2B research', 'B2C research'],
    ogImage: '/assets/images/og-home.jpg',
  },
  blog: {
    title: 'Blog | Survey Fieldwork - Market Research Insights',
    description: 'Explore our latest insights on market research, audience sampling, survey methodology, and data collection best practices.',
    keywords: ['market research blog', 'research insights', 'survey methodology', 'data collection tips'],
    ogImage: '/assets/images/og-blog.jpg',
  },
  about: {
    title: 'About Us | Survey Fieldwork - Your Research Partner',
    description: 'Learn about Survey Fieldwork, a division of Cogentix Research with 15+ years of experience in market research and data collection.',
    keywords: ['about survey fieldwork', 'market research company', 'cogentix research', 'research partner'],
    ogImage: '/assets/images/og-about.jpg',
  },
}

// Blog posts (static fallback)
export const blogPosts = [
  {
    id: '1',
    title: 'The Future of Online Panel Research: Trends to Watch in 2024',
    slug: 'future-online-panel-research-2024',
    excerpt: 'Discover the key trends shaping the online panel research industry and how to prepare your research strategy for the coming year.',
    content: `<p>The landscape of online panel research is evolving rapidly, driven by technological advancements and changing respondent expectations. As we look ahead to 2024, several key trends are emerging that will shape how we conduct market research.</p>
    
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
<p>Staying ahead of these trends will be crucial for researchers looking to deliver high-quality insights in 2024 and beyond. At Survey Fieldwork, we're continuously innovating to ensure our clients have access to the latest research methodologies.</p>`,
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
    seo: {
      title: 'Future of Online Panel Research 2024 | Survey Fieldwork',
      description: 'Discover key trends in online panel research for 2024 including AI quality control, mobile-first design, and privacy-first approaches.',
      focusKeyword: 'online panel research trends',
      keywords: ['panel research', 'research trends 2024', 'AI in research', 'mobile surveys'],
    }
  },
  {
    id: '2',
    title: 'How to Ensure Data Quality in B2B Market Research',
    slug: 'data-quality-b2b-market-research',
    excerpt: 'Learn proven strategies for maintaining high data quality standards in your B2B research projects.',
    content: `<p>Data quality is the foundation of any successful B2B market research project. Poor quality data leads to flawed insights and misguided business decisions.</p>
    
<h2>Key Strategies for B2B Data Quality</h2>
<p>Implementing robust screening questions, verification processes, and quality checks throughout the research process ensures reliable results.</p>`,
    featuredImage: '/assets/images/blog/post2.jpg',
    category: 'Best Practices',
    tags: ['B2B Research', 'Data Quality', 'Best Practices'],
    author: {
      name: 'Michael Chen',
      avatar: '/assets/images/team/michael.jpg',
      bio: 'Senior Research Director specializing in B2B methodology.',
    },
    publishedAt: '2024-01-10',
    readTime: '7 min read',
    seo: {
      title: 'B2B Market Research Data Quality Guide | Survey Fieldwork',
      description: 'Learn proven strategies for maintaining high data quality in B2B market research projects.',
      focusKeyword: 'B2B data quality',
      keywords: ['B2B research', 'data quality', 'research methodology'],
    }
  },
  {
    id: '3',
    title: 'GDPR Compliance in Market Research: A Complete Guide',
    slug: 'gdpr-compliance-market-research-guide',
    excerpt: 'Everything you need to know about maintaining GDPR compliance in your market research activities.',
    featuredImage: '/assets/images/blog/post3.jpg',
    category: 'Compliance',
    tags: ['GDPR', 'Compliance', 'Data Privacy'],
    author: {
      name: 'Emma Williams',
      avatar: '/assets/images/team/emma.jpg',
      bio: 'Compliance Officer and Data Privacy Expert.',
    },
    publishedAt: '2024-01-05',
    readTime: '10 min read',
    seo: {
      title: 'GDPR Compliance for Market Research | Survey Fieldwork',
      description: 'Complete guide to GDPR compliance in market research including consent, data handling, and respondent rights.',
      focusKeyword: 'GDPR market research',
      keywords: ['GDPR compliance', 'data privacy', 'research compliance'],
    }
  },
]

// Type definitions
export interface ContentSection {
  id: string
  type: 'hero' | 'services' | 'about' | 'testimonials' | 'cta' | 'contact' | 'custom'
  content: Record<string, any>
  seo?: {
    focusKeyword?: string
    keywords?: string[]
  }
  lastModified?: string
  modifiedBy?: string
}

export interface PageContent {
  slug: string
  title: string
  sections: ContentSection[]
  seo: {
    title: string
    description: string
    keywords: string[]
    ogImage?: string
    focusKeyword?: string
    canonicalUrl?: string
  }
  lastAnalyzed?: string
  seoScore?: number
}
