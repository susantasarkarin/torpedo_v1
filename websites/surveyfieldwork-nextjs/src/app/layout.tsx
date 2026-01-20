import type { Metadata, Viewport } from 'next'
import { Montserrat, Open_Sans, Poppins } from 'next/font/google'
import '@/styles/globals.css'

// Fonts
const montserrat = Montserrat({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-montserrat',
})

const openSans = Open_Sans({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-open-sans',
})

const poppins = Poppins({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-poppins',
})

// Metadata
export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || 'https://surveyfieldwork.com'),
  title: {
    default: 'Survey Fieldwork | Global Data Collection & Market Research',
    template: '%s | Survey Fieldwork',
  },
  description: 'Survey Fieldwork specializes in global data collection, market research, and survey programming. We deliver high-quality insights for businesses worldwide.',
  keywords: [
    'survey fieldwork',
    'data collection',
    'market research',
    'survey programming',
    'CATI',
    'CAWI',
    'online surveys',
    'field research',
    'quantitative research',
    'qualitative research',
  ],
  authors: [{ name: 'Survey Fieldwork' }],
  creator: 'Survey Fieldwork',
  publisher: 'Survey Fieldwork',
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: 'https://surveyfieldwork.com',
    siteName: 'Survey Fieldwork',
    title: 'Survey Fieldwork | Global Data Collection & Market Research',
    description: 'Survey Fieldwork specializes in global data collection, market research, and survey programming.',
    images: [
      {
        url: '/og-image.jpg',
        width: 1200,
        height: 630,
        alt: 'Survey Fieldwork',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Survey Fieldwork | Global Data Collection & Market Research',
    description: 'Survey Fieldwork specializes in global data collection, market research, and survey programming.',
    images: ['/og-image.jpg'],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  verification: {
    google: process.env.NEXT_PUBLIC_GOOGLE_VERIFICATION,
  },
}

export const viewport: Viewport = {
  themeColor: '#3b82f6',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
}

// Root Layout
export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html 
      lang="en" 
      className={`${montserrat.variable} ${openSans.variable} ${poppins.variable}`}
    >
      <head>
        {/* Favicon */}
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/manifest.json" />
        
        {/* Preconnect to external domains */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        
        {/* Google Tag Manager - Head */}
        {process.env.NEXT_PUBLIC_GTM_ID && (
          <script
            dangerouslySetInnerHTML={{
              __html: `
                (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
                new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
                j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
                'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
                })(window,document,'script','dataLayer','${process.env.NEXT_PUBLIC_GTM_ID}');
              `,
            }}
          />
        )}
      </head>
      <body className="antialiased">
        {/* Google Tag Manager - Body */}
        {process.env.NEXT_PUBLIC_GTM_ID && (
          <noscript>
            <iframe
              src={`https://www.googletagmanager.com/ns.html?id=${process.env.NEXT_PUBLIC_GTM_ID}`}
              height="0"
              width="0"
              style={{ display: 'none', visibility: 'hidden' }}
            />
          </noscript>
        )}
        
        {children}
      </body>
    </html>
  )
}
