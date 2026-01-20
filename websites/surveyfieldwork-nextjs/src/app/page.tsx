import { Header, Footer } from '@/components/layout'
import { Hero, Services, About, Testimonials, Contact, CTA } from '@/components/sections'
import { getHomeContent } from '@/lib/content-service'

// Revalidate every 60 seconds for ISR
export const revalidate = 60

export default async function HomePage() {
  // Fetch content with API fallback to static
  const { data: content, source } = await getHomeContent()
  
  // Log content source for debugging (remove in production)
  if (process.env.NODE_ENV === 'development') {
    console.log(`[Home] Content source: ${source}`)
  }

  return (
    <>
      <Header />
      <main>
        <Hero content={content.hero} />
        <Services content={content.services} />
        <About content={content.about} />
        <Testimonials content={content.testimonials} />
        <CTA content={content.cta} />
        <Contact content={content.contact} />
      </main>
      <Footer />
    </>
  )
}
