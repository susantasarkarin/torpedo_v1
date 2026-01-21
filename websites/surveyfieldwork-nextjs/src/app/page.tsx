import { Header, Footer } from '@/components/layout'
import { Hero, Services, About, Testimonials, Contact, EnterpriseSolutions, JoinPanel } from '@/components/sections'
import { getHomeContent } from '@/lib/content-service'

// Revalidate every 60 seconds for ISR
export const revalidate = 60

export default async function HomePage() {
  // Fetch content with API fallback to static
  const { data: content, source } = await getHomeContent()

  return (
    <>
      <Header />
      <main>
        <Hero content={content.hero} />
        <Services />
        <EnterpriseSolutions />
        <JoinPanel />
        <About content={content.about} />
        <Testimonials content={content.testimonials} />
        <Contact content={content.contact} />
      </main>
      <Footer />
    </>
  )
}
