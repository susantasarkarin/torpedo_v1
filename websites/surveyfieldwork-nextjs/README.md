# SurveyFieldwork.com - Next.js Website

This is the modernized Next.js 14 website for Survey Fieldwork, replacing the legacy WordPress site.

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Styling**: Tailwind CSS 3.4
- **Animations**: Framer Motion
- **Icons**: Lucide React
- **TypeScript**: For type safety
- **API**: Connects to Torpedo CRM backend for CMS data

## Features

- 🚀 Server-side rendering and static generation
- 📱 Fully responsive design
- 🎨 Modern UI with Tailwind CSS
- ⚡ Optimized performance
- 🔍 SEO optimized with metadata API
- 📊 Google Analytics & GTM integration
- 📝 Blog with dynamic routing
- 📧 Contact form with validation
- 🎯 CRM-controlled content via API

## Getting Started

### Prerequisites

- Node.js 18+ 
- npm or yarn
- Access to Torpedo CRM backend (for CMS features)

### Installation

```bash
# Install dependencies
npm install

# Create environment file
cp .env.example .env.local

# Run development server
npm run dev
```

### Environment Variables

Create a `.env.local` file with:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_GTM_ID=GTM-K5BX7PV2
NEXT_PUBLIC_GA_ID=G-HFZMW72Z32
```

## Project Structure

```
src/
├── app/                    # Next.js App Router pages
│   ├── blog/               # Blog pages
│   │   ├── [slug]/         # Dynamic blog post pages
│   │   └── page.tsx        # Blog listing
│   ├── layout.tsx          # Root layout
│   └── page.tsx            # Home page
├── components/
│   ├── layout/             # Header, Footer
│   └── sections/           # Page sections (Hero, Services, etc.)
├── lib/
│   ├── api.ts              # API client for CRM
│   └── utils.ts            # Utility functions
└── styles/
    └── globals.css         # Global styles + Tailwind
```

## Available Scripts

```bash
# Development
npm run dev           # Start development server
npm run build         # Build for production
npm run start         # Start production server
npm run lint          # Run ESLint
npm run type-check    # Run TypeScript checks
```

## Deployment

### Build for Production

```bash
npm run build
```

### Deploy with PM2

```bash
# Install PM2 globally
npm install -g pm2

# Start with PM2
pm2 start npm --name "surveyfieldwork" -- start -- -p 3001

# Save PM2 configuration
pm2 save
```

### Nginx Configuration

```nginx
server {
    listen 80;
    server_name surveyfieldwork.com www.surveyfieldwork.com;
    
    location / {
        proxy_pass http://localhost:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

## Content Management

This website fetches content from the Torpedo CRM Marketing module:

- **Pages**: Managed via CRM > Marketing > Pages
- **Blog Posts**: Managed via CRM > Marketing > Blog
- **Navigation**: Managed via CRM > Marketing > Websites > Navigation
- **Media**: Uploaded via CRM > Marketing > Media

## Assets

Place images in the `public/assets/images/` directory:

```
public/assets/images/
├── logo.png                # Main logo
├── logo-white.png          # White version for dark backgrounds
├── hero-visual.png         # Hero section image
├── about-team.jpg          # About section image
├── blog/                   # Blog post images
├── testimonials/           # Testimonial avatars
├── clients/                # Client logos
└── team/                   # Team member photos
```

## Contributing

1. Create a feature branch from `main`
2. Make your changes
3. Run `npm run lint` and `npm run type-check`
4. Submit a pull request

## License

Private - Cogentix Research Pvt Ltd

---

Built with ❤️ by Cogentix Research
